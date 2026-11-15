"""Substep 11.6: Step 11 closing pass: every capability keeps the same safety shape; one end-to-end audited agent journey."""
import json
import pathlib
import re
from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.agents.context import agent_policy, agent_principal
from app.agents.definition import effective_tools
from app.agents.starter import INSIGHT_AGENT, OPS_AGENT
from app.capabilities.attention_tool import attention_tool_definition
from app.capabilities.changes_tool import changes_tool_definition
from app.capabilities.composite import new_slots
from app.capabilities.meetings_tool import meetings_tool_definition
from app.capabilities.opportunities_tool import opportunity_tool_definition
from app.kernel.errors import PolicyDeniedError
from app.kernel.policy import WorkspacePolicy
from app.kernel.service import ToolExecutionService
from app.models.enums import ExecutionStatus, RiskLevel
from app.models.kernel import Approval, SystemEvent, ToolExecution
from tests.test_attention import fake_registry, full
from tests.test_workspace_connectors import principal, public_dns, team  # noqa: F401

NOW = datetime(2026, 3, 9, 9, 0, 0, tzinfo=timezone.utc)
CANARY = "CANARY-step11-8841"
# tool id -> (permission, capability name on the insight agent, source module, endpoint)
COMPOSITES = {
    "insight.attention.read": ("insight:read", "insight.attention", "attention", "attention"),
    "sales.opportunity.list": ("sales:read", "sales.opportunities", "opportunities", "opportunities"),
    "insight.changes.read": ("insight:read", "insight.changes", "changes", "changes"),
    "insight.meetings.read": ("insight:read", "insight.meetings", "meetings", "meetings"),
}
BUILDERS = [attention_tool_definition, opportunity_tool_definition, changes_tool_definition, meetings_tool_definition]
SECRETISH = re.compile(r"secret|token|password|credential|api_?key|authorization", re.I)


def build_all(db, handlers, slots=None):
    """The real composite tool definitions on one shared cap, over canned handlers with the real read schemas."""
    reg = fake_registry(handlers)
    factory = sessionmaker(bind=db.get_bind(), autoflush=False, expire_on_commit=False)
    slots = slots or new_slots()
    for build in BUILDERS:
        reg.register(build(factory, lambda: reg, clock=lambda: NOW, slots=slots))
    return reg


def run_as_agent(db, reg, who, ws, tool_id, agent=INSIGHT_AGENT):
    user = principal(db, who, ws["id"])
    kernel = ToolExecutionService(db, reg, policy_provider=lambda w: agent_policy(WorkspacePolicy(), agent, reg))
    return kernel.submit(agent_principal(user, agent), tool_id, {})


# ------------------------------------------------------------------ one safety shape for every capability tool
def test_every_capability_tool_has_the_same_safety_shape(client):
    app_tools = client.app.state.tool_registry
    for tool_id, (permission, _cap, _mod, _ep) in COMPOSITES.items():
        t = app_tools.get(tool_id)
        assert (t.risk_level, t.required_permission, t.approval_required, t.max_retries) == (RiskLevel.LOW, permission, False, 0), tool_id
        assert t.input_schema.model_config.get("extra") == "forbid" and not t.input_schema.model_fields, tool_id
        assert 0 < t.timeout_seconds <= 120, tool_id
        assert not SECRETISH.search(json.dumps(t.output_schema.model_json_schema())), tool_id


def test_every_capability_is_owned_by_the_insight_agent_and_no_other_starter_agent(client):
    app_tools = client.app.state.tool_registry
    agent = client.app.state.agent_registry.get("insight_agent")
    visible = {t.id for t in effective_tools(agent, app_tools)}
    for tool_id, (_perm, cap, _mod, _ep) in COMPOSITES.items():
        assert agent.allows_tool_id(tool_id) and cap in agent.capabilities and tool_id in visible, tool_id
        assert not OPS_AGENT.allows_tool_id(tool_id), tool_id
    assert {"email:read", "calendar:read", "crm:read", "project:read"} <= INSIGHT_AGENT.scope_permissions
    for direct in ("email.message.list", "calendar.event.list", "crm.lead.list", "project.task.list"):
        assert not INSIGHT_AGENT.allows_tool_id(direct), direct       # scope lets the composite read; the agent still cannot name the reads


def test_capability_modules_have_no_connector_or_write_access_and_share_one_cap():
    runtime = pathlib.Path("app/runtime.py").read_text()
    assert runtime.count("new_slots(") == 1
    for tool_id, (_p, _c, mod, _e) in COMPOSITES.items():
        for name in (mod, f"{mod}_tool"):
            text = pathlib.Path(f"app/capabilities/{name}.py").read_text()
            assert "app.connectors" not in text and "import httpx" not in text, name
            for banned in ('"email.send"', '"email.draft"', '"crm.lead.create"', '"chat.message.post"', '"calendar.meeting.create"',
                           "execute_approved", "allow_write", "get_settings"):
                assert banned not in text, (name, banned)
    assert len(re.findall(r"_tool_definition\(sessions, lambda: registry, slots=slots, policy_provider=policy\)", runtime)) == len(COMPOSITES)


def test_every_capability_has_an_endpoint_that_calls_the_service_with_the_callers_principal_only():
    text = pathlib.Path("app/api/capabilities.py").read_text()
    for tool_id, (_p, _c, _m, ep) in COMPOSITES.items():
        assert f'@router.post("/{ep}"' in text, ep
    assert text.count("ctx.principal()") == len(COMPOSITES) and "connectors" not in text and "execute_approved" not in text


# ------------------------------------------------------------------ the shared cap, across all four
def test_all_four_tools_are_refused_while_the_shared_cap_is_held_and_every_slot_is_released(client, team, db_session):
    hs, ws = team
    slots = new_slots(1)
    reg = build_all(db_session, full(), slots=slots)
    assert slots.acquire(blocking=False)                                   # another composite holds the only slot
    for tool_id in COMPOSITES:
        ex = run_as_agent(db_session, reg, "admin@x.com", ws, tool_id)
        assert ex.status == ExecutionStatus.FAILED, tool_id
        assert "DigestBusyError" in json.dumps({"e": ex.error}), tool_id
    nested = db_session.scalars(select(ToolExecution).where(ToolExecution.tool_id == "calendar.event.list")).all()
    assert nested == []                                                    # refused before any nested read
    slots.release()
    for tool_id in COMPOSITES:                                             # each one works once and gives the slot back
        assert run_as_agent(db_session, reg, "admin@x.com", ws, tool_id).status == ExecutionStatus.SUCCEEDED, tool_id
    assert slots.acquire(blocking=False)
    slots.release()


# ------------------------------------------------------------------ who may call what
def test_members_and_other_agents_are_denied_every_tool_and_nothing_is_read(client, team, db_session):
    hs, ws = team
    reg = build_all(db_session, full())
    before = len(db_session.scalars(select(ToolExecution)).all())
    for tool_id in COMPOSITES:
        with pytest.raises(PolicyDeniedError):
            run_as_agent(db_session, reg, "admin@x.com", ws, tool_id, agent=OPS_AGENT)
        with pytest.raises(PolicyDeniedError):
            ToolExecutionService(db_session, reg).submit(principal(db_session, "member@x.com", ws["id"]), tool_id, {})
    assert len(db_session.scalars(select(ToolExecution)).all()) == before


def test_endpoints_are_member_safe_and_workspace_scoped_for_every_capability(client, team):
    hs, ws = team
    client.app.state.tool_registry = fake_registry(full())
    for _tool_id, (_p, _c, _m, ep) in COMPOSITES.items():
        url = f"/workspaces/{ws['id']}/capabilities/{ep}"
        m = client.post(url, headers=hs["member"])
        body = m.json()
        states = {s["status"] for s in body["sources"]} if "sources" in body else {body["status"]}       # opportunities has one source
        assert m.status_code == 200 and "not_permitted" in states and body["partial"] is True, ep
        assert not any(body.get(k) for k in ("items", "meetings")), ep                                      # nothing was read for a member
        assert client.post(url, headers=hs["outsider"]).status_code in (403, 404), ep
        assert client.post(url).status_code == 401 and client.get(url, headers=hs["admin"]).status_code == 405, ep


# ------------------------------------------------------------------ end to end: agent call to audit trail
def test_journey_agent_asks_all_four_questions_and_the_audit_trail_is_complete_and_content_free(client, team, db_session):
    hs, ws = team
    handlers = full()
    handlers["project.task.list"] = lambda ctx, d: {"tasks": [{"id": "1", "name": f"Overdue {CANARY}", "completed": False, "due_on": "2026-03-01"}]}
    handlers["email.message.list"] = lambda ctx, d: {"messages": [{"id": f"{1:016x}", "subject": f"Mail {CANARY}"}]}
    reg = build_all(db_session, handlers)
    top = {}
    for tool_id in COMPOSITES:                                                              # 1 ask, 2 plan, 3 permission, 4 execute
        ex = run_as_agent(db_session, reg, "admin@x.com", ws, tool_id)
        assert ex.status == ExecutionStatus.SUCCEEDED and ex.agent == "insight_agent", tool_id
        top[tool_id] = ex
    assert CANARY in json.dumps(top["insight.attention.read"].output)                       # 5 the result carries the text, flagged as data
    assert all(i["external_text"] for i in top["insight.attention.read"].output["items"] if i["source"] in ("project", "email"))
    rows = db_session.scalars(select(ToolExecution).where(ToolExecution.workspace_id == ws["id"])).all()
    assert {r.requested_by for r in rows} == {top["insight.attention.read"].requested_by}   # 6 every nested read is attributed to the same user
    assert {r.agent for r in rows} == {"insight_agent"} and {r.risk_level.value for r in rows} == {"low"}
    assert {r.status.value for r in rows} == {"succeeded"} and db_session.scalars(select(Approval)).all() == []
    nested = {r.tool_id for r in rows} - set(COMPOSITES)
    assert nested <= {"calendar.event.list", "project.project.list", "project.task.list", "crm.lead.list", "email.message.list"}
    for ex in top.values():                                                                 # 7 an ordered trail per execution
        events = db_session.scalars(select(SystemEvent).where(SystemEvent.execution_id == ex.id).order_by(SystemEvent.created_at)).all()
        kinds = [e.event_type for e in events]
        assert kinds[0] == "execution.created" and "execution.started" in kinds and kinds[-1] in ("execution.succeeded", "execution.executed"), kinds
        assert kinds.index("execution.started") < len(kinds) - 1
    blob = json.dumps([e.payload for e in db_session.scalars(select(SystemEvent)).all()])
    assert CANARY not in blob                                                               # 8 the audit trail holds no remote text


def test_journey_a_removed_member_gets_nothing_from_any_capability(client, team, db_session):
    from app.models.identity import Membership
    hs, ws = team
    reg = build_all(db_session, full())
    user = principal(db_session, "admin@x.com", ws["id"])
    for m in db_session.scalars(select(Membership).where(Membership.user_id == user.user_id, Membership.workspace_id == ws["id"])).all():
        db_session.delete(m)
    db_session.commit()
    for tool_id in COMPOSITES:
        ex = ToolExecutionService(db_session, reg, policy_provider=lambda w: agent_policy(WorkspacePolicy(), INSIGHT_AGENT, reg)).submit(
            agent_principal(user, INSIGHT_AGENT), tool_id, {})
        assert ex.status == ExecutionStatus.FAILED and "DigestIdentityError" in json.dumps({"e": ex.error}), tool_id
    assert [r.tool_id for r in db_session.scalars(select(ToolExecution)).all() if r.tool_id not in COMPOSITES] == []
