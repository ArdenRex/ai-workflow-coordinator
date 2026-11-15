"""Substep 7.5: result aggregation + the plans HTTP API."""
import json

import pytest
from sqlalchemy import func, select

from app.kernel.approvals import ApprovalService
from app.llm.errors import LLMAuthError
from app.models import Approval, ApprovalStatus, SystemEvent, ToolExecution
from app.models.agents import AgentRun
from app.models.orchestration import PlanRecord
from app.orchestration.aggregate import headline, summarize
from app.models.enums import PlanStatus as P
from tests.test_agent_context import CALLS
from tests.test_agent_runs_api import intent_json, plan_json, rig, writer  # noqa: F401
from tests.test_workspace_connectors import principal

GOAL = "Check the system, then summarise tasks"
CANARY = "CANARY-plan-text-3302"
PING = [intent_json(), plan_json()]
WRITE = [intent_json("notes.task.update"), plan_json("notes.task.update", {"task_id": 5})]


def base(ws):
    return f"/workspaces/{ws['id']}/plans"


def st(i, agent="ops_agent", deps=(), text="Check system status"):
    return {"id": i, "agent_id": agent, "instruction": text, "depends_on": list(deps)}


def decomp(steps, missing=(), rationale="because"):
    return json.dumps({"steps": steps, "rationale": rationale, "missing_information": list(missing)})


def create(client, h, ws, script, steps, *items, goal=GOAL, **extra):
    script.extend([decomp(steps), *items])
    return client.post(base(ws), json={"goal": goal, **extra}, headers=h)


def run_body(r, goal=GOAL):
    return {"goal": goal, "steps": r.json()["proposed_steps"]}


def n(db, model):
    return db.scalar(select(func.count()).select_from(model))


# ------------------------------------------------------------------ pure aggregation
class FakeStep:
    def __init__(self, key, status, agent="ops_agent", run_id=None, error_code=None, result=None):
        self.step_key, self.status, self.agent_id, self.run_id = key, status, agent, run_id
        self.error_code, self.result = error_code, result


def test_summary_counts_failures_and_attention_and_ignores_unknown_result_fields():
    from app.models.enums import StepState as S
    steps = [FakeStep("a", S.SUCCEEDED, result={"outcome": "executed", "tool_id": "system.ping", "secret": CANARY,
                                                  "nested": {"x": 1}}),
             FakeStep("b", S.FAILED, error_code="llm_auth"), FakeStep("c", S.SKIPPED),
             FakeStep("d", S.WAITING_APPROVAL, run_id="r1"), FakeStep("e", S.PENDING)]
    s = summarize(P.RUNNING, steps, {"r1": "ex1"})
    assert s["headline"] == "waiting_approval" and s["total_steps"] == 5 and s["finished_steps"] == 3
    assert s["counts"]["succeeded"] == 1 and s["failures"] == [{"step": "b", "agent": "ops_agent", "error_code": "llm_auth"}]
    assert s["skipped"] == ["c"] and s["needs_attention"]["approvals"][0]["execution_id"] == "ex1"
    assert CANARY not in json.dumps(s) and "nested" not in json.dumps(s)


@pytest.mark.parametrize("status,expected", [(P.SUCCEEDED, "succeeded"), (P.FAILED, "failed"), (P.CANCELLED, "cancelled"),
                                             (P.PENDING, "pending"), (P.RUNNING, "running")])
def test_headline_words_are_fixed(status, expected):
    assert headline(status, {}) == expected


# ------------------------------------------------------------------ access
def test_every_plan_route_requires_the_right_caller(rig):
    client, hs, ws, other, script = rig
    routes = [("get", base(ws)), ("get", f"{base(ws)}/x"), ("post", f"{base(ws)}/x/cancel"), ("post", base(ws)),
              ("post", f"{base(ws)}/x/run")]
    for verb, p in routes:
        call = getattr(client, verb)
        kw = {"json": {}} if verb == "post" else {}
        assert call(p, **kw).status_code == 401
        assert call(p, headers=hs["outsider"], **kw).status_code == 404
        assert call(p, headers=hs["viewer"], **kw).status_code == 403


# ------------------------------------------------------------------ create
def test_create_returns_a_reviewable_proposal_stores_content_free_and_runs_nothing(rig, db_session):
    client, hs, ws, _, script = rig
    r = create(client, hs["member"], ws, script, [st("a", text=CANARY), st("b", "insight_agent", ["a"])])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["decomposition"] == "planned" and [s["id"] for s in body["proposed_steps"]] == ["a", "b"]
    assert body["proposed_steps"][0]["instruction"] == CANARY               # only the requester sees this, once
    plan = body["plan"]
    assert plan["status"] == "pending" and plan["step_count"] == 2 and plan["summary"]["headline"] == "pending"
    assert CANARY not in json.dumps(plan) and GOAL not in json.dumps(plan) and "digest" not in json.dumps(plan)
    assert n(db_session, AgentRun) == 0 and n(db_session, ToolExecution) == 0
    assert CANARY not in client.get(f"{base(ws)}/{plan['id']}", headers=hs["member"]).text


@pytest.mark.parametrize("script_item,expect,reason", [
    (decomp([], ["Which region?"]), "needs_information", "missing_information"),
    (decomp([]), "no_action", "model_chose_no_plan"),
    (decomp([st("a", "ghost_agent")]), "rejected", "agent_not_allowed"),
    (decomp([st("a", deps=["b"]), st("b", deps=["a"])]), "rejected", "plan_invalid"),
])
def test_non_planned_outcomes_store_nothing(rig, db_session, script_item, expect, reason):
    client, hs, ws, _, script = rig
    script.extend([script_item] * 4)
    r = client.post(base(ws), json={"goal": GOAL}, headers=hs["member"])
    assert r.status_code == 200 and r.json()["decomposition"] == expect and r.json()["reason"] == reason
    assert r.json()["plan"] is None and n(db_session, PlanRecord) == 0 and n(db_session, AgentRun) == 0


@pytest.mark.parametrize("payload", [{"goal": "  "}, {"goal": "x" * 4001}, {}, {"goal": GOAL, "role": "owner"},
                                     {"goal": GOAL, "execute": "maybe"}])
def test_invalid_create_requests_are_422(rig, db_session, payload):
    client, hs, ws, *_ = rig
    assert client.post(base(ws), json=payload, headers=hs["member"]).status_code == 422
    assert n(db_session, PlanRecord) == 0


# ------------------------------------------------------------------ run
def test_run_executes_the_plan_and_the_response_is_content_free(rig, db_session):
    client, hs, ws, _, script = rig
    r = create(client, hs["member"], ws, script, [st("a", text=CANARY), st("b", deps=["a"])])
    pid = r.json()["plan"]["id"]
    script.extend([*PING, *PING])
    out = client.post(f"{base(ws)}/{pid}/run", json=run_body(r), headers=hs["member"])
    assert out.status_code == 200, out.text
    body = out.json()
    assert body["drive_state"] == "completed" and body["plan"]["status"] == "succeeded"
    assert body["plan"]["summary"]["headline"] == "succeeded" and body["plan"]["summary"]["finished_steps"] == 2
    assert CANARY not in out.text and GOAL not in out.text
    assert n(db_session, ToolExecution) == 2
    assert client.post(f"{base(ws)}/{pid}/run", json=run_body(r), headers=hs["member"]).status_code == 409
    assert n(db_session, ToolExecution) == 2


def test_execute_true_plans_and_runs_in_one_call(rig, db_session):
    client, hs, ws, _, script = rig
    r = create(client, hs["member"], ws, script, [st("a"), st("b", deps=["a"])], *PING, *PING, execute=True)
    assert r.status_code == 200 and r.json()["drive_state"] == "completed"
    assert r.json()["plan"]["status"] == "succeeded" and n(db_session, ToolExecution) == 2


def test_run_refuses_a_different_goal_or_edited_steps_and_runs_nothing(rig, db_session):
    client, hs, ws, _, script = rig
    r = create(client, hs["member"], ws, script, [st("a")])
    pid, url = r.json()["plan"]["id"], f"{base(ws)}/{r.json()['plan']['id']}/run"
    assert client.post(url, json=run_body(r, "another goal"), headers=hs["member"]).status_code == 422
    edited = run_body(r)
    edited["steps"][0]["instruction"] = "Delete everything"
    assert client.post(url, json=edited, headers=hs["member"]).status_code == 422
    cyc = {"goal": GOAL, "steps": [st("a", deps=["b"]), st("b", deps=["a"])]}
    assert client.post(url, json=cyc, headers=hs["member"]).status_code == 422
    ghost = {"goal": GOAL, "steps": [st("a", "ghost_agent")]}
    assert client.post(url, json=ghost, headers=hs["member"]).status_code == 422
    assert client.post(url, json={"goal": GOAL, "steps": [{**st("a"), "tool_id": "x"}]}, headers=hs["member"]).status_code == 422
    assert n(db_session, AgentRun) == 0 and client.get(f"{base(ws)}/{pid}", headers=hs["member"]).json()["status"] == "pending"


def test_a_failed_step_is_reported_with_a_fixed_code_and_skips_dependents(rig, db_session):
    client, hs, ws, _, script = rig
    r = create(client, hs["member"], ws, script, [st("a"), st("b", deps=["a"])])
    script.append(LLMAuthError("provider key rejected"))                     # a's first model call fails
    out = client.post(f"{base(ws)}/{r.json()['plan']['id']}/run", json=run_body(r), headers=hs["member"]).json()
    s = out["plan"]["summary"]
    assert out["plan"]["status"] == "failed" and s["headline"] == "failed" and s["skipped"] == ["b"]
    assert len(s["failures"]) == 1 and s["failures"][0]["step"] == "a" and s["failures"][0]["error_code"]


# ------------------------------------------------------------------ visibility / authority
def test_visibility_and_driving_rules(rig):
    client, hs, ws, other, script = rig
    r = create(client, hs["member"], ws, script, [st("a")])
    pid = r.json()["plan"]["id"]
    url = f"{base(ws)}/{pid}"
    assert client.get(url, headers=hs["member2"]).status_code == 404                 # not theirs
    assert client.get(url, headers=hs["admin"]).status_code == 200                   # admins see all
    assert client.get(url, headers=hs["outsider"]).status_code == 404
    assert [p["id"] for p in client.get(base(ws), headers=hs["member"]).json()] == [pid]
    assert client.get(base(ws), headers=hs["member2"]).json() == []
    assert client.post(f"{url}/run", json=run_body(r), headers=hs["admin"]).status_code == 403   # cannot drive
    assert client.post(f"{url}/run", json=run_body(r), headers=hs["member2"]).status_code == 404
    assert client.post(f"{url}/cancel", headers=hs["member2"]).status_code == 404
    assert client.post(f"{url}/cancel", headers=hs["admin"]).json()["status"] == "cancelled"
    assert client.get(f"/workspaces/{other['id']}/plans/{pid}", headers=hs["outsider"]).status_code == 404


def test_idempotency_key_reused_for_a_different_goal_is_409(rig):
    client, hs, ws, _, script = rig
    assert create(client, hs["member"], ws, script, [st("a")], idempotency_key="k1").status_code == 200
    r = create(client, hs["member"], ws, script, [st("a")], goal="a different goal", idempotency_key="k1")
    assert r.status_code == 409


# ------------------------------------------------------------------ approvals over HTTP
def test_approval_pause_then_continue_after_a_human_decides(writer, db_session):
    client, hs, ws, _, script = writer
    steps = [st("w", "task_writer"), st("x"), st("y", deps=["w"])]
    r = create(client, hs["member"], ws, script, steps, *WRITE, *PING, *PING, execute=True)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["drive_state"] == "paused_approval" and CALLS == []
    summ = body["plan"]["summary"]
    assert summ["headline"] == "waiting_approval" and len(summ["needs_attention"]["approvals"]) == 1
    ex_id = summ["needs_attention"]["approvals"][0]["execution_id"]
    assert ex_id
    url = f"{base(ws)}/{body['plan']['id']}/run"
    again = client.post(url, json=run_body(r), headers=hs["member"])
    assert again.json()["drive_state"] == "paused_approval" and CALLS == []
    approval = db_session.scalar(select(Approval).where(Approval.execution_id == ex_id))
    ApprovalService(db_session).decide(approval.id, principal(db_session, "owner@x.com", ws["id"]), approve=True)
    assert CALLS == []
    done = client.post(url, json=run_body(r), headers=hs["member"])
    assert done.json()["drive_state"] == "completed" and done.json()["plan"]["status"] == "succeeded"
    assert len(CALLS) == 1


def test_cancel_over_http_cancels_runs_and_withdraws_the_approval(writer, db_session):
    client, hs, ws, _, script = writer
    r = create(client, hs["member"], ws, script, [st("w", "task_writer"), st("y", deps=["w"])], *WRITE, execute=True)
    ex_id = r.json()["plan"]["summary"]["needs_attention"]["approvals"][0]["execution_id"]
    out = client.post(f"{base(ws)}/{r.json()['plan']['id']}/cancel", headers=hs["member"])
    assert out.status_code == 200 and out.json()["status"] == "cancelled"
    assert {s["status"] for s in out.json()["steps"]} == {"cancelled"}
    approval = db_session.scalar(select(Approval).where(Approval.execution_id == ex_id))
    assert approval.status == ApprovalStatus.REJECTED and CALLS == []
    assert client.post(f"{base(ws)}/{r.json()['plan']['id']}/cancel", headers=hs["member"]).json()["status"] == "cancelled"


# ------------------------------------------------------------------ leaks
def test_no_goal_or_instruction_text_in_logs_events_or_reads(rig, db_session, caplog):
    client, hs, ws, _, script = rig
    with caplog.at_level("DEBUG"):
        r = create(client, hs["member"], ws, script, [st("a", text=CANARY)], *PING, goal=CANARY, execute=True)
        reads = [client.get(base(ws), headers=hs["member"]).text,
                 client.get(f"{base(ws)}/{r.json()['plan']['id']}", headers=hs["admin"]).text]
    blob = json.dumps([e.payload for e in db_session.scalars(select(SystemEvent))], default=str) + caplog.text + "".join(reads)
    blob += json.dumps(r.json()["plan"])
    assert CANARY not in blob
