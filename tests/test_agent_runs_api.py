"""Substep 6.5: starter agents + the agent-run HTTP API."""
import json

import pytest
from sqlalchemy import func, select

from app.agents.definition import AgentDefinition
from app.agents.starter import STARTER_AGENTS, build_agent_registry
from app.kernel.approvals import ApprovalService
from app.kernel.builtin_tools import build_default_registry
from app.llm import registry as llm_registry
from app.llm.fake import FakeProvider
from app.models import Approval, ApprovalStatus, RiskLevel, SystemEvent, ToolExecution
from app.models.agents import AgentRun
from app.models.enums import AgentRunStatus as S
from tests.test_agent_context import CALLS, mk, UpdIn
from tests.test_workspace_connectors import principal
from tests.test_workspaces_api import mkws, signup

GOAL = "Check the status of my business system"


def intent_json(tool="system.ping"):
    return json.dumps(dict(kind="tool_request", summary="status", candidate_tools=[tool], confidence=0.95))


def plan_json(tool="system.ping", args=None):
    return json.dumps(dict(tool_id=tool, arguments=args or {}, rationale="because", confidence=0.9,
                           missing_information=[]))


@pytest.fixture
def rig(client, monkeypatch):
    script = []

    def build(settings, **kw):
        items = list(script)
        script.clear()
        return FakeProvider(items)
    monkeypatch.setitem(llm_registry.PROVIDERS, "fake", build)
    hs = {n: signup(client, f"{n}@x.com") for n in ("owner", "admin", "member", "member2", "viewer", "outsider")}
    ws = mkws(client, hs["owner"], "Acme")
    for n, role in (("admin", "admin"), ("member", "member"), ("member2", "member"), ("viewer", "viewer")):
        assert client.post(f"/workspaces/{ws['id']}/members", json={"email": f"{n}@x.com", "role": role},
                           headers=hs["owner"]).status_code == 201
    other = mkws(client, hs["outsider"], "Other Co")
    return client, hs, ws, other, script


def base(ws):
    return f"/workspaces/{ws['id']}/agents"


def start(client, h, ws, script, goal=GOAL, agent="ops_agent", ok=True, **extra):
    if ok:
        script.extend([intent_json(), plan_json()])
    return client.post(f"{base(ws)}/runs", json={"agent_id": agent, "goal": goal, **extra}, headers=h)


# ------------------------------------------------------------------ starter agents
def test_starter_agents_are_few_read_only_and_valid_against_the_real_tools(app):
    reg = build_agent_registry(app.state.tool_registry)
    assert [a.id for a in reg.list()] == ["insight_agent", "ops_agent"] and len(STARTER_AGENTS) == 2
    assert all(a.max_risk == RiskLevel.LOW for a in STARTER_AGENTS)
    assert app.state.agent_registry.has("ops_agent")


def test_a_dead_tool_pattern_fails_at_registration_not_at_run_time():
    from app.agents.errors import UnknownToolPatternError
    with pytest.raises(UnknownToolPatternError):
        build_agent_registry(build_default_registry())            # no aceden.* tools registered here


# ------------------------------------------------------------------ access
def test_every_route_requires_the_right_caller(rig):
    client, hs, ws, other, script = rig
    paths = [("get", base(ws)), ("get", f"{base(ws)}/runs"), ("get", f"{base(ws)}/runs/x"),
             ("post", f"{base(ws)}/runs/x/cancel"), ("post", f"{base(ws)}/runs/x/resume")]
    for verb, p in paths:
        call = getattr(client, verb)
        assert call(p).status_code == 401
        assert call(p, headers=hs["outsider"]).status_code == 404          # not a member: workspace is invisible
        assert call(p, headers=hs["viewer"]).status_code == 403            # viewers cannot use agents
    assert client.post(f"{base(ws)}/runs", json={"agent_id": "ops_agent", "goal": "x"}).status_code == 401
    assert start(client, hs["viewer"], ws, script, ok=False).status_code == 403
    assert start(client, hs["outsider"], ws, script, ok=False).status_code == 404


def test_list_agents_shows_only_descriptions(rig):
    client, hs, ws, *_ = rig
    r = client.get(base(ws), headers=hs["member"])
    assert r.status_code == 200 and {a["id"] for a in r.json()} == {"ops_agent", "insight_agent"}
    assert set(r.json()[0]) == {"id", "name", "description", "capabilities", "max_risk"}


# ------------------------------------------------------------------ start
def test_start_runs_through_the_kernel_and_the_response_is_content_free(rig, db_session):
    client, hs, ws, _, script = rig
    r = start(client, hs["member"], ws, script)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "succeeded" and body["result"]["outcome"] == "executed"
    assert body["agent_id"] == "ops_agent" and body["goal_chars"] == len(GOAL)
    assert "goal" not in body and "goal_digest" not in body and GOAL not in r.text
    ex = db_session.get(ToolExecution, body["result"]["execution_id"])
    assert ex.workspace_id == ws["id"] and ex.agent == "ops_agent"
    assert GOAL not in json.dumps([e.payload for e in db_session.scalars(select(SystemEvent))], default=str)


@pytest.mark.parametrize("payload", [
    {"agent_id": "nope_agent", "goal": GOAL},                       # unknown agent
    {"agent_id": "ops_agent", "goal": "   "},
    {"agent_id": "ops_agent", "goal": "x" * 4001},
    {"agent_id": "ops_agent", "goal": GOAL, "max_steps": 999},       # above any ceiling
    {"agent_id": "ops_agent", "goal": GOAL, "role": "owner"},        # unknown field
    {"agent_id": "ops_agent"},
])
def test_invalid_requests_are_422_and_create_nothing(rig, db_session, payload):
    client, hs, ws, _, script = rig
    assert client.post(f"{base(ws)}/runs", json=payload, headers=hs["member"]).status_code == 422
    assert db_session.scalar(select(func.count()).select_from(AgentRun)) == 0


def test_a_caller_can_ask_for_less_than_the_ceiling_never_more(rig, settings):
    client, hs, ws, _, script = rig
    r = start(client, hs["member"], ws, script, max_llm_calls=2, max_tool_calls=1)
    assert r.status_code == 201 and r.json()["max_llm_calls"] == 2
    assert r.json()["max_steps"] == settings.agent_run_max_steps


def test_a_tiny_budget_fails_the_run_with_a_fixed_code(rig):
    client, hs, ws, _, script = rig
    r = start(client, hs["member"], ws, script, max_llm_calls=1)
    assert r.status_code == 201 and r.json()["status"] == "failed" and r.json()["error_code"] == "limit_llm_calls"


def test_idempotent_replay_returns_the_same_run_and_runs_nothing_twice(rig, db_session):
    client, hs, ws, _, script = rig
    a = start(client, hs["member"], ws, script, idempotency_key="k-1").json()
    b = start(client, hs["member"], ws, script, ok=False, idempotency_key="k-1").json()
    assert a["id"] == b["id"] and b["status"] == "succeeded"
    assert db_session.scalar(select(func.count()).select_from(ToolExecution)) == 1
    assert start(client, hs["member"], ws, script, ok=False, goal="a different goal",
                 idempotency_key="k-1").status_code == 409
    assert start(client, hs["member2"], ws, script, ok=False, idempotency_key="k-1").status_code == 409


def test_no_usable_llm_means_a_generic_error_and_no_orphan_run(rig, db_session, monkeypatch):
    client, hs, ws, _, script = rig
    from app.llm.errors import LLMConfigError

    def boom(settings, **kw):
        raise LLMConfigError("secret-detail sk-123")
    monkeypatch.setitem(llm_registry.PROVIDERS, "fake", boom)
    r = client.post(f"{base(ws)}/runs", json={"agent_id": "ops_agent", "goal": GOAL}, headers=hs["member"])
    assert r.status_code == 502 and "sk-123" not in r.text and "secret-detail" not in r.text
    assert db_session.scalar(select(func.count()).select_from(AgentRun)) == 0


# ------------------------------------------------------------------ read / visibility
def test_runs_are_private_to_their_user_but_visible_to_admins(rig):
    client, hs, ws, other, script = rig
    run = start(client, hs["member"], ws, script).json()
    url = f"{base(ws)}/runs/{run['id']}"
    assert client.get(url, headers=hs["member"]).status_code == 200
    assert client.get(url, headers=hs["admin"]).status_code == 200
    assert client.get(url, headers=hs["owner"]).status_code == 200
    assert client.get(url, headers=hs["member2"]).status_code == 404         # another member: same as missing
    assert client.get(f"{base(ws)}/runs/does-not-exist", headers=hs["member2"]).status_code == 404
    assert [r["id"] for r in client.get(f"{base(ws)}/runs", headers=hs["member"]).json()] == [run["id"]]
    assert client.get(f"{base(ws)}/runs", headers=hs["member2"]).json() == []
    assert [r["id"] for r in client.get(f"{base(ws)}/runs", headers=hs["admin"]).json()] == [run["id"]]
    assert [r["id"] for r in client.get(f"{base(ws)}/runs?status=succeeded", headers=hs["member"]).json()] == [run["id"]]
    assert client.get(f"{base(ws)}/runs?status=failed", headers=hs["member"]).json() == []
    assert client.get(f"{base(ws)}/runs?limit=0", headers=hs["member"]).status_code == 422


def test_a_run_is_invisible_through_another_workspace(rig):
    client, hs, ws, other, script = rig
    run = start(client, hs["member"], ws, script).json()
    # the other workspace's owner, using THEIR workspace path, cannot see it; nor can anyone using a path they aren't in
    assert client.get(f"{base(other)}/runs/{run['id']}", headers=hs["outsider"]).status_code == 404
    assert client.get(f"{base(ws)}/runs/{run['id']}", headers=hs["outsider"]).status_code == 404
    assert client.get(f"{base(other)}/runs", headers=hs["outsider"]).json() == []


# ------------------------------------------------------------------ cancel
def queued(db, user_email, ws):
    from app.agents.runs import AgentRunService
    from app.config import Settings
    svc = AgentRunService(db, build_agent_registry(build_default_registry_with_aceden()), Settings(
        app_env="test", database_url="sqlite:///:memory:", _env_file=None))
    return svc.create(principal(db, user_email, ws["id"]), "ops_agent", GOAL)


def build_default_registry_with_aceden():
    from app.runtime import build_runtime
    from app.config import Settings
    return build_runtime(Settings(app_env="test", database_url="sqlite:///:memory:", _env_file=None))[0]


def test_cancel_rules(rig, db_session):
    client, hs, ws, _, script = rig
    r1 = queued(db_session, "member@x.com", ws)
    url = f"{base(ws)}/runs/{r1.id}/cancel"
    assert client.post(url, headers=hs["member2"]).status_code == 404         # not yours
    assert client.post(url, headers=hs["outsider"]).status_code == 404
    ok = client.post(url, headers=hs["member"])
    assert ok.status_code == 200 and ok.json()["status"] == "cancelled"
    assert client.post(url, headers=hs["member"]).json()["status"] == "cancelled"     # idempotent
    r2 = queued(db_session, "member@x.com", ws)
    assert client.post(f"{base(ws)}/runs/{r2.id}/cancel", headers=hs["admin"]).json()["status"] == "cancelled"
    done = start(client, hs["member"], ws, script).json()
    assert client.post(f"{base(ws)}/runs/{done['id']}/cancel", headers=hs["member"]).status_code == 409


# ------------------------------------------------------------------ approval + resume
@pytest.fixture
def writer(rig, app):
    """Add a MEDIUM-risk tool and an agent allowed to use it, to the running app's registries."""
    CALLS.clear()
    app.state.tool_registry.register(mk("notes.task.update", "task:write", RiskLevel.MEDIUM, UpdIn, "update"))
    app.state.agent_registry.register(AgentDefinition(
        id="task_writer", name="Writer", description="Updates tasks.", capabilities={"task.write"},
        tool_patterns=["notes.task.update"], scope_permissions={"task:write"}, max_risk=RiskLevel.MEDIUM))
    return rig


def test_medium_risk_run_waits_then_resumes_only_after_a_human_approves(writer, db_session):
    client, hs, ws, _, script = writer
    script.extend([intent_json("notes.task.update"), plan_json("notes.task.update", {"task_id": 5})])
    run = client.post(f"{base(ws)}/runs", json={"agent_id": "task_writer", "goal": "update task five"},
                      headers=hs["member"]).json()
    assert run["status"] == "waiting_approval" and run["pending_execution_id"] and CALLS == []
    url = f"{base(ws)}/runs/{run['id']}/resume"
    assert client.post(url, headers=hs["member"]).status_code == 409           # undecided
    assert client.post(url, headers=hs["member2"]).status_code == 404          # not their run
    assert client.post(url, headers=hs["admin"]).status_code == 403            # admin sees it, cannot drive it
    approval = db_session.scalar(select(Approval).where(Approval.execution_id == run["pending_execution_id"]))
    ApprovalService(db_session).decide(approval.id, principal(db_session, "owner@x.com", ws["id"]), approve=True)
    assert CALLS == []                                                           # approving alone runs nothing
    done = client.post(url, headers=hs["member"])
    assert done.status_code == 200 and done.json()["status"] == "succeeded" and len(CALLS) == 1
    assert client.post(url, headers=hs["member"]).status_code == 409           # cannot resume twice
    assert len(CALLS) == 1


def test_cancelling_over_http_withdraws_the_pending_approval(writer, db_session):
    client, hs, ws, _, script = writer
    script.extend([intent_json("notes.task.update"), plan_json("notes.task.update", {"task_id": 5})])
    run = client.post(f"{base(ws)}/runs", json={"agent_id": "task_writer", "goal": "update task five"},
                      headers=hs["member"]).json()
    assert client.post(f"{base(ws)}/runs/{run['id']}/cancel", headers=hs["admin"]).json()["status"] == "cancelled"
    approval = db_session.scalar(select(Approval).where(Approval.execution_id == run["pending_execution_id"]))
    assert approval.status == ApprovalStatus.REJECTED and CALLS == []


def test_the_agents_tool_rules_still_bind_over_http(rig, db_session):
    client, hs, ws, _, script = rig
    # insight_agent has no system.ping: the model asks for it and the kernel/policy refuses; nothing executes.
    script.extend([intent_json("system.ping"), plan_json("system.ping")])
    body = client.post(f"{base(ws)}/runs", json={"agent_id": "insight_agent", "goal": GOAL}, headers=hs["member"]).json()
    assert body["status"] in ("succeeded", "failed") and body["result"] != {"outcome": "executed", "tool_id": "system.ping"}
    assert db_session.scalar(select(func.count()).select_from(ToolExecution)) == 0
