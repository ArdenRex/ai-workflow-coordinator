"""Agent runs: lifecycle state machine, hard limits, audit. Nothing here executes anything.

    QUEUED --start--> RUNNING --wait_for_approval--> WAITING_APPROVAL --resume--> RUNNING
    RUNNING --succeed--> SUCCEEDED      any non-terminal --fail--> FAILED
    any non-terminal --cancel--> CANCELLED (a RUNNING run is flagged and stops at its next checkpoint)
    any non-terminal past its deadline --> EXPIRED

Design rules
- Every status change is a compare-and-swap UPDATE (`WHERE status IN (allowed sources)`), so concurrent
  workers/cancels cannot both win and a terminal state can never be left.
- Limits (steps, tool calls, LLM calls) are charged by an atomic conditional UPDATE; the request may ask for
  less than the configured ceiling, never more. Hitting a limit fails the run with a fixed error code.
- The deadline is per stretch: queue wait, each active stretch, and the approval wait each get their own
  `expires_at`. Total work is still bounded by the step/tool/LLM budgets.
- Content-free: the goal is stored only as a digest + length; `error_code` is a fixed-vocabulary slug;
  `result` is redacted and size-capped; audit payloads carry ids, states and counters only.
- Authority: a run belongs to the user who created it and executes as that user. Users see their own runs;
  `agent:manage` (admin+) sees all runs in the workspace and may cancel them. Agent principals can drive
  only their own run's lifecycle and can never create, read other runs, or cancel. Missing and invisible
  runs are indistinguishable (RunNotFoundError).
"""
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, FrozenSet, List, Optional

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agents.errors import (InvalidRunRequestError, RunCancelledError, RunConflictError, RunExpiredError,
                               RunForbiddenError, RunLimitError, RunNotFoundError, RunStateError)
from app.agents.registry import AgentRegistry
from app.config import Settings
from app.kernel.approvals import ApprovalService
from app.kernel.audit import input_digest, record_event, redact
from app.kernel.permissions import Principal
from app.models.agents import AgentRun
from app.models.enums import AgentRunStatus as S
from app.models.enums import ExecutionStatus
from app.models.enums import ApprovalStatus
from app.models.kernel import Approval, ToolExecution

MAX_GOAL_CHARS = 4000
MAX_RESULT_BYTES = 16_000
_CODE_RE = re.compile(r"^[a-z0-9_.]{1,64}$")

ALLOWED_TRANSITIONS: Dict[S, FrozenSet[S]] = {
    S.QUEUED: frozenset({S.RUNNING, S.CANCELLED, S.EXPIRED, S.FAILED}),
    S.RUNNING: frozenset({S.WAITING_APPROVAL, S.SUCCEEDED, S.FAILED, S.CANCELLED, S.EXPIRED}),
    S.WAITING_APPROVAL: frozenset({S.RUNNING, S.FAILED, S.CANCELLED, S.EXPIRED}),
    S.SUCCEEDED: frozenset(), S.FAILED: frozenset(), S.CANCELLED: frozenset(), S.EXPIRED: frozenset(),
}
TERMINAL = frozenset(s for s, t in ALLOWED_TRANSITIONS.items() if not t)
_CHARGE = {"step": ("steps_used", "max_steps", "limit_steps"),
           "tool_call": ("tool_calls_used", "max_tool_calls", "limit_tool_calls"),
           "llm_call": ("llm_calls_used", "max_llm_calls", "limit_llm_calls")}


def is_terminal(status: S) -> bool:
    return status in TERMINAL


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is not None and dt.tzinfo is None:           # SQLite returns naive datetimes; treat as UTC
        return dt.replace(tzinfo=timezone.utc)
    return dt


class AgentRunService:
    def __init__(self, db: Session, agents: AgentRegistry, settings: Settings, *,
                 clock: Optional[Callable[[], datetime]] = None):
        self.db = db
        self.agents = agents
        self.settings = settings
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    # ---------------------------------------------------------------- create / read
    def create(self, principal: Principal, agent_id: str, goal: str, *, idempotency_key: Optional[str] = None,
               max_steps: Optional[int] = None, max_tool_calls: Optional[int] = None,
               max_llm_calls: Optional[int] = None, timeout_seconds: Optional[int] = None) -> AgentRun:
        if principal.agent is not None or not principal.can("agent:run"):
            raise RunForbiddenError("Not allowed to start agent runs")
        self.agents.get(agent_id)                                    # AgentNotFoundError if unknown
        if not isinstance(goal, str) or not goal.strip():
            raise InvalidRunRequestError("A goal is required")
        if len(goal) > MAX_GOAL_CHARS:
            raise InvalidRunRequestError(f"Goal is too long (max {MAX_GOAL_CHARS} characters)")
        if idempotency_key is not None and not 1 <= len(idempotency_key) <= 128:
            raise InvalidRunRequestError("idempotency_key must be 1-128 characters")
        s = self.settings
        steps = self._limit("max_steps", max_steps, s.agent_run_max_steps, 1)
        tools = self._limit("max_tool_calls", max_tool_calls, s.agent_run_max_tool_calls, 0)
        llms = self._limit("max_llm_calls", max_llm_calls, s.agent_run_max_llm_calls, 0)
        timeout = self._limit("timeout_seconds", timeout_seconds, s.agent_run_timeout_seconds, 5)
        digest = input_digest(goal.strip())

        if idempotency_key is not None:
            existing = self._by_idempotency(principal.workspace_id, idempotency_key)
            if existing is not None:
                return self._replay(existing, principal, agent_id, digest)

        now = self._clock()
        run = AgentRun(workspace_id=principal.workspace_id, agent_id=agent_id, requested_by=principal.user_id,
                       status=S.QUEUED, goal_digest=digest, goal_chars=len(goal.strip()),
                       idempotency_key=idempotency_key, max_steps=steps, max_tool_calls=tools,
                       max_llm_calls=llms, steps_used=0, tool_calls_used=0, llm_calls_used=0,
                       cancel_requested=False, expires_at=now + timedelta(seconds=timeout))
        self.db.add(run)
        try:
            self.db.flush()
            self._event(run, "agent_run.created", principal.user_id,
                        limits={"steps": steps, "tool_calls": tools, "llm_calls": llms, "timeout_seconds": timeout},
                        goal_chars=run.goal_chars)
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            existing = self._by_idempotency(principal.workspace_id, idempotency_key) if idempotency_key else None
            if existing is None:
                raise
            return self._replay(existing, principal, agent_id, digest)
        return run

    def get(self, principal: Principal, run_id: str) -> AgentRun:
        run = self._load(principal.workspace_id, run_id)
        if not self._can_see(principal, run):
            raise RunNotFoundError("Run not found")
        return run

    def list(self, principal: Principal, *, status: Optional[S] = None, limit: int = 50) -> List[AgentRun]:
        limit = max(1, min(int(limit), 200))
        q = select(AgentRun).where(AgentRun.workspace_id == principal.workspace_id)
        if principal.agent is not None or not principal.can("agent:manage"):
            q = q.where(AgentRun.requested_by == principal.user_id)
            if principal.agent is not None:
                q = q.where(AgentRun.agent_id == principal.agent)
        if status is not None:
            q = q.where(AgentRun.status == status)
        return list(self.db.scalars(q.order_by(AgentRun.created_at.desc(), AgentRun.id).limit(limit)))

    # ---------------------------------------------------------------- lifecycle (executor-facing)
    def start(self, principal: Principal, run_id: str) -> AgentRun:
        run = self._load_driven(principal, run_id)
        if _aware(run.expires_at) is not None and _aware(run.expires_at) <= self._clock():
            return self._expire_and_raise(run, principal.user_id)
        return self._transition(run, S.RUNNING, principal.user_id, "agent_run.started",
                                only_from=S.QUEUED, started_at=run.started_at or self._clock(),
                                expires_at=self._clock() + timedelta(seconds=self.settings.agent_run_timeout_seconds))

    def wait_for_approval(self, principal: Principal, run_id: str, execution_id: str) -> AgentRun:
        run = self._load_driven(principal, run_id)
        ex = self.db.get(ToolExecution, execution_id)
        if (ex is None or ex.workspace_id != run.workspace_id or ex.agent != run.agent_id
                or ex.requested_by != run.requested_by or ex.status != ExecutionStatus.AWAITING_APPROVAL):
            raise RunStateError("That execution is not awaiting approval for this run")
        return self._transition(run, S.WAITING_APPROVAL, principal.user_id, "agent_run.waiting_approval",
                                execution_id=execution_id, pending_execution_id=execution_id,
                                expires_at=self._clock() + timedelta(
                                    seconds=self.settings.agent_run_approval_wait_seconds))

    def resume(self, principal: Principal, run_id: str) -> AgentRun:
        run = self._load_driven(principal, run_id)
        if run.status == S.WAITING_APPROVAL and _aware(run.expires_at) is not None \
                and _aware(run.expires_at) <= self._clock():
            self._expire_and_raise(run, principal.user_id)        # approved too late: expire (withdraws the approval)
        if run.status == S.WAITING_APPROVAL and run.pending_execution_id:
            ex = self.db.get(ToolExecution, run.pending_execution_id)
            if ex is not None and ex.status == ExecutionStatus.AWAITING_APPROVAL:
                raise RunStateError("The approval has not been decided yet")
        pending = run.pending_execution_id
        return self._transition(run, S.RUNNING, principal.user_id, "agent_run.resumed", execution_id=pending,
                                only_from=S.WAITING_APPROVAL, pending_execution_id=None,
                                expires_at=self._clock() + timedelta(seconds=self.settings.agent_run_timeout_seconds))

    def charge(self, principal: Principal, run_id: str, kind: str) -> AgentRun:
        """Spend one unit of the run's step / tool-call / LLM-call budget (atomic). Call BEFORE the work."""
        if kind not in _CHARGE:
            raise InvalidRunRequestError("Unknown budget kind")
        used_col, max_col, code = _CHARGE[kind]
        run = self._load_driven(principal, run_id)
        self._guard_active(run, principal.user_id)
        used, cap = getattr(AgentRun, used_col), getattr(AgentRun, max_col)
        res = self.db.execute(
            update(AgentRun)
            .where(AgentRun.id == run.id, AgentRun.workspace_id == run.workspace_id,
                   AgentRun.status == S.RUNNING, AgentRun.cancel_requested.is_(False), used < cap)
            .values({used_col: used + 1, "updated_at": self._clock()}))
        if res.rowcount == 1:
            self.db.commit()
            self.db.refresh(run)
            return run
        self.db.rollback()
        fresh = self._load(run.workspace_id, run.id)                 # lost a race, or the budget is spent
        self._guard_active(fresh, principal.user_id)
        self._transition(fresh, S.FAILED, principal.user_id, "agent_run.failed", error_code=code,
                         finished_at=self._clock(), reason="limit")
        raise RunLimitError(f"Run budget exhausted: {kind.replace('_', ' ')}s")

    def checkpoint(self, principal: Principal, run_id: str) -> AgentRun:
        """Cooperative stop point: raises if the run was cancelled, expired or is no longer running."""
        run = self._load_driven(principal, run_id)
        self._guard_active(run, principal.user_id)
        return run

    def succeed(self, principal: Principal, run_id: str, result: Optional[Dict[str, Any]] = None) -> AgentRun:
        run = self._load_driven(principal, run_id)
        safe = self._bounded_result(result)
        return self._transition(run, S.SUCCEEDED, principal.user_id, "agent_run.succeeded", result=safe,
                                finished_at=self._clock(), has_result=safe is not None)

    def fail(self, principal: Principal, run_id: str, code: str) -> AgentRun:
        if not isinstance(code, str) or not _CODE_RE.match(code):
            raise InvalidRunRequestError("error code must be a short slug (a-z, 0-9, _ or .)")
        run = self._load_driven(principal, run_id)
        return self._transition(run, S.FAILED, principal.user_id, "agent_run.failed", error_code=code,
                                finished_at=self._clock())

    # ---------------------------------------------------------------- cancel / expiry
    def cancel(self, principal: Principal, run_id: str) -> AgentRun:
        run = self.get(principal, run_id)
        if principal.agent is not None:
            raise RunForbiddenError("Agents cannot cancel runs")
        if run.status == S.CANCELLED:
            return run                                               # idempotent
        if run.status == S.RUNNING:
            res = self.db.execute(update(AgentRun).where(
                AgentRun.id == run.id, AgentRun.workspace_id == run.workspace_id, AgentRun.status == S.RUNNING)
                .values(cancel_requested=True, updated_at=self._clock()))
            if res.rowcount == 1:
                self._event(run, "agent_run.cancel_requested", principal.user_id)
                self.db.commit()
                self.db.refresh(run)
                return run
            self.db.rollback()
            run = self._load(run.workspace_id, run.id)               # state moved under us: fall through
            if run.status == S.CANCELLED:
                return run
        return self._transition(run, S.CANCELLED, principal.user_id, "agent_run.cancelled",
                                finished_at=self._clock(), cancel_requested=True)

    def expire_overdue(self, workspace_id: Optional[str] = None) -> int:
        """Expires every non-terminal run past its deadline. Safe to call repeatedly (a scheduler hook later)."""
        now = self._clock()
        q = select(AgentRun).where(AgentRun.status.in_([s for s in S if s not in TERMINAL]))
        if workspace_id is not None:
            q = q.where(AgentRun.workspace_id == workspace_id)
        count = 0
        for run in list(self.db.scalars(q)):
            if _aware(run.expires_at) is not None and _aware(run.expires_at) <= now:
                try:
                    self._transition(run, S.EXPIRED, "system", "agent_run.expired", finished_at=now)
                    count += 1
                except RunStateError:
                    pass                                             # someone else finished it first
        return count

    # ---------------------------------------------------------------- internals
    def _limit(self, name: str, requested: Optional[int], ceiling: int, floor: int) -> int:
        if requested is None:
            return ceiling
        if isinstance(requested, bool) or not isinstance(requested, int) or requested < floor:
            raise InvalidRunRequestError(f"{name} must be an integer >= {floor}")
        return min(requested, ceiling)                               # ask for less, never more

    def _by_idempotency(self, workspace_id: str, key: str) -> Optional[AgentRun]:
        return self.db.scalar(select(AgentRun).where(AgentRun.workspace_id == workspace_id,
                                                     AgentRun.idempotency_key == key))

    def _replay(self, existing: AgentRun, principal: Principal, agent_id: str, digest: str) -> AgentRun:
        if (existing.requested_by != principal.user_id or existing.agent_id != agent_id
                or existing.goal_digest != digest):
            raise RunConflictError("idempotency_key was already used for a different request")
        return existing

    def _load(self, workspace_id: str, run_id: str) -> AgentRun:
        run = self.db.scalar(select(AgentRun).where(AgentRun.id == run_id, AgentRun.workspace_id == workspace_id))
        if run is None:
            raise RunNotFoundError("Run not found")
        self.db.refresh(run)
        return run

    def _can_see(self, principal: Principal, run: AgentRun) -> bool:
        if run.workspace_id != principal.workspace_id:
            return False
        if principal.agent is not None:
            return run.requested_by == principal.user_id and run.agent_id == principal.agent
        return run.requested_by == principal.user_id or principal.can("agent:manage")

    def _load_driven(self, principal: Principal, run_id: str) -> AgentRun:
        """Executor-facing load: the run's own user (or that user's agent for this run), nobody else."""
        run = self._load(principal.workspace_id, run_id)
        if run.requested_by != principal.user_id or (principal.agent is not None and principal.agent != run.agent_id):
            raise RunNotFoundError("Run not found")
        return run

    def _guard_active(self, run: AgentRun, actor: str) -> None:
        if run.status != S.RUNNING:
            raise RunStateError(f"Run is {run.status.value}, not running")
        if run.cancel_requested:
            self._transition(run, S.CANCELLED, actor, "agent_run.cancelled", finished_at=self._clock())
            raise RunCancelledError("Run was cancelled")
        if _aware(run.expires_at) is not None and _aware(run.expires_at) <= self._clock():
            self._expire_and_raise(run, actor)

    def _expire_and_raise(self, run: AgentRun, actor: str):
        self._transition(run, S.EXPIRED, actor, "agent_run.expired", finished_at=self._clock())
        raise RunExpiredError("Run deadline passed")

    def _bounded_result(self, result: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if result is None:
            return None
        if not isinstance(result, dict):
            raise InvalidRunRequestError("result must be an object")
        safe = redact(result)
        try:
            size = len(json.dumps(safe, default=str).encode())
        except (TypeError, ValueError):
            raise InvalidRunRequestError("result must be JSON-serialisable")
        if size > MAX_RESULT_BYTES:
            raise InvalidRunRequestError(f"result is too large (max {MAX_RESULT_BYTES} bytes)")
        return safe

    def _event(self, run: AgentRun, event_type: str, actor: str, *, execution_id: Optional[str] = None,
               **payload: Any) -> None:
        record_event(self.db, workspace_id=run.workspace_id, event_type=event_type, actor=actor,
                     execution_id=execution_id,
                     payload={"run_id": run.id, "agent": run.agent_id, "status": run.status.value, **payload})

    def _transition(self, run: AgentRun, to: S, actor: str, event_type: str, *,
                    execution_id: Optional[str] = None, reason: Optional[str] = None, has_result: Optional[bool] = None,
                    only_from: Optional[S] = None, **fields: Any) -> AgentRun:
        # `only_from` narrows the table for operations with a single legal source (start, resume), because
        # QUEUED and WAITING_APPROVAL both lead to RUNNING and must not be interchangeable.
        sources = [s for s, targets in ALLOWED_TRANSITIONS.items() if to in targets and only_from in (None, s)]
        frm = run.status
        res = self.db.execute(
            update(AgentRun)
            .where(AgentRun.id == run.id, AgentRun.workspace_id == run.workspace_id, AgentRun.status.in_(sources))
            .values(status=to, updated_at=self._clock(), **fields))
        if res.rowcount != 1:
            self.db.rollback()
            fresh = self._load(run.workspace_id, run.id)
            raise RunStateError(f"Run is {fresh.status.value}; cannot move to {to.value}")
        self.db.refresh(run)
        extra: Dict[str, Any] = {"from": frm.value, "to": to.value}
        if run.error_code and to in (S.FAILED,):
            extra["error_code"] = run.error_code
        if reason:
            extra["reason"] = reason
        if has_result is not None:
            extra["has_result"] = has_result
        self._event(run, event_type, actor, execution_id=execution_id, **extra)
        self.db.commit()
        if frm == S.WAITING_APPROVAL and to != S.RUNNING and run.pending_execution_id:
            self._withdraw_pending(run, to)
        return run

    def _withdraw_pending(self, run: AgentRun, to: S) -> None:
        """A run that ends while waiting must not leave a live approval behind: a human could otherwise still
        approve (and the kernel execute) work whose run was cancelled, expired or failed."""
        approval = self.db.scalar(select(Approval).where(
            Approval.execution_id == run.pending_execution_id, Approval.workspace_id == run.workspace_id,
            Approval.status == ApprovalStatus.PENDING))
        if approval is not None:
            ApprovalService(self.db).withdraw(approval.id, run.workspace_id, reason=f"run_{to.value}")
