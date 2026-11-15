"""Alert rules (13.7): which known problems are firing right now. Read-only, workspace-scoped, content-free.

A fixed set of rules is evaluated against the 13.1 summary and the 13.2/13.6 health report of ONE workspace. Nothing is stored, sent or
changed: this reports what is firing and nothing else (no notifications, no acknowledgement, no per-workspace thresholds yet).
Alert text is fixed per rule; only a number (count, rate or value) varies. No tool names, ids, errors or payloads appear.
"""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.monitoring.health import HealthReport, HealthService
from app.monitoring.service import ALLOWED_WINDOWS, DEFAULT_WINDOW, MonitoringService, MonitoringSummary

SEVERITY_ORDER = {"critical": 0, "warning": 1}
MIN_FINISHED_FOR_RATE = 4                    # a failure rate over fewer finished runs is noise
FAILURE_RATE_WARN, FAILURE_RATE_CRIT = 0.25, 0.5
APPROVAL_STALE_WARN, APPROVAL_STALE_CRIT = 86400, 3 * 86400       # seconds the oldest pending approval has waited
DENIALS_WARN = 20
P95_SLOW_MS = 30000


class Alert(BaseModel):
    rule: str
    severity: str                             # critical | warning
    value: float                              # the measured number
    threshold: float
    message: str                              # fixed text per rule


class AlertReport(BaseModel):
    window_seconds: int
    generated_at: str
    rules_evaluated: int
    firing_count: int
    highest_severity: Optional[str] = None    # None when nothing is firing
    alerts: List[Alert]                       # critical first, then by rule name


def _rules(s: MonitoringSummary, h: HealthReport) -> List[Alert]:
    out: List[Alert] = []

    def fire(rule: str, severity: str, value: float, threshold: float, message: str) -> None:
        out.append(Alert(rule=rule, severity=severity, value=value, threshold=threshold, message=message))

    bs = s.executions.by_status
    finished = bs.get("succeeded", 0) + bs.get("failed", 0)
    rate = s.executions.failure_rate
    if rate is not None and finished >= MIN_FINISHED_FOR_RATE and rate >= FAILURE_RATE_WARN:
        crit = rate >= FAILURE_RATE_CRIT
        fire("execution_failure_rate", "critical" if crit else "warning", rate, FAILURE_RATE_CRIT if crit else FAILURE_RATE_WARN,
             "A high share of tool executions are failing")
    age = s.approvals.oldest_pending_age_seconds
    if age is not None and age >= APPROVAL_STALE_WARN:
        crit = age >= APPROVAL_STALE_CRIT
        fire("approval_waiting_too_long", "critical" if crit else "warning", age, APPROVAL_STALE_CRIT if crit else APPROVAL_STALE_WARN,
             "An approval has been waiting for a decision for a long time")
    if s.denials_in_window >= DENIALS_WARN:
        fire("many_denials", "warning", s.denials_in_window, DENIALS_WARN, "Many execution attempts were denied")
    p95 = s.executions.p95_duration_ms
    if p95 is not None and p95 >= P95_SLOW_MS:
        fire("slow_executions", "warning", p95, P95_SLOW_MS, "Slow tail latency on tool executions")
    failing = h.connections.by_state.get("failing", 0)
    if failing:
        fire("connection_failing", "critical", failing, 1, "A connection's last test failed")
    if h.agent_runs.overdue_active:
        fire("agent_runs_overdue", "warning", h.agent_runs.overdue_active, 1, "Agent runs are past their deadline and not finished")
    if h.agent_runs.by_status.get("failed", 0):
        fire("agent_runs_failed", "warning", h.agent_runs.by_status["failed"], 1, "Agent runs failed in the window")
    if h.workflow_runs.overdue_steps:
        fire("workflow_steps_overdue", "warning", h.workflow_runs.overdue_steps, 1, "Workflow steps are past their deadline")
    if h.workflow_runs.by_status.get("failed", 0):
        fire("workflow_runs_failed", "warning", h.workflow_runs.by_status["failed"], 1, "Workflow runs failed in the window")
    if h.schedules.overdue:
        fire("schedules_overdue", "warning", h.schedules.overdue, 1, "Schedules have not fired when due")
    if h.schedules.auto_disabled:
        fire("schedules_auto_disabled", "warning", h.schedules.auto_disabled, 1, "Schedules were switched off by the system")
    if h.events.stuck_undispatched:
        fire("events_stuck", "warning", h.events.stuck_undispatched, 1, "Events were received but not dispatched")
    return out


RULES_EVALUATED = 12                         # the number of distinct rules above (a test keeps this honest)


def evaluate(summary: MonitoringSummary, health: HealthReport, now: Optional[datetime] = None) -> AlertReport:
    alerts = sorted(_rules(summary, health), key=lambda a: (SEVERITY_ORDER[a.severity], a.rule))
    return AlertReport(window_seconds=summary.window_seconds, generated_at=health.generated_at, rules_evaluated=RULES_EVALUATED,
                       firing_count=len(alerts), highest_severity=alerts[0].severity if alerts else None, alerts=alerts)


class AlertService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def report(self, workspace_id: str, window_seconds: int = DEFAULT_WINDOW) -> AlertReport:
        if window_seconds not in ALLOWED_WINDOWS:
            raise ValueError("invalid window")
        return evaluate(MonitoringService(self.db).summary(workspace_id, window_seconds),
                        HealthService(self.db).report(workspace_id, window_seconds))
