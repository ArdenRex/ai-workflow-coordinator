"""Connection and background-work health (13.2): which connections are failing, which agent/workflow runs failed or are overdue.

Read-only, workspace-scoped, content-free, like the 13.1 summary. Connections use the last connection test already stored on the credential
(the safe code, never the secret or the config). Runs use their lifecycle rows only: no goals, results or step output. It never tests a
connection, retries or cancels anything, so it cannot cause an external call.
"""
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.agents import AgentRun
from app.models.credentials import Credential
from app.models.enums import AgentRunStatus, StepState, WorkflowRunStatus
from app.models.workflows import WorkflowEventRecord, WorkflowRunRecord, WorkflowScheduleRecord, WorkflowStepRecord
from app.monitoring.service import ALLOWED_WINDOWS, DEFAULT_WINDOW, NameCount, RECENT_N, TOP_N

STALE_TEST_AFTER = timedelta(days=7)         # a passing test older than this is reported as "stale"
MAX_CONNECTIONS = 50
GRACE = timedelta(minutes=5)                  # a schedule or event this far past due is 'overdue' / 'stuck' (the scheduler may just be between ticks)
MAX_SCHEDULES = 10
ACTIVE_AGENT = (AgentRunStatus.QUEUED, AgentRunStatus.RUNNING, AgentRunStatus.WAITING_APPROVAL)
ACTIVE_WORKFLOW = (WorkflowRunStatus.PENDING, WorkflowRunStatus.RUNNING)


class ConnectionHealth(BaseModel):
    credential_id: str
    provider: str
    name: str
    state: str                                # ok | failing | untested | stale
    last_tested_at: Optional[str] = None
    last_test_message: Optional[str] = None   # the stored safe code only


class ConnectionsReport(BaseModel):
    total_active: int
    by_state: Dict[str, int]
    connections: List[ConnectionHealth]       # failing and stale first, at most 50


class AgentRunHealth(BaseModel):
    by_status: Dict[str, int]
    failure_codes: List[NameCount]
    overdue_active: int                       # queued/running/waiting runs whose own deadline has passed (nothing has expired them yet)


class FailedWorkflowRun(BaseModel):
    run_id: str
    workflow_key: str
    error_code: Optional[str] = None
    finished_at: Optional[str] = None


class WorkflowHealth(BaseModel):
    by_status: Dict[str, int]
    failure_codes: List[NameCount]
    overdue_steps: int                        # steps still RUNNING after their attempt deadline
    steps_waiting_retry: int
    recent_failures: List[FailedWorkflowRun]


class OverdueSchedule(BaseModel):
    schedule_id: str
    workflow_key: str
    interval_seconds: int
    next_fire_at: str


class ScheduleHealth(BaseModel):
    total: int
    enabled: int
    disabled: int
    auto_disabled: int                        # disabled by the scheduler with a stored reason (not switched off by a person)
    disabled_reasons: List[NameCount]
    overdue: int                              # enabled, and next_fire_at is more than 5 minutes in the past (snapshot of now)
    overdue_schedules: List[OverdueSchedule]  # the most overdue, at most 10
    skipped_slots_total: int


class EventHealth(BaseModel):
    received_in_window: int
    dispatched_in_window: int
    truncated_in_window: int                  # events that matched more workflows than one dispatch could start
    stuck_undispatched: int                   # not dispatched more than 5 minutes after arrival (snapshot of now)


class HealthReport(BaseModel):
    window_seconds: int
    generated_at: str
    connections: ConnectionsReport
    agent_runs: AgentRunHealth
    workflow_runs: WorkflowHealth
    schedules: ScheduleHealth
    events: EventHealth
    needs_attention: bool


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


def _value(k) -> str:
    return k.value if hasattr(k, "value") else str(k)


class HealthService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def report(self, workspace_id: str, window_seconds: int = DEFAULT_WINDOW, *, now: Optional[datetime] = None) -> HealthReport:
        if window_seconds not in ALLOWED_WINDOWS:
            raise ValueError("invalid window")
        now = now or datetime.now(timezone.utc)
        since = now - timedelta(seconds=window_seconds)
        conns, agents, flows = self._connections(workspace_id, now), self._agents(workspace_id, since, now), self._workflows(workspace_id, since, now)
        scheds, evs = self._schedules(workspace_id, now), self._events(workspace_id, since, now)
        attention = (conns.by_state.get("failing", 0) > 0 or agents.overdue_active > 0 or agents.by_status.get("failed", 0) > 0
                     or flows.overdue_steps > 0 or flows.by_status.get("failed", 0) > 0
                     or scheds.overdue > 0 or scheds.auto_disabled > 0 or evs.stuck_undispatched > 0)
        return HealthReport(window_seconds=window_seconds, generated_at=now.isoformat(), connections=conns, agent_runs=agents,
                            workflow_runs=flows, schedules=scheds, events=evs, needs_attention=attention)

    # ------------------------------------------------------------------ connections
    def _connections(self, ws: str, now: datetime) -> ConnectionsReport:
        rows = list(self.db.scalars(select(Credential).where(Credential.workspace_id == ws, Credential.is_active.is_(True))
                                    .order_by(Credential.provider, Credential.name)))
        out: List[ConnectionHealth] = []
        for c in rows:
            tested = _aware(c.last_tested_at)
            if c.last_test_ok is None or tested is None:
                state = "untested"
            elif not c.last_test_ok:
                state = "failing"
            elif now - tested > STALE_TEST_AFTER:
                state = "stale"
            else:
                state = "ok"
            out.append(ConnectionHealth(credential_id=c.id, provider=c.provider, name=c.name, state=state,
                                        last_tested_at=tested.isoformat() if tested else None,
                                        last_test_message=(c.last_test_message or None) and c.last_test_message[:64]))
        order = {"failing": 0, "stale": 1, "untested": 2, "ok": 3}
        out.sort(key=lambda x: (order[x.state], x.provider, x.name))
        return ConnectionsReport(total_active=len(out), by_state=dict(sorted(Counter(x.state for x in out).items())), connections=out[:MAX_CONNECTIONS])

    # ------------------------------------------------------------------ agent runs
    def _agents(self, ws: str, since: datetime, now: datetime) -> AgentRunHealth:
        by = {_value(k): int(v) for k, v in self.db.execute(select(AgentRun.status, func.count()).where(
            AgentRun.workspace_id == ws, AgentRun.created_at >= since).group_by(AgentRun.status)).all()}
        codes = list(self.db.execute(select(AgentRun.error_code, func.count()).where(
            AgentRun.workspace_id == ws, AgentRun.created_at >= since, AgentRun.status == AgentRunStatus.FAILED,
            AgentRun.error_code.is_not(None)).group_by(AgentRun.error_code).order_by(func.count().desc(), AgentRun.error_code).limit(TOP_N)))
        overdue = self.db.scalar(select(func.count()).select_from(AgentRun).where(
            AgentRun.workspace_id == ws, AgentRun.status.in_(ACTIVE_AGENT), AgentRun.expires_at.is_not(None), AgentRun.expires_at < now)) or 0
        return AgentRunHealth(by_status=dict(sorted(by.items())), failure_codes=[NameCount(name=str(c), count=n) for c, n in codes], overdue_active=overdue)

    # ------------------------------------------------------------------ workflow runs
    def _workflows(self, ws: str, since: datetime, now: datetime) -> WorkflowHealth:
        by = {_value(k): int(v) for k, v in self.db.execute(select(WorkflowRunRecord.status, func.count()).where(
            WorkflowRunRecord.workspace_id == ws, WorkflowRunRecord.created_at >= since).group_by(WorkflowRunRecord.status)).all()}
        codes = list(self.db.execute(select(WorkflowRunRecord.error_code, func.count()).where(
            WorkflowRunRecord.workspace_id == ws, WorkflowRunRecord.created_at >= since, WorkflowRunRecord.status == WorkflowRunStatus.FAILED,
            WorkflowRunRecord.error_code.is_not(None)).group_by(WorkflowRunRecord.error_code)
            .order_by(func.count().desc(), WorkflowRunRecord.error_code).limit(TOP_N)))
        overdue = self.db.scalar(select(func.count()).select_from(WorkflowStepRecord).where(
            WorkflowStepRecord.workspace_id == ws, WorkflowStepRecord.status == StepState.RUNNING,
            WorkflowStepRecord.deadline_at.is_not(None), WorkflowStepRecord.deadline_at < now)) or 0
        waiting = self.db.scalar(select(func.count()).select_from(WorkflowStepRecord).where(
            WorkflowStepRecord.workspace_id == ws, WorkflowStepRecord.status == StepState.PENDING,
            WorkflowStepRecord.next_attempt_at.is_not(None))) or 0
        recent = list(self.db.scalars(select(WorkflowRunRecord).where(
            WorkflowRunRecord.workspace_id == ws, WorkflowRunRecord.created_at >= since, WorkflowRunRecord.status == WorkflowRunStatus.FAILED)
            .order_by(WorkflowRunRecord.created_at.desc(), WorkflowRunRecord.id).limit(RECENT_N)))
        return WorkflowHealth(by_status=dict(sorted(by.items())), failure_codes=[NameCount(name=str(c), count=n) for c, n in codes],
                              overdue_steps=overdue, steps_waiting_retry=waiting,
                              recent_failures=[FailedWorkflowRun(run_id=r.id, workflow_key=r.workflow_key, error_code=r.error_code,
                                                                 finished_at=r.finished_at.isoformat() if r.finished_at else None) for r in recent])

    # ------------------------------------------------------------------ schedules and events (13.6)
    def _schedules(self, ws: str, now: datetime) -> ScheduleHealth:
        R = WorkflowScheduleRecord
        rows = list(self.db.execute(select(R.enabled, R.disabled_reason, R.skipped_count).where(R.workspace_id == ws)).all())
        reasons = Counter(str(r)[:32] for e, r, _ in rows if not e and r)
        late = list(self.db.scalars(select(R).where(R.workspace_id == ws, R.enabled.is_(True), R.next_fire_at < now - GRACE)
                                    .order_by(R.next_fire_at, R.id)))
        return ScheduleHealth(
            total=len(rows), enabled=sum(1 for e, _, _ in rows if e), disabled=sum(1 for e, _, _ in rows if not e),
            auto_disabled=sum(reasons.values()), disabled_reasons=[NameCount(name=k, count=v) for k, v in reasons.most_common(TOP_N)],
            overdue=len(late),
            overdue_schedules=[OverdueSchedule(schedule_id=r.id, workflow_key=r.workflow_key, interval_seconds=r.interval_seconds,
                                               next_fire_at=_aware(r.next_fire_at).isoformat()) for r in late[:MAX_SCHEDULES]],
            skipped_slots_total=sum(int(n or 0) for _, _, n in rows))

    def _events(self, ws: str, since: datetime, now: datetime) -> EventHealth:
        E = WorkflowEventRecord
        count = lambda *c: self.db.scalar(select(func.count()).select_from(E).where(E.workspace_id == ws, *c)) or 0   # noqa: E731
        return EventHealth(
            received_in_window=count(E.created_at >= since),
            dispatched_in_window=count(E.created_at >= since, E.dispatched_at.is_not(None)),
            truncated_in_window=count(E.created_at >= since, E.truncated.is_(True)),
            stuck_undispatched=count(E.dispatched_at.is_(None), E.created_at < now - GRACE))
