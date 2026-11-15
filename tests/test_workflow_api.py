"""Substep 9.6: the workflow HTTP API and the end-to-end safety suite that closes Step 9."""
import json
from datetime import timedelta

import pytest
from sqlalchemy import func, select, update

from app.kernel.approvals import ApprovalService
from app.models import Approval, SystemEvent, ToolExecution
from app.models.agents import AgentRun
from app.models.workflows import (WorkflowEventRecord, WorkflowRecord, WorkflowRunRecord, WorkflowScheduleRecord,
                                  WorkflowStepRecord)
from tests.test_agent_context import CALLS
from tests.test_agent_runs_api import intent_json, plan_json, rig, writer  # noqa: F401
from tests.test_workflow_engine import flaky  # noqa: F401
from tests.test_workspace_connectors import principal
from tests.test_workspaces_api import mkws, signup

CANARY = "CANARY-wfapi-6108"
PING = [intent_json(), plan_json()]
WRITE = [intent_json("notes.task.update"), plan_json("notes.task.update", {"task_id": 5})]
HOUR = 3600


def step(i, agent="ops_agent", deps=(), text="Check system status", **kw):
    return {"id": i, "agent_id": agent, "instruction": text, "depends_on": list(deps), **kw}


def wf(key="nightly", steps=None, triggers=None, version=1, **kw):
    d = {"id": key, "name": key.title(), "version": version, "steps": steps or [step("a")]}
    if triggers is not None:
        d["triggers"] = triggers
    d.update(kw)
    return d


def base(ws):
    return f"/workspaces/{ws['id']}"


def define(client, h, ws, body):
    return client.post(f"{base(ws)}/workflows", json=body, headers=h)


def n(db, model):
    return db.scalar(select(func.count()).select_from(model))


def start(client, h, ws, key="nightly", **body):
    return client.post(f"{base(ws)}/workflows/{key}/runs", json=body, headers=h)


def drive(client, h, ws, run_id):
    return client.post(f"{base(ws)}/workflow-runs/{run_id}/drive", headers=h)


# ------------------------------------------------------------------ access
def test_every_route_requires_the_right_caller(rig):
    client, hs, ws, other, script = rig
    b = base(ws)
    routes = [("get", f"{b}/workflows"), ("get", f"{b}/workflows/x"), ("get", f"{b}/workflows/x/versions"),
              ("post", f"{b}/workflows/x/versions/1/archive"), ("post", f"{b}/workflows/x/runs"),
              ("get", f"{b}/workflow-runs"), ("get", f"{b}/workflow-runs/x"), ("post", f"{b}/workflow-runs/x/drive"),
              ("post", f"{b}/workflow-runs/x/cancel"), ("post", f"{b}/workflow-events"),
              ("get", f"{b}/workflow-events"), ("get", f"{b}/workflow-events/x"), ("get", f"{b}/workflow-schedules"),
              ("post", f"{b}/workflow-schedules"), ("post", f"{b}/workflow-schedules/disarm"),
              ("post", f"{b}/workflow-tick"), ("post", f"{b}/workflows")]
    for verb, p in routes:
        call = getattr(client, verb)
        kw = {"json": {}} if verb == "post" else {}
        assert call(p, **kw).status_code == 401, p
        assert call(p, headers=hs["outsider"], **kw).status_code == 404, p
        assert call(p, headers=hs["viewer"], **kw).status_code == 403, p


@pytest.mark.parametrize("verb,path,body", [
    ("post", "/workflows", wf()),
    ("post", "/workflows/nightly/versions/1/archive", None),
    ("post", "/workflow-schedules", {"workflow_key": "nightly", "interval_seconds": HOUR}),
    ("post", "/workflow-schedules/disarm", {"workflow_key": "nightly", "interval_seconds": HOUR}),
    ("post", "/workflow-tick", {}),
])
def test_members_cannot_use_admin_routes(rig, verb, path, body):
    client, hs, ws, _, _ = rig
    kw = {"json": body} if body is not None else {}
    assert getattr(client, verb)(base(ws) + path, headers=hs["member"], **kw).status_code == 403


# ------------------------------------------------------------------ definitions
def test_define_read_version_and_archive(rig, db_session):
    client, hs, ws, _, _ = rig
    r = define(client, hs["admin"], ws, wf(steps=[step("a", text=CANARY)]))
    assert r.status_code == 200, r.text
    assert r.json()["version"] == 1 and r.json()["steps"] == 1 and r.json()["status"] == "active"
    again = define(client, hs["admin"], ws, wf(steps=[step("a", text=CANARY)]))        # same version, same content
    assert again.status_code == 200 and n(db_session, WorkflowRecord) == 1
    assert define(client, hs["admin"], ws, wf(steps=[step("a", text="Other")])).status_code == 409
    assert define(client, hs["admin"], ws, wf(version=3)).status_code == 409
    assert define(client, hs["admin"], ws, wf(version=2, steps=[step("a"), step("b", deps=["a"])])).status_code == 200
    lst = client.get(f"{base(ws)}/workflows", headers=hs["member"])
    assert lst.status_code == 200 and [(w["key"], w["version"]) for w in lst.json()] == [("nightly", 2)]
    assert CANARY not in lst.text and all(w["definition"] is None for w in lst.json())   # text only on the single read
    one = client.get(f"{base(ws)}/workflows/nightly?version=1", headers=hs["member"])
    assert one.json()["definition"]["steps"][0]["instruction"] == CANARY
    assert [v["version"] for v in client.get(f"{base(ws)}/workflows/nightly/versions", headers=hs["member"]).json()] == [1, 2]
    assert client.get(f"{base(ws)}/workflows/ghost", headers=hs["member"]).status_code == 404
    arch = client.post(f"{base(ws)}/workflows/nightly/versions/2/archive", headers=hs["admin"])
    assert arch.status_code == 200 and arch.json()["status"] == "archived"
    assert start(client, hs["member"], ws, version=2).status_code == 409


@pytest.mark.parametrize("body", [
    {"id": "x", "name": "X", "steps": [step("a")], "extra": 1},            # unknown key
    {"id": "x", "name": "X"},                                              # missing steps
    {"id": "x", "name": "X", "steps": [step("a", agent="ghost_agent")]},   # unregistered agent
    {"id": "x", "name": "X", "steps": [step("a", deps=["b"]), step("b", deps=["a"])]},   # cycle
    {"id": "x", "name": "X", "steps": [step("a", text="password: hunter2hunter2")]},     # looks like a credential
    {"id": "x", "name": "X", "steps": [step("a", retry={"max_attempts": True})]},        # bool is not an int
    {"id": "x", "name": "X", "steps": [step("a")], "triggers": [{"type": "schedule", "interval_seconds": 5}]},
    {"id": "x", "name": "X", "steps": [step(f"s{i}") for i in range(30)]},               # over the ceiling
])
def test_invalid_definitions_are_422_and_store_nothing(rig, db_session, body):
    client, hs, ws, _, _ = rig
    r = define(client, hs["admin"], ws, body)
    assert r.status_code == 422 and n(db_session, WorkflowRecord) == 0
    assert "hunter2" not in r.text


def test_a_non_object_body_is_422(rig):
    client, hs, ws, _, _ = rig
    assert client.post(f"{base(ws)}/workflows", json=[1, 2], headers=hs["admin"]).status_code == 422


def test_workflows_never_cross_workspaces(rig):
    client, hs, ws, other, _ = rig
    assert define(client, hs["admin"], ws, wf()).status_code == 200
    run = start(client, hs["member"], ws).json()
    assert client.get(f"{base(other)}/workflows", headers=hs["outsider"]).json() == []
    assert client.get(f"{base(other)}/workflows/nightly", headers=hs["outsider"]).status_code == 404
    assert start(client, hs["outsider"], other).status_code == 404
    assert client.get(f"{base(other)}/workflow-runs/{run['id']}", headers=hs["outsider"]).status_code == 404
    assert client.get(f"{base(ws)}/workflow-runs/{run['id']}", headers=hs["outsider"]).status_code == 404


# ------------------------------------------------------------------ runs
def test_manual_start_creates_a_pending_run_and_executes_nothing(rig, db_session):
    client, hs, ws, _, _ = rig
    define(client, hs["admin"], ws, wf(steps=[step("a", text=CANARY), step("b", deps=["a"])]))
    r = start(client, hs["member"], ws, idempotency_key="k1")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "pending" and body["trigger_type"] == "manual" and body["step_count"] == 2
    assert [s["status"] for s in body["steps"]] == ["pending", "pending"]
    assert CANARY not in r.text and "digest" not in r.text
    assert n(db_session, AgentRun) == 0 and n(db_session, ToolExecution) == 0
    assert start(client, hs["member"], ws, idempotency_key="k1").json()["id"] == body["id"]     # idempotent
    assert n(db_session, WorkflowRunRecord) == 1


@pytest.mark.parametrize("body", [{"version": 0}, {"idempotency_key": ""}, {"idempotency_key": "x" * 129},
                                  {"role": "owner"}, {"version": "one"}])
def test_invalid_start_requests_are_422(rig, body):
    client, hs, ws, _, _ = rig
    define(client, hs["admin"], ws, wf())
    assert start(client, hs["member"], ws, **body).status_code == 422


def test_drive_runs_the_workflow_and_the_response_is_content_free(rig, db_session):
    client, hs, ws, _, script = rig
    define(client, hs["admin"], ws, wf(steps=[step("a", text=CANARY), step("b", deps=["a"])]))
    run = start(client, hs["member"], ws).json()
    script.extend([*PING, *PING])
    out = drive(client, hs["member"], ws, run["id"])
    assert out.status_code == 200, out.text
    body = out.json()
    assert body["drive_state"] == "completed" and body["run"]["status"] == "succeeded"
    assert [s["status"] for s in body["run"]["steps"]] == ["succeeded", "succeeded"]
    assert [s["attempts"] for s in body["run"]["steps"]] == [1, 1]
    assert CANARY not in out.text and CANARY not in client.get(f"{base(ws)}/workflow-runs/{run['id']}", headers=hs["member"]).text
    assert n(db_session, ToolExecution) == 2
    assert drive(client, hs["member"], ws, run["id"]).status_code == 409           # finished: not driven again
    assert n(db_session, ToolExecution) == 2


def test_only_the_creator_can_drive_and_an_admin_can_only_see_and_cancel(rig, db_session):
    client, hs, ws, _, script = rig
    define(client, hs["admin"], ws, wf())
    run = start(client, hs["member"], ws).json()
    for who in ("admin", "owner", "member2"):
        script.extend(PING)
        assert drive(client, hs[who], ws, run["id"]).status_code in (403, 404), who
    assert n(db_session, ToolExecution) == 0 and n(db_session, AgentRun) == 0
    assert client.get(f"{base(ws)}/workflow-runs/{run['id']}", headers=hs["admin"]).status_code == 200
    assert client.get(f"{base(ws)}/workflow-runs/{run['id']}", headers=hs["member2"]).status_code == 404
    assert [r["id"] for r in client.get(f"{base(ws)}/workflow-runs", headers=hs["admin"]).json()] == [run["id"]]
    assert client.get(f"{base(ws)}/workflow-runs", headers=hs["member2"]).json() == []
    assert client.post(f"{base(ws)}/workflow-runs/{run['id']}/cancel", headers=hs["member2"]).status_code == 404
    out = client.post(f"{base(ws)}/workflow-runs/{run['id']}/cancel", headers=hs["admin"])
    assert out.status_code == 200 and out.json()["status"] == "cancelled"


def test_an_approval_pauses_the_run_and_only_a_human_decision_resumes_it(writer, db_session):
    client, hs, ws, _, script = writer
    define(client, hs["admin"], ws, wf(steps=[step("w", "task_writer")]))
    run = start(client, hs["member"], ws).json()
    script.extend(WRITE)
    first = drive(client, hs["member"], ws, run["id"])
    assert first.json()["drive_state"] == "paused_approval" and CALLS == []
    assert first.json()["run"]["steps"][0]["status"] == "waiting_approval"
    assert drive(client, hs["member"], ws, run["id"]).json()["drive_state"] == "paused_approval" and CALLS == []
    approval = db_session.scalar(select(Approval))
    ApprovalService(db_session).decide(approval.id, principal(db_session, "owner@x.com", ws["id"]), approve=True)
    assert CALLS == []                                                             # a decision alone executes nothing
    done = drive(client, hs["member"], ws, run["id"])
    assert done.json()["drive_state"] == "completed" and len(CALLS) == 1


def test_cancel_over_http_withdraws_the_pending_approval(writer, db_session):
    client, hs, ws, _, script = writer
    define(client, hs["admin"], ws, wf(steps=[step("w", "task_writer")]))
    run = start(client, hs["member"], ws).json()
    script.extend(WRITE)
    drive(client, hs["member"], ws, run["id"])
    out = client.post(f"{base(ws)}/workflow-runs/{run['id']}/cancel", headers=hs["member"])
    assert out.status_code == 200 and out.json()["status"] == "cancelled"
    approval = db_session.scalar(select(Approval))
    with pytest.raises(Exception):
        ApprovalService(db_session).decide(approval.id, principal(db_session, "owner@x.com", ws["id"]), approve=True)
    again = drive(client, hs["member"], ws, run["id"])
    assert CALLS == [] and again.status_code == 200 and again.json()["drive_state"] == "cancelled"


def test_a_transient_failure_schedules_a_retry_and_a_later_drive_resumes(rig, db_session, app):
    client, hs, ws, _, script = rig
    retry = {"max_attempts": 2, "backoff": "fixed", "delay_seconds": 60}
    define(client, hs["admin"], ws, wf(steps=[step("a", retry=retry)]))
    run = start(client, hs["member"], ws).json()
    script.extend(flaky())
    first = drive(client, hs["member"], ws, run["id"])
    assert first.status_code == 200, first.text
    assert first.json()["drive_state"] == "waiting_retry" and first.json()["retry_at"]
    st = first.json()["run"]["steps"][0]
    assert st["status"] == "pending" and st["attempts"] == 1 and st["next_attempt_at"]
    assert n(db_session, ToolExecution) == 0
    db_session.execute(update(WorkflowStepRecord).values(next_attempt_at=None))   # the delay has passed
    db_session.commit()
    script.extend(PING)
    assert drive(client, hs["member"], ws, run["id"]).json()["drive_state"] == "completed"


def test_drive_without_a_usable_model_fails_closed_and_runs_nothing(rig, db_session, monkeypatch):
    from app.llm.errors import LLMAuthError
    client, hs, ws, _, script = rig
    define(client, hs["admin"], ws, wf())
    run = start(client, hs["member"], ws).json()
    script.extend([LLMAuthError("bad key")])
    out = drive(client, hs["member"], ws, run["id"])
    assert out.status_code in (200, 401, 424, 502, 503) and n(db_session, ToolExecution) == 0
    assert "bad key" not in out.text


# ------------------------------------------------------------------ events
def test_events_start_pending_runs_for_declared_triggers_only_and_are_idempotent(rig, db_session):
    client, hs, ws, _, _ = rig
    define(client, hs["admin"], ws, wf("onlead", triggers=[{"type": "manual"}, {"type": "event", "event_type": "lead.created"}]))
    define(client, hs["admin"], ws, wf("manualonly"))
    r = client.post(f"{base(ws)}/workflow-events", json={"event_type": "lead.created", "event_ref": "lead-1"}, headers=hs["member"])
    assert r.status_code == 200, r.text
    ev = r.json()["event"]
    assert r.json()["duplicate"] is False and ev["matched"] == 1 and ev["started"] == 1 and len(ev["run_ids"]) == 1
    run = client.get(f"{base(ws)}/workflow-runs/{ev['run_ids'][0]}", headers=hs["member"]).json()
    assert run["status"] == "pending" and run["trigger_type"] == "event" and run["workflow_key"] == "onlead"
    assert n(db_session, AgentRun) == 0 and n(db_session, ToolExecution) == 0       # an event executes nothing
    dup = client.post(f"{base(ws)}/workflow-events", json={"event_type": "lead.created", "event_ref": "lead-1"}, headers=hs["member"])
    assert dup.json()["duplicate"] is True and dup.json()["event"]["run_ids"] == ev["run_ids"]
    assert n(db_session, WorkflowRunRecord) == 1
    none = client.post(f"{base(ws)}/workflow-events", json={"event_type": "other.thing", "event_ref": "x"}, headers=hs["member"])
    assert none.json()["event"]["matched"] == 0 and n(db_session, WorkflowRunRecord) == 1
    stolen = client.post(f"{base(ws)}/workflow-events", json={"event_type": "lead.created", "event_ref": "lead-1"}, headers=hs["member2"])
    assert stolen.status_code == 409
    assert client.get(f"{base(ws)}/workflow-events/{ev['id']}", headers=hs["member2"]).status_code == 404
    assert client.get(f"{base(ws)}/workflow-events/{ev['id']}", headers=hs["admin"]).status_code == 200
    assert client.get(f"{base(ws)}/workflow-events", headers=hs["member2"]).json() == []
    assert len(client.get(f"{base(ws)}/workflow-events", headers=hs["admin"]).json()) == 2


@pytest.mark.parametrize("body", [{"event_type": "Lead Created", "event_ref": "x"}, {"event_type": "lead.created", "event_ref": "has space"},
                                  {"event_type": "lead.created", "event_ref": "x", "payload": {"a": 1}},
                                  {"event_type": "lead.created"}, {"event_type": "", "event_ref": "x"}])
def test_invalid_events_are_422_and_nothing_is_stored(rig, db_session, body):
    client, hs, ws, _, _ = rig
    assert client.post(f"{base(ws)}/workflow-events", json=body, headers=hs["member"]).status_code == 422
    assert n(db_session, WorkflowEventRecord) == 0


def test_event_audit_never_holds_the_reference(rig, db_session):
    client, hs, ws, _, _ = rig
    define(client, hs["admin"], ws, wf("onlead", triggers=[{"type": "event", "event_type": "lead.created"}]))
    client.post(f"{base(ws)}/workflow-events", json={"event_type": "lead.created", "event_ref": "cust-CANARY9"}, headers=hs["member"])
    assert "cust-CANARY9" not in json.dumps([e.payload for e in db_session.scalars(select(SystemEvent))])


# ------------------------------------------------------------------ schedules and tick
def sched_body(key="nightly", interval=HOUR):
    return {"workflow_key": key, "interval_seconds": interval}


def test_arm_list_and_disarm_a_schedule(rig, db_session):
    client, hs, ws, _, _ = rig
    define(client, hs["admin"], ws, wf(triggers=[{"type": "schedule", "interval_seconds": HOUR}]))
    r = client.post(f"{base(ws)}/workflow-schedules", json=sched_body(), headers=hs["admin"])
    assert r.status_code == 200, r.text
    assert r.json()["enabled"] is True and r.json()["interval_seconds"] == HOUR and r.json()["fired_count"] == 0
    assert client.post(f"{base(ws)}/workflow-schedules", json=sched_body(), headers=hs["admin"]).json()["id"] == r.json()["id"]
    assert n(db_session, WorkflowScheduleRecord) == 1
    assert [s["workflow_key"] for s in client.get(f"{base(ws)}/workflow-schedules", headers=hs["member"]).json()] == ["nightly"]
    off = client.post(f"{base(ws)}/workflow-schedules/disarm", json=sched_body(), headers=hs["admin"])
    assert off.status_code == 200 and off.json()["enabled"] is False and off.json()["disabled_reason"] == "disarmed"
    assert client.post(f"{base(ws)}/workflow-schedules/disarm", json=sched_body("ghost"), headers=hs["admin"]).status_code == 404


def test_arming_needs_a_declared_trigger_and_a_valid_interval(rig, db_session):
    client, hs, ws, _, _ = rig
    define(client, hs["admin"], ws, wf(triggers=[{"type": "schedule", "interval_seconds": HOUR}]))
    assert client.post(f"{base(ws)}/workflow-schedules", json=sched_body(interval=7200), headers=hs["admin"]).status_code == 422
    assert client.post(f"{base(ws)}/workflow-schedules", json=sched_body(interval=5), headers=hs["admin"]).status_code == 422
    assert client.post(f"{base(ws)}/workflow-schedules", json=sched_body("ghost"), headers=hs["admin"]).status_code == 404
    assert client.post(f"{base(ws)}/workflow-schedules", json={**sched_body(), "x": 1}, headers=hs["admin"]).status_code == 422
    assert n(db_session, WorkflowScheduleRecord) == 0


def backdate(db):
    for sched in db.scalars(select(WorkflowScheduleRecord)):
        sched.next_fire_at = sched.next_fire_at - timedelta(days=1)
    db.commit()


def test_tick_fires_a_due_schedule_and_drives_it_as_its_owner(rig, db_session):
    client, hs, ws, _, script = rig
    define(client, hs["admin"], ws, wf(triggers=[{"type": "schedule", "interval_seconds": HOUR}]))
    client.post(f"{base(ws)}/workflow-schedules", json=sched_body(), headers=hs["admin"])
    nothing = client.post(f"{base(ws)}/workflow-tick", json={}, headers=hs["admin"])
    assert nothing.status_code == 200 and nothing.json()["fired"] == 0 and n(db_session, WorkflowRunRecord) == 0
    backdate(db_session)
    script.extend(PING)
    out = client.post(f"{base(ws)}/workflow-tick", json={}, headers=hs["admin"])
    assert out.status_code == 200, out.text
    assert out.json()["fired"] == 1 and out.json()["driven"] == 1 and out.json()["states"] == {"completed": 1}
    run = db_session.scalar(select(WorkflowRunRecord))
    assert run.trigger_type == "schedule" and run.status.value == "succeeded"
    assert client.get(f"{base(ws)}/workflow-schedules", headers=hs["admin"]).json()[0]["fired_count"] == 1
    again = client.post(f"{base(ws)}/workflow-tick", json={}, headers=hs["admin"])
    assert again.json()["fired"] == 0 and n(db_session, WorkflowRunRecord) == 1


def test_tick_can_fire_without_driving_and_needs_no_model(rig, db_session):
    client, hs, ws, _, _ = rig
    define(client, hs["admin"], ws, wf(triggers=[{"type": "schedule", "interval_seconds": HOUR}]))
    client.post(f"{base(ws)}/workflow-schedules", json=sched_body(), headers=hs["admin"])
    backdate(db_session)
    out = client.post(f"{base(ws)}/workflow-tick", json={"drive": False}, headers=hs["admin"])
    assert out.json()["fired"] == 1 and out.json()["driven"] == 0
    assert db_session.scalar(select(WorkflowRunRecord)).status.value == "pending" and n(db_session, ToolExecution) == 0


def test_tick_drives_event_started_runs_but_never_manual_ones(rig, db_session):
    client, hs, ws, _, script = rig
    define(client, hs["admin"], ws, wf("onlead", triggers=[{"type": "manual"}, {"type": "event", "event_type": "lead.created"}]))
    manual = start(client, hs["member"], ws, "onlead").json()
    client.post(f"{base(ws)}/workflow-events", json={"event_type": "lead.created", "event_ref": "l1"}, headers=hs["member"])
    script.extend(PING)
    out = client.post(f"{base(ws)}/workflow-tick", json={}, headers=hs["admin"])
    assert out.json()["driven"] == 1 and n(db_session, ToolExecution) == 1
    assert client.get(f"{base(ws)}/workflow-runs/{manual['id']}", headers=hs["member"]).json()["status"] == "pending"


def test_tick_never_touches_another_workspace(rig, db_session):
    client, hs, ws, other, script = rig
    for w, h in ((ws, hs["admin"]), (other, hs["outsider"])):
        define(client, h, w, wf(triggers=[{"type": "schedule", "interval_seconds": HOUR}]))
        client.post(f"{base(w)}/workflow-schedules", json=sched_body(), headers=h)
    backdate(db_session)
    out = client.post(f"{base(other)}/workflow-tick", json={"drive": False}, headers=hs["outsider"])
    assert out.json()["fired"] == 1
    runs = list(db_session.scalars(select(WorkflowRunRecord)))
    assert [r.workspace_id for r in runs] == [other["id"]]
    scheds = {s.workspace_id: s for s in db_session.scalars(select(WorkflowScheduleRecord))}
    assert scheds[other["id"]].fired_count == 1 and scheds[ws["id"]].fired_count == 0
    assert client.post(f"{base(ws)}/workflow-tick", json={"drive": False}, headers=hs["outsider"]).status_code == 404


def test_a_schedule_whose_owner_lost_admin_disables_itself_at_the_next_tick(rig, db_session):
    from app.models import Membership, Role
    client, hs, ws, _, _ = rig
    define(client, hs["admin"], ws, wf(triggers=[{"type": "schedule", "interval_seconds": HOUR}]))
    client.post(f"{base(ws)}/workflow-schedules", json=sched_body(), headers=hs["admin"])
    sched = db_session.scalar(select(WorkflowScheduleRecord))
    db_session.execute(update(Membership).where(Membership.user_id == sched.armed_by).values(role=Role.MEMBER))
    db_session.commit()
    backdate(db_session)
    client.post(f"{base(ws)}/workflow-tick", json={"drive": False}, headers=hs["owner"])
    db_session.refresh(sched)
    assert sched.enabled is False and sched.disabled_reason == "owner_unavailable" and n(db_session, WorkflowRunRecord) == 0


# ------------------------------------------------------------------ authority and audit, end to end
def test_a_workflow_step_cannot_use_a_tool_outside_its_agent(rig, db_session):
    """Authority is the agent's, not the workflow's: a model naming a tool the agent may not use executes nothing."""
    client, hs, ws, _, script = rig
    define(client, hs["admin"], ws, wf())
    run = start(client, hs["member"], ws).json()
    script.extend([intent_json("aceden.customer.delete"), plan_json("aceden.customer.delete", {"customer_id": 1})])
    out = drive(client, hs["member"], ws, run["id"])
    assert out.status_code == 200
    assert out.json()["run"]["steps"][0]["result"]["outcome"] == "no_action"       # not actionable: nothing ran
    assert n(db_session, ToolExecution) == 0


def test_the_whole_lifecycle_is_audited_without_any_instruction_text(rig, db_session):
    client, hs, ws, _, script = rig
    define(client, hs["admin"], ws, wf(steps=[step("a", text=CANARY)], triggers=[{"type": "manual"}, {"type": "schedule", "interval_seconds": HOUR}]))
    client.post(f"{base(ws)}/workflow-schedules", json=sched_body(), headers=hs["admin"])
    run = start(client, hs["member"], ws).json()
    script.extend(PING)
    drive(client, hs["member"], ws, run["id"])
    client.post(f"{base(ws)}/workflow-events", json={"event_type": "a.b", "event_ref": "r1"}, headers=hs["member"])
    types = {e.event_type for e in db_session.scalars(select(SystemEvent))}
    assert {"workflow.defined", "workflow.run_created", "workflow.schedule_armed", "workflow.event_received"} <= types
    payloads = json.dumps([e.payload for e in db_session.scalars(select(SystemEvent)) if e.event_type.startswith("workflow.")])
    assert CANARY not in payloads
    for model in (WorkflowRunRecord, WorkflowStepRecord, WorkflowScheduleRecord, WorkflowEventRecord):
        for row in db_session.scalars(select(model)):
            assert CANARY not in json.dumps({c.name: str(getattr(row, c.name)) for c in row.__table__.columns})


def test_errors_are_fixed_text_and_never_echo_input(rig):
    client, hs, ws, _, _ = rig
    for r in (define(client, hs["admin"], ws, wf(steps=[step("a", text=f"token: {CANARY}-aaaaaaaaaaaaaaaaaaaa")])),
              client.post(f"{base(ws)}/workflow-events", json={"event_type": CANARY, "event_ref": "x"}, headers=hs["member"])):
        assert r.status_code == 422 and CANARY not in r.text


def test_unexpected_failures_do_not_leak_internals(rig, monkeypatch):
    client, hs, ws, _, _ = rig
    define(client, hs["admin"], ws, wf())
    from app.workflows.store import WorkflowService

    def boom(*a, **k):
        raise RuntimeError(f"db password {CANARY}")
    monkeypatch.setattr(WorkflowService, "create_run", boom)
    from fastapi.testclient import TestClient
    safe = TestClient(client.app, raise_server_exceptions=False)
    r = safe.post(f"{base(ws)}/workflows/nightly/runs", json={}, headers=hs["member"])
    assert r.status_code == 500 and CANARY not in r.text and r.json() == {"detail": "Internal server error"}
