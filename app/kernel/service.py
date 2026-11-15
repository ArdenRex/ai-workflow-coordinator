"""ToolExecutionService: THE single trusted boundary for real-world actions.

submit():            validate -> policy -> record -> (approval | run)
execute_approved():  run only an execution whose stored input was approved
Nothing else in the system may call a tool handler.
"""
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.kernel.approvals import ApprovalService
from app.kernel.audit import input_digest, record_event
from app.kernel.errors import (ExecutionStateError, IdempotencyConflictError, KernelError,
                               PolicyDeniedError, ToolInputError, ToolNotFoundError)
from app.kernel.permissions import Principal
from app.kernel.policy import Outcome, PolicyDecision, WorkspacePolicy, effective_risk, evaluate, ExecutionLimit
from app.kernel.registry import ToolDefinition, ToolRegistry
from app.models.enums import ApprovalStatus, ExecutionStatus
from app.models.kernel import Approval, SystemEvent, ToolExecution

logger = logging.getLogger(__name__)
_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="tool-exec")


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class ExecutionContext:
    """What a tool handler is told. Deliberately contains no credentials."""
    workspace_id: str
    user_id: str
    agent: Optional[str]
    execution_id: str


class ToolExecutionService:
    def __init__(self, db: Session, registry: ToolRegistry, *,
                 policy_provider: Optional[Callable[[str], WorkspacePolicy]] = None,
                 approvals: Optional[ApprovalService] = None):
        self.db = db
        self.registry = registry
        self.policy_provider = policy_provider or (lambda workspace_id: WorkspacePolicy())
        self.approvals = approvals or ApprovalService(db, policy_provider=self.policy_provider)

    # ------------------------------------------------------------------ submit
    def submit(self, principal: Principal, tool_id: str, raw_input: Dict[str, Any], *,
               idempotency_key: Optional[str] = None) -> ToolExecution:
        ws = principal.workspace_id

        try:
            tool = self.registry.get(tool_id)
        except ToolNotFoundError:
            self._deny(principal, tool_id, "tool_not_found")
            raise

        try:
            validated = self.registry.validate_input(tool_id, raw_input)
        except ToolInputError:
            self._deny(principal, tool_id, "invalid_input")
            raise
        normalized = validated.model_dump(mode="json")   # compare/store the normalized form

        policy = self.policy_provider(ws)
        if idempotency_key:
            existing = self._find_idempotent(ws, idempotency_key)
            if existing is not None:
                return self._replay(existing, principal, tool, tool_id, normalized, policy)

        decision = evaluate(tool, principal, ws, policy)
        if decision.outcome == Outcome.DENY:
            self._deny(principal, tool_id, decision.reason_code)
            raise PolicyDeniedError(decision.reason_code, decision.message)

        if decision.outcome == Outcome.ALLOW and self._escalated(ws, policy):   # recent failures/denials: a human looks first (12.3d)
            decision = PolicyDecision(Outcome.REQUIRE_APPROVAL, "escalation_threshold", "Recent failures or denials require approval")

        if decision.outcome == Outcome.ALLOW:          # it would run now: the cap applies (a parked one is checked when it is released)
            self._enforce_limit(principal, tool_id, policy)

        execution = ToolExecution(
            workspace_id=ws, tool_id=tool_id, requested_by=principal.user_id, agent=principal.agent,
            risk_level=effective_risk(tool, policy), status=ExecutionStatus.PENDING,
            input=normalized, idempotency_key=idempotency_key)
        self.db.add(execution)
        try:
            self.db.flush()
        except IntegrityError:                     # lost a race on (workspace, idempotency_key): the winner's row is the answer (13.3)
            self.db.rollback()
            winner = self._find_idempotent(ws, idempotency_key) if idempotency_key else None
            if winner is None:
                raise
            return self._replay(winner, principal, tool, tool_id, normalized, policy)
        record_event(self.db, workspace_id=ws, event_type="execution.created", actor=principal.user_id,
                     execution_id=execution.id,
                     payload={"tool_id": tool_id, "agent": principal.agent, "policy": decision.reason_code})
        self.db.commit()

        if decision.outcome == Outcome.REQUIRE_APPROVAL:
            self.approvals.request(execution)
            return execution
        return self._run(execution, tool, principal, policy)

    # -------------------------------------------------------- execute approved
    def execute_approved(self, principal: Principal, execution_id: str) -> ToolExecution:
        execution = self.get(execution_id, principal.workspace_id)
        if execution.status != ExecutionStatus.APPROVED:
            raise ExecutionStateError("Execution is not approved")

        # Independent proof of approval: don't trust the status field alone.
        approval = self.db.scalar(select(Approval).where(
            Approval.execution_id == execution.id, Approval.workspace_id == execution.workspace_id,
            Approval.status == ApprovalStatus.APPROVED))
        if approval is None:
            self._deny(principal, execution.tool_id, "approval_missing", execution.id)
            raise ExecutionStateError("No valid approval found for execution")

        # Approval is bound to the exact input that was requested; any change voids it.
        requested = self.db.scalar(select(SystemEvent).where(
            SystemEvent.execution_id == execution.id, SystemEvent.workspace_id == execution.workspace_id,
            SystemEvent.event_type == "approval.requested"))
        if requested is None or requested.payload.get("input_sha256") != input_digest(execution.input):
            self._deny(principal, execution.tool_id, "approved_input_mismatch", execution.id)
            raise ExecutionStateError("Execution input does not match what was approved")

        tool = self.registry.get(execution.tool_id)
        policy = self.policy_provider(execution.workspace_id)
        decision = evaluate(tool, principal, execution.workspace_id, policy)
        if decision.outcome == Outcome.DENY:  # disabled/permission revoked since approval
            self._deny(principal, execution.tool_id, decision.reason_code, execution.id)
            raise PolicyDeniedError(decision.reason_code, decision.message)
        self._enforce_limit(principal, execution.tool_id, policy, execution.id)   # stays APPROVED when refused; can be retried later

        self.registry.validate_input(execution.tool_id, execution.input)  # stored, approved input only
        result = self._run(execution, tool, principal, policy)
        if result.status == ExecutionStatus.SUCCEEDED:
            self.approvals.mark_executed(approval)
        return result

    # --------------------------------------------------------------- reads
    def get(self, execution_id: str, workspace_id: str) -> ToolExecution:
        row = self.db.scalar(select(ToolExecution).where(
            ToolExecution.id == execution_id, ToolExecution.workspace_id == workspace_id))
        if row is None:
            raise ExecutionStateError("Execution not found")
        return row

    def audit_trail(self, execution_id: str, workspace_id: str) -> List[SystemEvent]:
        self.get(execution_id, workspace_id)
        return list(self.db.scalars(select(SystemEvent).where(
            SystemEvent.execution_id == execution_id, SystemEvent.workspace_id == workspace_id
        ).order_by(SystemEvent.created_at, SystemEvent.id)))

    # ------------------------------------------------------------ internals
    def _replay(self, existing: ToolExecution, principal: Principal, tool: ToolDefinition, tool_id: str,
                normalized: Dict[str, Any], policy: WorkspacePolicy) -> ToolExecution:
        """An idempotent replay returns the stored execution without running anything, but only to a caller who may
        run this tool NOW: a replay is not a way around a disabled tool or a missing permission (13.3)."""
        if existing.tool_id != tool_id or existing.input != normalized:
            raise IdempotencyConflictError("Idempotency key reused with different request")
        decision = evaluate(tool, principal, existing.workspace_id, policy)
        if decision.outcome == Outcome.DENY:
            self._deny(principal, tool_id, decision.reason_code, existing.id)
            raise PolicyDeniedError(decision.reason_code, decision.message)
        return existing

    def _find_idempotent(self, ws: str, key: str) -> Optional[ToolExecution]:
        return self.db.scalar(select(ToolExecution).where(
            ToolExecution.workspace_id == ws, ToolExecution.idempotency_key == key))

    def _deny(self, principal: Principal, tool_id: str, reason: str, execution_id: Optional[str] = None):
        record_event(self.db, workspace_id=principal.workspace_id, event_type="execution.denied",
                     actor=principal.user_id, execution_id=execution_id,
                     payload={"tool_id": tool_id, "reason": reason, "agent": principal.agent})
        self.db.commit()

    def _escalated(self, ws: str, policy: WorkspacePolicy) -> bool:
        """Escalation rule (12.3d): failed runs plus denied attempts of THIS workspace inside the window reached the threshold.
        Only ever turns ALLOW into REQUIRE_APPROVAL. Escalation does not apply to an execution a human already approved."""
        rule = policy.escalation
        if rule is None:
            return False
        since = _now() - timedelta(seconds=rule.window_seconds)
        failed = self.db.scalar(select(func.count()).select_from(ToolExecution).where(
            ToolExecution.workspace_id == ws, ToolExecution.status == ExecutionStatus.FAILED,
            ToolExecution.finished_at.is_not(None), ToolExecution.finished_at >= since)) or 0
        denied = self.db.scalar(select(func.count()).select_from(SystemEvent).where(
            SystemEvent.workspace_id == ws, SystemEvent.event_type == "execution.denied", SystemEvent.created_at >= since)) or 0
        return failed + denied >= rule.threshold

    def _enforce_limit(self, principal: Principal, tool_id: str, policy: WorkspacePolicy, execution_id: Optional[str] = None) -> None:
        """Workspace execution cap (12.3c). Counts runs that STARTED in the window (all tools, all callers, this workspace only)."""
        limit = policy.execution_limit
        if limit is None:
            return
        since = _now() - timedelta(seconds=limit.window_seconds)
        started = self.db.scalar(select(func.count()).select_from(ToolExecution).where(
            ToolExecution.workspace_id == principal.workspace_id, ToolExecution.started_at.is_not(None),
            ToolExecution.started_at >= since)) or 0
        if started >= limit.max_executions:
            self._deny(principal, tool_id, "execution_limit_reached", execution_id)
            raise PolicyDeniedError("execution_limit_reached", "The workspace's execution limit has been reached")

    def _claim(self, execution: ToolExecution, limit: Optional[ExecutionLimit] = None, policy: Optional[WorkspacePolicy] = None) -> str:
        """Atomically move PENDING/APPROVED -> RUNNING so a run can never happen twice. Returns "ok", "lost", "limit" or "escalate".

        With an execution cap, the count and the claim happen under one per-workspace lock (PostgreSQL advisory lock held to the end of
        this transaction), so parallel runs cannot all pass the check and then all start (14.2). On SQLite the recount is still done here but
        there is no cross-connection lock; SQLite is a development database."""
        ws = execution.workspace_id
        recheck = policy is not None and policy.escalation is not None and execution.status == ExecutionStatus.PENDING   # 14.6: never for an approved run
        if limit is not None or recheck:
            if self.db.get_bind().dialect.name == "postgresql":
                self.db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"execution-cap:{ws}"})
            if recheck and self._escalated(ws, policy):         # failures/denials reached the threshold after the early check: a human looks first
                self.db.commit()
                return "escalate"
        if limit is not None:
            since = _now() - timedelta(seconds=limit.window_seconds)
            started = self.db.scalar(select(func.count()).select_from(ToolExecution).where(
                ToolExecution.workspace_id == ws, ToolExecution.started_at.is_not(None), ToolExecution.started_at >= since)) or 0
            if started >= limit.max_executions:
                self.db.commit()                    # nothing is pending; this ends the transaction and releases the lock
                return "limit"
        res = self.db.execute(update(ToolExecution).where(
            ToolExecution.id == execution.id, ToolExecution.workspace_id == ws,
            ToolExecution.status.in_([ExecutionStatus.PENDING, ExecutionStatus.APPROVED])
        ).values(status=ExecutionStatus.RUNNING, started_at=_now()))
        self.db.commit()
        if res.rowcount != 1:
            return "lost"
        self.db.refresh(execution)
        return "ok"

    def _run(self, execution: ToolExecution, tool: ToolDefinition, principal: Principal, policy: WorkspacePolicy) -> ToolExecution:
        claimed = self._claim(execution, policy.execution_limit, policy)
        if claimed == "escalate":                  # tightened between the early check and the claim (14.6): park it, run nothing
            self.approvals.request(execution)
            return execution
        if claimed == "limit":                     # the cap filled up between the early check and the claim (14.2)
            was_approved = execution.status == ExecutionStatus.APPROVED
            self._deny(principal, tool.id, "execution_limit_reached", execution.id)
            if not was_approved:                   # a fresh run never started: end it. An approved one stays APPROVED and can be released later
                execution.status, execution.error, execution.finished_at = ExecutionStatus.FAILED, "execution_limit_reached", _now()
                self.db.commit()
            raise PolicyDeniedError("execution_limit_reached", "The workspace's execution limit has been reached")
        if claimed != "ok":
            raise ExecutionStateError("Execution already started or finished")
        ws = execution.workspace_id
        record_event(self.db, workspace_id=ws, event_type="execution.started", actor=execution.requested_by,
                     execution_id=execution.id, payload={"tool_id": tool.id})
        self.db.commit()

        ctx = ExecutionContext(ws, execution.requested_by, execution.agent, execution.id)
        validated = self.registry.validate_input(tool.id, execution.input)
        error: Optional[str] = None
        output: Optional[dict] = None

        if tool.handler is None:
            error = "Tool has no handler"
        else:
            for attempt in range(tool.max_retries + 1):
                try:
                    future = _POOL.submit(tool.handler, ctx, validated)
                    raw = future.result(timeout=tool.timeout_seconds)
                    output = self.registry.validate_output(tool.id, raw).model_dump(mode="json")  # verify
                    error = None
                    break
                except FutureTimeout:
                    error = "Tool timed out"
                    break                      # never retry a timeout: the effect may have happened
                except KernelError as exc:     # output verification failed
                    error = exc.code
                    break
                except Exception as exc:       # handler failure: log details, store only the type
                    logger.exception("Tool %s failed (attempt %d)", tool.id, attempt + 1)
                    error = f"Tool failed: {type(exc).__name__}"

        execution.finished_at = _now()
        if error is None:
            execution.status, execution.output, execution.error = ExecutionStatus.SUCCEEDED, output, None
        else:
            execution.status, execution.error = ExecutionStatus.FAILED, error
        record_event(self.db, workspace_id=ws, event_type=f"execution.{execution.status.value}",
                     actor=execution.requested_by, execution_id=execution.id,
                     payload={"tool_id": tool.id, "error": error})
        self.db.commit()
        return execution
