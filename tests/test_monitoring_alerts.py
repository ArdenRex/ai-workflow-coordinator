"""Step 13.7: alert rules. Read-only, workspace-scoped, content-free, fixed text."""
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.kernel.service import _now
from app.models.credentials import Credential
from app.models.enums import AgentRunStatus, ApprovalStatus, ExecutionStatus
from app.models.kernel import Approval, SystemEvent, ToolExecution
from app.monitoring import alerts as A
from app.monitoring.alerts import AlertService, evaluate
from app.monitoring.health import HealthService
from app.monitoring.service import MonitoringService
from tests.test_monitoring import add
from tests.test_monitoring_health import agent
from tests.test_monitoring_latency import _approval
from tests.test_monitoring_schedules_events import event, sched
from tests.test_workspace_connectors import SECRET, add_cred, mkws, team  # noqa: F401


def u(ws, window=None):
    return f"/workspaces/{ws['id']}/monitoring/alerts" + (f"?window_seconds={window}" if window is not None else "")


def get(client, h, ws, window=None):
    r = client.get(u(ws, window), headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def rules(j):
    return {a["rule"]: a for a in j["alerts"]}


def test_permissions_and_window(client, team):
    hs, ws = team
    assert client.get(u(ws), headers=hs["member"]).status_code == 403
    assert client.get(u(ws), headers=hs["outsider"]).status_code in (403, 404)
    assert client.get(u(ws)).status_code == 401
    for w in (0, 61, 999999):
        r = client.get(u(ws, w), headers=hs["admin"])
        assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_window"
    assert get(client, hs["owner"], ws)["window_seconds"] == 86400


def test_a_quiet_workspace_fires_nothing(client, team):
    hs, ws = team
    j = get(client, hs["admin"], ws)
    assert j["firing_count"] == 0 and j["alerts"] == [] and j["highest_severity"] is None and j["rules_evaluated"] == A.RULES_EVALUATED


def test_failure_rate_needs_enough_runs_then_warns_then_goes_critical(client, team, db_session):
    hs, ws = team
    w = ws["id"]
    for _ in range(3):
        add(db_session, w, ExecutionStatus.FAILED)
    assert "execution_failure_rate" not in rules(get(client, hs["admin"], ws))       # 3 finished runs: too few for a rate
    add(db_session, w, ExecutionStatus.SUCCEEDED)
    add(db_session, w, ExecutionStatus.SUCCEEDED)
    add(db_session, w, ExecutionStatus.SUCCEEDED)
    a = rules(get(client, hs["admin"], ws))["execution_failure_rate"]                # 3 of 6 = 0.5
    assert a["severity"] == "critical" and a["value"] == 0.5
    for _ in range(3):
        add(db_session, w, ExecutionStatus.SUCCEEDED)                                # 3 of 9 = 0.33
    a = rules(get(client, hs["admin"], ws))["execution_failure_rate"]
    assert a["severity"] == "warning" and a["threshold"] == A.FAILURE_RATE_WARN


def test_stale_approvals_connections_and_background_work_fire(client, team, db_session):
    hs, ws = team
    w = ws["id"]
    _approval(db_session, w, ApprovalStatus.PENDING, 4 * 86400, None)
    cid = add_cred(client, hs["owner"], ws, name="bad")
    c = db_session.get(Credential, cid)
    c.last_test_ok, c.last_tested_at, c.last_test_message = False, _now(), "auth_failed"
    db_session.commit()
    agent(db_session, w, AgentRunStatus.RUNNING, expires=_now() - timedelta(hours=1))
    sched(db_session, w, due_in=-9999)
    sched(db_session, w, enabled=False, reason="definition_missing", key="b")
    event(db_session, w, age=3600, dispatched=False)
    j = get(client, hs["admin"], ws)
    r = rules(j)
    assert r["approval_waiting_too_long"]["severity"] == "critical" and r["connection_failing"]["severity"] == "critical"
    for name in ("agent_runs_overdue", "schedules_overdue", "schedules_auto_disabled", "events_stuck"):
        assert r[name]["severity"] == "warning" and r[name]["value"] == 1
    assert j["highest_severity"] == "critical" and [a["severity"] for a in j["alerts"]] == sorted((a["severity"] for a in j["alerts"]))
    assert j["firing_count"] == len(j["alerts"])


def test_denials_and_slow_tail_fire_at_their_thresholds(client, team, db_session):
    hs, ws = team
    w = ws["id"]
    add(db_session, w, ExecutionStatus.SUCCEEDED, ms=A.P95_SLOW_MS - 1)
    for _ in range(A.DENIALS_WARN - 1):
        db_session.add(SystemEvent(workspace_id=w, event_type="execution.denied", actor="u", payload={"reason": "x"}))
    db_session.commit()
    assert not {"many_denials", "slow_executions"} & set(rules(get(client, hs["admin"], ws)))
    add(db_session, w, ExecutionStatus.SUCCEEDED, ms=A.P95_SLOW_MS)
    db_session.add(SystemEvent(workspace_id=w, event_type="execution.denied", actor="u", payload={"reason": "x"}))
    db_session.commit()
    assert {"many_denials", "slow_executions"} <= set(rules(get(client, hs["admin"], ws)))


def test_alerts_are_workspace_scoped_and_content_free(client, team, db_session):
    hs, ws = team
    other = mkws(client, hs["outsider"])
    for _ in range(6):
        add(db_session, other["id"], ExecutionStatus.FAILED, tool="theirs.tool", error="boom SHHH")
    sched(db_session, other["id"], due_in=-9999, key="theirs")
    j = get(client, hs["admin"], ws)
    assert j["firing_count"] == 0
    assert get(client, hs["outsider"], other)["firing_count"] >= 1
    text = client.get(u(other), headers=hs["outsider"]).text
    assert "theirs" not in text and "SHHH" not in text and "boom" not in text and SECRET not in text


def test_reading_changes_nothing_and_only_get_exists(client, team, db_session):
    hs, ws = team
    add(db_session, ws["id"], ExecutionStatus.FAILED)
    n = lambda m: db_session.scalar(select(func.count()).select_from(m))   # noqa: E731
    before = (n(ToolExecution), n(SystemEvent), n(Approval))
    get(client, hs["admin"], ws)
    assert (n(ToolExecution), n(SystemEvent), n(Approval)) == before
    assert client.post(u(ws), headers=hs["admin"]).status_code == 405 and client.put(u(ws), headers=hs["admin"], json={}).status_code == 405


def test_rule_count_is_honest_and_service_rejects_unknown_window(db_session, client, team):
    hs, ws = team
    s = MonitoringService(db_session).summary(ws["id"])
    h = HealthService(db_session).report(ws["id"])
    # push every rule over its threshold at once; the number of distinct rules that can fire must equal RULES_EVALUATED
    s = s.model_copy(update={
        "executions": s.executions.model_copy(update={"by_status": {"succeeded": 1, "failed": 9}, "failure_rate": 0.9, "p95_duration_ms": 10**6}),
        "approvals": s.approvals.model_copy(update={"oldest_pending_age_seconds": 10**7}), "denials_in_window": 999})
    h = h.model_copy(update={
        "connections": h.connections.model_copy(update={"by_state": {"failing": 2}}),
        "agent_runs": h.agent_runs.model_copy(update={"overdue_active": 1, "by_status": {"failed": 1}}),
        "workflow_runs": h.workflow_runs.model_copy(update={"overdue_steps": 1, "by_status": {"failed": 1}}),
        "schedules": h.schedules.model_copy(update={"overdue": 1, "auto_disabled": 1}),
        "events": h.events.model_copy(update={"stuck_undispatched": 1})})
    rep = evaluate(s, h)
    assert len({a.rule for a in rep.alerts}) == A.RULES_EVALUATED == len(rep.alerts)
    with pytest.raises(ValueError):
        AlertService(db_session).report(ws["id"], 5)
