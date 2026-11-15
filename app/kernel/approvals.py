"""Approval workflow: PENDING -> APPROVED | REJECTED | EXPIRED; APPROVED -> EXECUTED.

Guarantees: workspace-scoped lookups, no self-approval by default, agents can
never decide approvals, terminal states are immutable, decisions are atomic
(conditional UPDATE) so concurrent double-decisions cannot both win, and every
transition is audited in the same transaction.
"""
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.kernel.audit import input_digest, record_event
from app.kernel.errors import (ApprovalExpiredError, ApprovalNotFoundError,
                               ApprovalPermissionError, ApprovalStateError)
from app.kernel.permissions import Principal
from app.kernel.policy import WorkspacePolicy, extra_decider_permission
from app.models.enums import ApprovalStatus, ExecutionStatus
from app.models.kernel import Approval, ToolExecution

DECIDE_PERMISSION = "approval:decide"
DEFAULT_TTL = timedelta(hours=24)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    # SQLite returns naive datetimes; treat them as UTC.
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


class ApprovalService:
    def __init__(self, db: Session, *, allow_self_approval: bool = False, ttl: timedelta = DEFAULT_TTL,
                 policy_provider: Optional[Callable[[str], WorkspacePolicy]] = None):
        self.db = db
        self.policy_provider = policy_provider      # approval routing (12.3e); without one, deciding behaves as before
        self.allow_self_approval = allow_self_approval
        self.ttl = ttl

    # -- create ------------------------------------------------------------
    def request(self, execution: ToolExecution, *, now: Optional[datetime] = None) -> Approval:
        now = now or _now()
        if execution.status not in (ExecutionStatus.PENDING, ExecutionStatus.AWAITING_APPROVAL):
            raise ApprovalStateError("Execution is not awaiting evaluation")
        approval = Approval(workspace_id=execution.workspace_id, execution_id=execution.id,
                            requested_by=execution.requested_by, status=ApprovalStatus.PENDING,
                            expires_at=now + self.ttl)
        execution.status = ExecutionStatus.AWAITING_APPROVAL
        self.db.add(approval)
        self.db.flush()
        record_event(self.db, workspace_id=execution.workspace_id, event_type="approval.requested",
                     actor=execution.requested_by, execution_id=execution.id,
                     payload={"approval_id": approval.id, "tool_id": execution.tool_id,
                              "risk": execution.risk_level.value,
                              "input_sha256": input_digest(execution.input)})
        self.db.commit()
        return approval

    # -- lookup (always workspace-scoped) -----------------------------------
    def get(self, approval_id: str, workspace_id: str) -> Approval:
        row = self.db.scalar(select(Approval).where(Approval.id == approval_id,
                                                    Approval.workspace_id == workspace_id))
        if row is None:  # same error for "missing" and "other workspace": no existence leak
            raise ApprovalNotFoundError("Approval not found")
        return row

    # -- decide -------------------------------------------------------------
    def decide(self, approval_id: str, decider: Principal, *, approve: bool,
               reason: Optional[str] = None, now: Optional[datetime] = None) -> Approval:
        now = now or _now()
        approval = self.get(approval_id, decider.workspace_id)

        if decider.agent is not None:
            raise ApprovalPermissionError("Agents cannot decide approvals")
        if not decider.can(DECIDE_PERMISSION):
            raise ApprovalPermissionError("Missing permission to decide approvals")
        if not self.allow_self_approval and decider.user_id == approval.requested_by:
            raise ApprovalPermissionError("Requesters cannot decide their own approvals")
        if self.policy_provider is not None:       # routing (12.3e): may only ADD a requirement; a provider error propagates (fails closed)
            execution = self.db.get(ToolExecution, approval.execution_id)
            needed = extra_decider_permission(execution.risk_level, self.policy_provider(decider.workspace_id))
            if needed is not None and not decider.can(needed):
                record_event(self.db, workspace_id=approval.workspace_id, event_type="approval.decision_refused", actor=decider.user_id,
                             execution_id=approval.execution_id, payload={"approval_id": approval.id, "reason": "approval_routing"})
                self.db.commit()
                raise ApprovalPermissionError("This approval must be decided by the workspace owner")
        if approval.status != ApprovalStatus.PENDING:
            raise ApprovalStateError(f"Approval already {approval.status.value}")

        if approval.expires_at and _aware(approval.expires_at) <= now:
            self._expire(approval, now)
            self.db.commit()
            raise ApprovalExpiredError("Approval has expired")

        new_status = ApprovalStatus.APPROVED if approve else ApprovalStatus.REJECTED
        res = self.db.execute(
            update(Approval)
            .where(Approval.id == approval.id, Approval.workspace_id == approval.workspace_id,
                   Approval.status == ApprovalStatus.PENDING)
            .values(status=new_status, decided_by=decider.user_id, decided_at=now, reason=reason))
        if res.rowcount != 1:  # lost a race with another decision
            self.db.rollback()
            raise ApprovalStateError("Approval was already decided")

        execution = self.db.get(ToolExecution, approval.execution_id)
        execution.status = ExecutionStatus.APPROVED if approve else ExecutionStatus.REJECTED
        record_event(self.db, workspace_id=approval.workspace_id,
                     event_type="approval.approved" if approve else "approval.rejected",
                     actor=decider.user_id, execution_id=approval.execution_id,
                     payload={"approval_id": approval.id, "reason": reason})
        self.db.commit()
        self.db.refresh(approval)
        return approval

    # -- withdraw (system-initiated, e.g. the agent run that asked has ended) -----
    def withdraw(self, approval_id: str, workspace_id: str, *, reason: str, now: Optional[datetime] = None) -> bool:
        """Rejects a still-PENDING approval on behalf of the system. Never approves anything and never touches a
        decided approval: returns False if it was no longer pending. `reason` is a short machine slug."""
        now = now or _now()
        res = self.db.execute(
            update(Approval)
            .where(Approval.id == approval_id, Approval.workspace_id == workspace_id,
                   Approval.status == ApprovalStatus.PENDING)
            .values(status=ApprovalStatus.REJECTED, decided_by="system", decided_at=now, reason=reason[:64]))
        if res.rowcount != 1:
            self.db.rollback()
            return False
        approval = self.get(approval_id, workspace_id)
        execution = self.db.get(ToolExecution, approval.execution_id)
        if execution is not None and execution.status == ExecutionStatus.AWAITING_APPROVAL:
            execution.status = ExecutionStatus.REJECTED
        record_event(self.db, workspace_id=workspace_id, event_type="approval.withdrawn", actor="system",
                     execution_id=approval.execution_id, payload={"approval_id": approval_id, "reason": reason[:64]})
        self.db.commit()
        return True

    # -- executed (called by the kernel after a successful run) --------------
    def mark_executed(self, approval: Approval) -> Approval:
        if approval.status != ApprovalStatus.APPROVED:
            raise ApprovalStateError("Only approved approvals can be executed")
        approval.status = ApprovalStatus.EXECUTED
        record_event(self.db, workspace_id=approval.workspace_id, event_type="approval.executed",
                     execution_id=approval.execution_id, payload={"approval_id": approval.id})
        self.db.commit()
        return approval

    # -- expiry ---------------------------------------------------------------
    def expire_stale(self, workspace_id: str, *, now: Optional[datetime] = None) -> int:
        now = now or _now()
        pending = self.db.scalars(select(Approval).where(
            Approval.workspace_id == workspace_id, Approval.status == ApprovalStatus.PENDING)).all()
        n = 0
        for a in pending:
            if a.expires_at and _aware(a.expires_at) <= now:
                self._expire(a, now)
                n += 1
        self.db.commit()
        return n

    def _expire(self, approval: Approval, now: datetime) -> None:
        approval.status = ApprovalStatus.EXPIRED
        approval.decided_at = now
        execution = self.db.get(ToolExecution, approval.execution_id)
        if execution is not None:
            execution.status = ExecutionStatus.EXPIRED
        record_event(self.db, workspace_id=approval.workspace_id, event_type="approval.expired",
                     execution_id=approval.execution_id, payload={"approval_id": approval.id})
