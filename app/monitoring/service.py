"""Workspace execution monitoring (13.1): what ran, what failed, what is stuck, in a recent window.

Read-only and workspace-scoped (every query filters on workspace_id). Content-free: no tool input or output, no error text beyond the short
type/code the kernel already stores, no user ids. Counts only come from tables the kernel already writes; nothing here changes any state.
"""
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.enums import ApprovalStatus, ExecutionStatus
from app.models.kernel import Approval, SystemEvent, ToolExecution

ALLOWED_WINDOWS = (3600, 86400, 604800)      # an hour, a day, a week
DEFAULT_WINDOW = 86400
SAMPLE_CAP = 5000                            # rows read for durations / denial reasons; the summary says when it was capped
TOP_N, RECENT_N = 5, 10


class NameCount(BaseModel):
    name: str
    count: int


class FailureItem(BaseModel):
    execution_id: str
    tool_id: str
    error: Optional[str] = None
    finished_at: Optional[str] = None


class ExecutionStats(BaseModel):
    total: int
    by_status: Dict[str, int]
    failure_rate: Optional[float] = None      # failed / (succeeded + failed); None when nothing finished
    avg_duration_ms: Optional[int] = None
    max_duration_ms: Optional[int] = None
    p50_duration_ms: Optional[int] = None     # nearest-rank percentiles of the same sample (13.5)
    p95_duration_ms: Optional[int] = None
    duration_sample_capped: bool = False


class ApprovalStats(BaseModel):
    pending: int
    oldest_pending_age_seconds: Optional[int] = None
    rejected_in_window: int
    expired_in_window: int
    decided_in_window: int = 0                # approved or rejected by a human in the window (expired ones are not a decision)
    avg_decision_seconds: Optional[int] = None    # created -> decided
    p95_decision_seconds: Optional[int] = None
    decision_sample_capped: bool = False


class MonitoringSummary(BaseModel):
    window_seconds: int
    generated_at: str
    executions: ExecutionStats
    approvals: ApprovalStats
    denials_in_window: int
    denial_reasons: List[NameCount]
    top_failing_tools: List[NameCount]
    recent_failures: List[FailureItem]
    needs_attention: bool                     # failures in the window, or a pending approval older than 24h


def percentile(values: List[int], q: int) -> Optional[int]:
    """Nearest-rank percentile (integer q in 0..100); None for an empty list. Always one of the observed values."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, -(-(int(q) * len(ordered)) // 100))
    return ordered[min(rank, len(ordered)) - 1]


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


class MonitoringService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def summary(self, workspace_id: str, window_seconds: int = DEFAULT_WINDOW, *, now: Optional[datetime] = None) -> MonitoringSummary:
        if window_seconds not in ALLOWED_WINDOWS:
            raise ValueError("invalid window")
        now = now or datetime.now(timezone.utc)
        since = now - timedelta(seconds=window_seconds)
        ex = self._executions(workspace_id, since)
        appr = self._approvals(workspace_id, since, now)
        denied_rows = list(self.db.scalars(select(SystemEvent.payload).where(
            SystemEvent.workspace_id == workspace_id, SystemEvent.event_type == "execution.denied",
            SystemEvent.created_at >= since).limit(SAMPLE_CAP)))
        denial_total = self.db.scalar(select(func.count()).select_from(SystemEvent).where(
            SystemEvent.workspace_id == workspace_id, SystemEvent.event_type == "execution.denied",
            SystemEvent.created_at >= since)) or 0
        reasons = Counter(str((p or {}).get("reason", "unknown"))[:64] for p in denied_rows)
        failing = list(self.db.execute(select(ToolExecution.tool_id, func.count()).where(
            ToolExecution.workspace_id == workspace_id, ToolExecution.status == ExecutionStatus.FAILED,
            ToolExecution.created_at >= since).group_by(ToolExecution.tool_id).order_by(func.count().desc(), ToolExecution.tool_id).limit(TOP_N)))
        recent = list(self.db.scalars(select(ToolExecution).where(
            ToolExecution.workspace_id == workspace_id, ToolExecution.status == ExecutionStatus.FAILED,
            ToolExecution.created_at >= since).order_by(ToolExecution.created_at.desc(), ToolExecution.id).limit(RECENT_N)))
        failed = ex.by_status.get(ExecutionStatus.FAILED.value, 0)
        stale = appr.oldest_pending_age_seconds is not None and appr.oldest_pending_age_seconds >= 86400
        return MonitoringSummary(
            window_seconds=window_seconds, generated_at=now.isoformat(), executions=ex, approvals=appr,
            denials_in_window=denial_total, denial_reasons=[NameCount(name=k, count=v) for k, v in reasons.most_common(TOP_N)],
            top_failing_tools=[NameCount(name=t, count=c) for t, c in failing],
            recent_failures=[FailureItem(execution_id=r.id, tool_id=r.tool_id, error=(r.error or None) and r.error[:120],
                                         finished_at=r.finished_at.isoformat() if r.finished_at else None) for r in recent],
            needs_attention=failed > 0 or stale)

    def _executions(self, ws: str, since: datetime) -> ExecutionStats:
        counts = dict(self.db.execute(select(ToolExecution.status, func.count()).where(
            ToolExecution.workspace_id == ws, ToolExecution.created_at >= since).group_by(ToolExecution.status)).all())
        by_status = {(k.value if hasattr(k, "value") else str(k)): int(v) for k, v in counts.items()}
        done = by_status.get("succeeded", 0) + by_status.get("failed", 0)
        spans = list(self.db.execute(select(ToolExecution.started_at, ToolExecution.finished_at).where(
            ToolExecution.workspace_id == ws, ToolExecution.created_at >= since, ToolExecution.started_at.is_not(None),
            ToolExecution.finished_at.is_not(None)).limit(SAMPLE_CAP + 1)).all())
        capped = len(spans) > SAMPLE_CAP
        ms = [max(0, int((_aware(b) - _aware(a)).total_seconds() * 1000)) for a, b in spans[:SAMPLE_CAP]]
        return ExecutionStats(total=sum(by_status.values()), by_status=dict(sorted(by_status.items())),
                              failure_rate=round(by_status.get("failed", 0) / done, 4) if done else None,
                              avg_duration_ms=int(sum(ms) / len(ms)) if ms else None, max_duration_ms=max(ms) if ms else None,
                              p50_duration_ms=percentile(ms, 50), p95_duration_ms=percentile(ms, 95), duration_sample_capped=capped)

    def _approvals(self, ws: str, since: datetime, now: datetime) -> ApprovalStats:
        pending = list(self.db.scalars(select(Approval.created_at).where(
            Approval.workspace_id == ws, Approval.status == ApprovalStatus.PENDING)))
        oldest = min((_aware(c) for c in pending), default=None)
        window = lambda st: self.db.scalar(select(func.count()).select_from(Approval).where(      # noqa: E731
            Approval.workspace_id == ws, Approval.status == st, Approval.decided_at.is_not(None), Approval.decided_at >= since)) or 0
        decided = list(self.db.execute(select(Approval.created_at, Approval.decided_at).where(
            Approval.workspace_id == ws, Approval.status.in_([ApprovalStatus.APPROVED, ApprovalStatus.EXECUTED, ApprovalStatus.REJECTED]),
            Approval.decided_at.is_not(None), Approval.decided_at >= since).limit(SAMPLE_CAP + 1)).all())
        capped = len(decided) > SAMPLE_CAP
        secs = [max(0, int((_aware(b) - _aware(a)).total_seconds())) for a, b in decided[:SAMPLE_CAP]]
        return ApprovalStats(pending=len(pending), oldest_pending_age_seconds=int((now - oldest).total_seconds()) if oldest else None,
                             rejected_in_window=window(ApprovalStatus.REJECTED), expired_in_window=window(ApprovalStatus.EXPIRED),
                             decided_in_window=len(secs), avg_decision_seconds=int(sum(secs) / len(secs)) if secs else None,
                             p95_decision_seconds=percentile(secs, 95), decision_sample_capped=capped)
