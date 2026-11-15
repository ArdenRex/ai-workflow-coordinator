"""Step 13.2: connection, agent-run and workflow-run health. Read-only, workspace-scoped, content-free."""
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.kernel.service import _now
from app.models.agents import AgentRun
from app.models.credentials import Credential
from app.models.identity import User
from app.models.enums import AgentRunStatus, StepState, WorkflowRunStatus
from app.models.workflows import WorkflowRecord, WorkflowRunRecord, WorkflowStepRecord
from app.monitoring.health import HealthService
from tests.test_workspace_connectors import SECRET, add_cred, mkws, team  # noqa: F401


def u(ws, window=None):
    return f"/workspaces/{ws['id']}/monitoring/health" + (f"?window_seconds={window}" if window is not None else "")


def get(client, h, ws, window=None):
    r = client.get(u(ws, window), headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def uid(db):
    return db.scalar(select(User.id).order_by(User.email).limit(1))


def defn(db, ws):
    d = db.scalar(select(WorkflowRecord).where(WorkflowRecord.workspace_id == ws))
    if d is None:
        d = WorkflowRecord(workspace_id=ws, created_by=uid(db), workflow_key="daily", version=1, name="n", definition={}, definition_digest="d")
        db.add(d)
        db.commit()
    return d


def agent(db, ws, status, *, code=None, expires=None, age=0):
    r = AgentRun(workspace_id=ws, agent_id="ops_agent", requested_by=uid(db), goal_digest="d", goal_chars=1, max_steps=1, max_tool_calls=0,
                 max_llm_calls=0, status=status, error_code=code, expires_at=expires, created_at=_now() - timedelta(seconds=age))
    db.add(r)
    db.commit()
    return r


def wf(db, ws, status, *, code=None, age=0):
    r = WorkflowRunRecord(workspace_id=ws, requested_by=uid(db), definition_id=defn(db, ws).id, workflow_key="daily", version=1, definition_digest="d",
                          trigger_type="manual", step_count=1, status=status, error_code=code, created_at=_now() - timedelta(seconds=age),
                          finished_at=_now())
    db.add(r)
    db.commit()
    return r


def step(db, ws, run, status, *, deadline=None, retry=None, key="a"):
    s = WorkflowStepRecord(run_id=run.id, workspace_id=ws, step_key=key, position=0, agent_id="ops_agent", depends_on=[], timeout_seconds=5,
                           status=status, deadline_at=deadline, next_attempt_at=retry)
    db.add(s)
    db.commit()


def test_permissions_and_window(client, team):
    hs, ws = team
    assert client.get(u(ws), headers=hs["member"]).status_code == 403
    assert client.get(u(ws), headers=hs["outsider"]).status_code in (403, 404)
    assert client.get(u(ws)).status_code == 401
    assert get(client, hs["owner"], ws)["window_seconds"] == 86400
    for w in (0, 61, 999999):
        r = client.get(u(ws, w), headers=hs["admin"])
        assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_window"


def test_an_empty_workspace_needs_no_attention(client, team):
    hs, ws = team
    j = get(client, hs["admin"], ws)
    assert j["needs_attention"] is False and j["connections"] == {"total_active": 0, "by_state": {}, "connections": []}
    assert j["agent_runs"] == {"by_status": {}, "failure_codes": [], "overdue_active": 0}
    assert (j["workflow_runs"]["overdue_steps"], j["workflow_runs"]["recent_failures"]) == (0, [])


def test_connection_states_use_the_stored_test_result_and_never_leak_secrets(client, team, db_session):
    hs, ws = team
    ids = {n: add_cred(client, hs["owner"], ws, name=n) for n in ("untested", "good", "bad", "old", "gone")}
    now = _now()
    for n, ok, when, msg in (("good", True, now, "ok"), ("bad", False, now, "auth_failed"), ("old", True, now - timedelta(days=9), "ok")):
        c = db_session.get(Credential, ids[n])
        c.last_test_ok, c.last_tested_at, c.last_test_message = ok, when, msg
    db_session.get(Credential, ids["gone"]).is_active = False
    db_session.commit()
    j = get(client, hs["admin"], ws)
    c = j["connections"]
    assert c["total_active"] == 4 and c["by_state"] == {"failing": 1, "ok": 1, "stale": 1, "untested": 1}
    assert [x["name"] for x in c["connections"]] == ["bad", "old", "untested", "good"]            # worst first; the revoked one is not listed
    assert c["connections"][0]["last_test_message"] == "auth_failed" and j["needs_attention"] is True
    text = client.get(u(ws), headers=hs["admin"]).text
    assert SECRET not in text and "base_url" not in text and "aceden.test" not in text


def test_a_healthy_connection_alone_needs_no_attention(client, team, db_session):
    hs, ws = team
    c = db_session.get(Credential, add_cred(client, hs["owner"], ws))
    c.last_test_ok, c.last_tested_at, c.last_test_message = True, _now(), "ok"
    db_session.commit()
    assert get(client, hs["admin"], ws)["needs_attention"] is False


def test_agent_runs_counts_failure_codes_and_overdue(client, team, db_session):
    hs, ws = team
    w = ws["id"]
    agent(db_session, w, AgentRunStatus.SUCCEEDED)
    agent(db_session, w, AgentRunStatus.FAILED, code="llm_timeout")
    agent(db_session, w, AgentRunStatus.FAILED, code="llm_timeout")
    agent(db_session, w, AgentRunStatus.FAILED, code="budget_exceeded")
    agent(db_session, w, AgentRunStatus.RUNNING, expires=_now() - timedelta(minutes=5))       # overdue
    agent(db_session, w, AgentRunStatus.WAITING_APPROVAL, expires=_now() + timedelta(hours=1))  # fine
    agent(db_session, w, AgentRunStatus.SUCCEEDED, age=7200)                                     # outside a 1h window
    a = get(client, hs["admin"], ws, 3600)["agent_runs"]
    assert a["by_status"] == {"failed": 3, "running": 1, "succeeded": 1, "waiting_approval": 1} and a["overdue_active"] == 1
    assert a["failure_codes"] == [{"name": "llm_timeout", "count": 2}, {"name": "budget_exceeded", "count": 1}]


def test_workflow_runs_overdue_steps_and_retries(client, team, db_session):
    hs, ws = team
    w = ws["id"]
    bad = wf(db_session, w, WorkflowRunStatus.FAILED, code="step_timeout")
    ok = wf(db_session, w, WorkflowRunStatus.SUCCEEDED)
    step(db_session, w, bad, StepState.RUNNING, deadline=_now() - timedelta(minutes=1))
    step(db_session, w, ok, StepState.RUNNING, deadline=_now() + timedelta(minutes=5), key="b")
    step(db_session, w, ok, StepState.PENDING, retry=_now() + timedelta(minutes=2), key="c")
    f = get(client, hs["admin"], ws)["workflow_runs"]
    assert f["by_status"] == {"failed": 1, "succeeded": 1} and f["overdue_steps"] == 1 and f["steps_waiting_retry"] == 1
    assert f["failure_codes"] == [{"name": "step_timeout", "count": 1}]
    assert f["recent_failures"][0]["run_id"] == bad.id and f["recent_failures"][0]["workflow_key"] == "daily"


def test_another_workspaces_health_never_appears(client, team, db_session):
    hs, ws = team
    other = mkws(client, hs["outsider"])
    cid = add_cred(client, hs["outsider"], other, name="theirs")
    db_session.get(Credential, cid).last_test_ok = False
    db_session.get(Credential, cid).last_tested_at = _now()
    agent(db_session, other["id"], AgentRunStatus.FAILED, code="theirs_code")
    wf(db_session, other["id"], WorkflowRunStatus.FAILED, code="theirs_flow")
    db_session.commit()
    j = get(client, hs["admin"], ws)
    assert j["needs_attention"] is False and j["connections"]["total_active"] == 0
    text = client.get(u(ws), headers=hs["admin"]).text
    assert "theirs" not in text
    assert get(client, hs["outsider"], other)["needs_attention"] is True


def test_reading_changes_nothing_and_no_goals_or_results_are_exposed(client, team, db_session):
    hs, ws = team
    r = agent(db_session, ws["id"], AgentRunStatus.FAILED, code="x")
    r.result = {"secret_answer": "SHHH"}
    db_session.commit()
    counts = lambda: [db_session.scalar(select(func.count()).select_from(m)) for m in (AgentRun, WorkflowRunRecord, Credential)]   # noqa: E731
    before = counts()
    assert "SHHH" not in client.get(u(ws), headers=hs["admin"]).text
    assert counts() == before
    assert client.post(u(ws), headers=hs["admin"]).status_code == 405


def test_service_rejects_an_unknown_window(db_session):
    with pytest.raises(ValueError):
        HealthService(db_session).report("w", 7)


def test_overdue_and_retry_snapshots_ignore_other_workspaces(client, team, db_session):
    hs, ws = team
    other = mkws(client, hs["outsider"])
    agent(db_session, other["id"], AgentRunStatus.RUNNING, expires=_now() - timedelta(minutes=5))
    run = wf(db_session, other["id"], WorkflowRunStatus.RUNNING)
    step(db_session, other["id"], run, StepState.RUNNING, deadline=_now() - timedelta(minutes=1))
    step(db_session, other["id"], run, StepState.PENDING, retry=_now() + timedelta(minutes=2), key="b")
    j = get(client, hs["admin"], ws)
    assert j["agent_runs"]["overdue_active"] == 0 and j["workflow_runs"]["overdue_steps"] == 0 and j["workflow_runs"]["steps_waiting_retry"] == 0
    assert j["needs_attention"] is False
    t = get(client, hs["outsider"], other)
    assert t["agent_runs"]["overdue_active"] == 1 and t["workflow_runs"]["overdue_steps"] == 1 and t["workflow_runs"]["steps_waiting_retry"] == 1
