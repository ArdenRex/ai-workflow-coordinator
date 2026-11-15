"""Step F4: approval inbox and workspace activity over HTTP."""
import json

from sqlalchemy import select

from app.models import Approval, ApprovalStatus, SystemEvent
from tests.test_agent_context import CALLS
from tests.test_agent_runs_api import base as runs_base, intent_json, plan_json, rig, writer  # noqa: F401


def ab(ws):
    return f"/workspaces/{ws['id']}/approvals"


def waiting(client, hs, ws, script, user="member"):
    script.extend([intent_json("notes.task.update"), plan_json("notes.task.update", {"task_id": 5})])
    run = client.post(f"{runs_base(ws)}/runs", json={"agent_id": "task_writer", "goal": "update task five"}, headers=hs[user]).json()
    assert run["status"] == "waiting_approval"
    return run


def test_every_route_needs_a_signed_in_member_of_the_workspace(writer):
    client, hs, ws, other, script = writer
    routes = [("get", ab(ws)), ("get", f"{ab(ws)}/x"), ("post", f"{ab(ws)}/x/approve"), ("post", f"{ab(ws)}/x/reject"),
              ("get", f"/workspaces/{ws['id']}/activity")]
    for verb, p in routes:
        assert getattr(client, verb)(p).status_code == 401
        assert getattr(client, verb)(p, headers=hs["outsider"]).status_code == 404


def test_admin_sees_the_input_and_approving_runs_nothing(writer):
    client, hs, ws, _, script = writer
    run = waiting(client, hs, ws, script)
    rows = client.get(ab(ws), headers=hs["admin"]).json()
    assert len(rows) == 1 and rows[0]["status"] == "PENDING" and rows[0]["tool_id"] == "notes.task.update"
    assert rows[0]["input"] == {"task_id": 5} and rows[0]["can_decide"] is True
    r = client.post(f"{ab(ws)}/{rows[0]['id']}/approve", json={"reason": "ok"}, headers=hs["admin"])
    assert r.status_code == 200 and r.json()["status"] == "APPROVED" and r.json()["decided_by"] and CALLS == []
    assert client.post(f"{ab(ws)}/{rows[0]['id']}/approve", headers=hs["admin"]).status_code == 409   # only once
    assert client.post(f"{ab(ws)}/{rows[0]['id']}/reject", headers=hs["admin"]).status_code == 409
    done = client.post(f"{runs_base(ws)}/runs/{run['id']}/resume", headers=hs["member"])
    assert done.json()["status"] == "succeeded" and len(CALLS) == 1


def test_reject_stops_the_action(writer):
    client, hs, ws, _, script = writer
    run = waiting(client, hs, ws, script)
    aid = client.get(ab(ws), headers=hs["owner"]).json()[0]["id"]
    r = client.post(f"{ab(ws)}/{aid}/reject", json={"reason": "no"}, headers=hs["owner"])
    assert r.json()["status"] == "REJECTED" and r.json()["reason"] == "no"
    assert client.post(f"{runs_base(ws)}/runs/{run['id']}/resume", headers=hs["member"]).status_code in (409, 200)
    assert CALLS == []


def test_the_requester_cannot_decide_their_own_and_members_cannot_decide_at_all(writer):
    client, hs, ws, _, script = writer
    waiting(client, hs, ws, script, user="admin")                  # an admin asked for it
    aid = client.get(ab(ws), headers=hs["admin"]).json()[0]["id"]
    assert client.get(ab(ws), headers=hs["admin"]).json()[0]["can_decide"] is False
    assert client.post(f"{ab(ws)}/{aid}/approve", headers=hs["admin"]).status_code == 403
    assert client.post(f"{ab(ws)}/{aid}/approve", headers=hs["member"]).status_code == 404    # not theirs, not a decider
    assert client.post(f"{ab(ws)}/{aid}/approve", headers=hs["viewer"]).status_code == 404
    assert client.get(ab(ws), headers=hs["member"]).json() == []
    assert CALLS == []


def test_a_requester_without_decide_rights_sees_their_own_without_the_input(writer):
    client, hs, ws, _, script = writer
    waiting(client, hs, ws, script)
    own = client.get(ab(ws), headers=hs["member"]).json()
    assert len(own) == 1 and own[0]["input"] is None and own[0]["can_decide"] is False
    assert client.get(ab(ws), headers=hs["member2"]).json() == []
    assert client.get(f"{ab(ws)}/{own[0]['id']}", headers=hs["member"]).json()["input"] is None
    assert client.get(f"{ab(ws)}/{own[0]['id']}", headers=hs["member2"]).status_code == 404
    assert client.post(f"{ab(ws)}/{own[0]["id"]}/approve", headers=hs["member"]).status_code == 403


def test_another_workspace_cannot_reach_the_approval(writer):
    client, hs, ws, other, script = writer
    waiting(client, hs, ws, script)
    aid = client.get(ab(ws), headers=hs["admin"]).json()[0]["id"]
    assert client.get(f"{ab(other)}/{aid}", headers=hs["outsider"]).status_code == 404
    assert client.post(f"{ab(other)}/{aid}/approve", headers=hs["outsider"]).status_code == 404
    assert client.get(ab(other), headers=hs["outsider"]).json() == []


def test_an_overdue_approval_shows_expired_and_cannot_be_approved(writer, db_session):
    from datetime import datetime, timedelta, timezone
    client, hs, ws, _, script = writer
    waiting(client, hs, ws, script)
    a = db_session.scalar(select(Approval))
    a.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()
    rows = client.get(ab(ws), headers=hs["admin"]).json()
    assert rows[0]["status"] == "EXPIRED" and rows[0]["can_decide"] is False
    assert client.post(f"{ab(ws)}/{rows[0]['id']}/approve", headers=hs["admin"]).status_code == 409


def test_filter_validation_and_extra_fields(writer):
    client, hs, ws, _, script = writer
    waiting(client, hs, ws, script)
    assert client.get(f"{ab(ws)}?status=NOPE", headers=hs["admin"]).status_code == 422
    assert client.get(f"{ab(ws)}?status=APPROVED", headers=hs["admin"]).json() == []
    assert len(client.get(f"{ab(ws)}?status=PENDING", headers=hs["admin"]).json()) == 1
    aid = client.get(ab(ws), headers=hs["admin"]).json()[0]["id"]
    assert client.post(f"{ab(ws)}/{aid}/approve", json={"status": "x"}, headers=hs["admin"]).status_code == 422
    assert client.post(f"{ab(ws)}/{aid}/approve", json={"reason": "x" * 501}, headers=hs["admin"]).status_code == 422


def test_activity_is_for_auditors_only_and_shows_codes_not_content(writer, db_session):
    client, hs, ws, other, script = writer
    waiting(client, hs, ws, script)
    url = f"/workspaces/{ws['id']}/activity"
    assert client.get(url, headers=hs["member"]).status_code == 403
    assert client.get(url, headers=hs["viewer"]).status_code == 403
    ev = db_session.scalar(select(SystemEvent).where(SystemEvent.event_type == "approval.requested"))
    ev.payload = {**ev.payload, "input": {"secret": "CANARY-act-77"}, "input_sha256": "abc"}
    db_session.commit()
    body = client.get(url, headers=hs["admin"])
    assert body.status_code == 200 and "approval.requested" in {e["event_type"] for e in body.json()}
    assert "CANARY-act-77" not in json.dumps(body.json()) and "input_sha256" not in json.dumps(body.json())
    assert client.get(f"{url}?event_type=approval.requested", headers=hs["admin"]).json()[0]["details"]["tool_id"] == "notes.task.update"
    assert client.get(f"/workspaces/{other['id']}/activity", headers=hs["admin"]).status_code == 404
    assert client.get(f"{url}?limit=0", headers=hs["admin"]).status_code == 422
