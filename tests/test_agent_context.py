"""Step 6.2: agent principals, per-agent tool-access enforcement at the kernel, agent-scoped AI chain."""
import dataclasses
import json

import pytest
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select

from app.agents.context import AgentContextError, agent_policy, agent_principal, build_agent_context
from app.agents.definition import AgentDefinition
from app.agents.errors import AgentNotFoundError
from app.agents.registry import AgentRegistry
from app.config import Settings
from app.intelligence.planning import PlanStatus, ProposalMismatchError, ToolCallPlanner, submit_proposal
from app.intelligence.understanding import RequestUnderstandingService
from app.kernel.approvals import ApprovalService
from app.kernel.builtin_tools import build_default_registry
from app.kernel.errors import ApprovalPermissionError, PolicyDeniedError
from app.kernel.permissions import Principal
from app.kernel.policy import WorkspacePolicy
from app.kernel.registry import ToolDefinition
from app.llm.fake import FakeProvider
from app.llm.service import LLMService
from app.models import Approval, ExecutionStatus, RiskLevel, SystemEvent, ToolExecution

pytestmark = pytest.mark.usefixtures("seed_workspaces")
CALLS = []


class ListIn(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UpdIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: int


class Out(BaseModel):
    ok: bool = True


def mk(id, perm, risk, schema, tag):
    return ToolDefinition(id=id, description=f"Does {id}", input_schema=schema, output_schema=Out,
                          required_permission=perm, risk_level=risk,
                          handler=lambda c, d: CALLS.append((tag, c.workspace_id, c.agent)) or {"ok": True})


def build_tools():
    CALLS.clear()
    r = build_default_registry()                                                    # system.ping (system:read)
    r.register(mk("aceden.task.list", "task:read", RiskLevel.LOW, ListIn, "list"))
    r.register(mk("aceden.task.update", "task:write", RiskLevel.MEDIUM, UpdIn, "update"))
    r.register(mk("aceden.customer.read", "customer:read", RiskLevel.LOW, ListIn, "cread"))
    r.register(mk("aceden.customer.delete", "customer:delete", RiskLevel.HIGH, UpdIn, "delete"))
    return r


@pytest.fixture
def tools():
    return build_tools()


OPS = AgentDefinition(id="ops_agent", name="Ops", description="Reads operations data.", capabilities={"ops.monitor"},
                      tool_patterns=["system.ping", "aceden.task.list"], scope_permissions={"system:read", "task:read"})
WRITER = AgentDefinition(id="task_writer", name="Writer", description="Updates tasks.", capabilities={"task.write"},
                         tool_patterns=["aceden.task.*"], scope_permissions={"task:*"}, max_risk=RiskLevel.MEDIUM)
COORD = AgentDefinition(id="coordinator", name="Coordinator", description="Plans only.")


@pytest.fixture
def agents(tools):
    reg = AgentRegistry(tools)
    for a in (OPS, WRITER, COORD):
        reg.register(a)
    return reg


def user(perms=("*",), ws="w1", uid="u1"):
    return Principal(user_id=uid, workspace_id=ws, permissions=frozenset(perms))


def ctx(agents, tools, perms=("*",), agent="ops_agent", ws="w1", base=None):
    return build_agent_context(user(perms, ws), agent, agents, tools, base_policy_provider=(lambda w: base) if base else None)


# ------------------------------------------------------------------ principal
def test_agent_principal_keeps_user_and_workspace_and_adds_scope():
    p = agent_principal(user(("task:read", "system:read")), OPS)
    assert (p.user_id, p.workspace_id, p.agent) == ("u1", "w1", "ops_agent")
    assert p.permissions == frozenset({"task:read", "system:read"}) and p.agent_scope == OPS.scope_permissions


def test_agent_cannot_nest_or_be_built_for_unknown_ids(agents, tools):
    with pytest.raises(AgentContextError):
        agent_principal(agent_principal(user(), OPS), WRITER)
    with pytest.raises(AgentNotFoundError):
        build_agent_context(user(), "ghost", agents, tools)


def test_agent_with_no_scope_can_do_nothing():
    p = agent_principal(user(), COORD)
    assert p.agent_scope == frozenset() and not p.can("task:read") and not p.can("system:read")


@pytest.mark.parametrize("user_perms,agent,perm,allowed", [
    (("task:read", "task:write"), OPS, "task:write", False),         # user may, agent's scope may not
    (("task:read",), WRITER, "task:write", False),                   # agent's scope may, user may not
    (("task:read", "task:write"), WRITER, "task:write", True),
    (("*",), OPS, "customer:delete", False),                         # owner-level user, narrow agent
    (("*",), OPS, "task:read", True),
    ((), WRITER, "task:read", False),
])
def test_kernel_rights_are_the_intersection_of_user_and_agent(user_perms, agent, perm, allowed):
    assert agent_principal(user(user_perms), agent).can(perm) is allowed


# ------------------------------------------------------------------ policy: tool access rules
def test_policy_disables_every_tool_outside_the_agents_rules(tools):
    pol = agent_policy(WorkspacePolicy(), OPS, tools)
    assert pol.disabled_tools == {"aceden.task.update", "aceden.customer.read", "aceden.customer.delete"}


def test_policy_preserves_workspace_settings(tools):
    base = WorkspacePolicy(disabled_tools=frozenset({"aceden.task.list"}), approval_required_tools=frozenset({"system.ping"}),
                           auto_execute_max_risk=RiskLevel.MEDIUM)
    pol = agent_policy(base, OPS, tools)
    assert "aceden.task.list" in pol.disabled_tools                   # workspace's own denials kept
    assert pol.approval_required_tools == {"system.ping"} and pol.auto_execute_max_risk == RiskLevel.MEDIUM


def test_risk_ceiling_disables_riskier_tools_even_if_named(tools):
    broad = AgentDefinition(id="broad", name="B", description="d", tool_patterns=["aceden.*"],
                            scope_permissions={"task:*", "customer:*"}, max_risk=RiskLevel.MEDIUM)
    pol = agent_policy(WorkspacePolicy(), broad, tools)
    assert "aceden.customer.delete" in pol.disabled_tools and "aceden.task.update" not in pol.disabled_tools


def test_tools_registered_after_the_agent_was_built_are_denied_by_default(agents, tools, db_session):
    c = ctx(agents, tools)
    tools.register(mk("aceden.task.archive", "task:read", RiskLevel.LOW, ListIn, "archive"))   # new tool, matches no rule
    assert "aceden.task.archive" in c.policy("w1").disabled_tools
    with pytest.raises(PolicyDeniedError):
        c.execution_service(db_session).submit(c.principal, "aceden.task.archive", {})
    assert CALLS == []


# ------------------------------------------------------------------ kernel enforcement
def test_agent_runs_an_allowed_tool_and_the_execution_is_attributed(agents, tools, db_session):
    c = ctx(agents, tools)
    ex = c.execution_service(db_session).submit(c.principal, "aceden.task.list", {})
    assert ex.status == ExecutionStatus.SUCCEEDED and ex.agent == "ops_agent" and ex.requested_by == "u1"
    assert CALLS == [("list", "w1", "ops_agent")]
    created = db_session.scalars(select(SystemEvent).where(SystemEvent.event_type == "execution.created")).one()
    assert created.payload["agent"] == "ops_agent"


@pytest.mark.parametrize("tool_id,args", [("aceden.task.update", {"task_id": 1}), ("aceden.customer.read", {}),
                                          ("aceden.customer.delete", {"task_id": 1})])
def test_out_of_rules_tools_are_denied_even_for_an_owner_user(agents, tools, db_session, tool_id, args):
    c = ctx(agents, tools, perms=("*",))
    with pytest.raises(PolicyDeniedError):
        c.execution_service(db_session).submit(c.principal, tool_id, args)
    assert CALLS == [] and db_session.scalar(select(func.count()).select_from(ToolExecution)) == 0
    # the same owner acting directly (no agent) CAN use those tools: the restriction is the agent's, not the user's
    assert ctx(agents, tools).user_principal.can("customer:read")


def test_in_rules_tool_beyond_the_scope_is_denied(agents, tools, db_session):
    narrow = AgentDefinition(id="narrow", name="N", description="d", tool_patterns=["aceden.task.list", "system.ping"],
                             scope_permissions={"task:read", "system:read"})
    reg = AgentRegistry(tools)
    reg.register(narrow)
    c = build_agent_context(user(("task:read", "system:read")), "narrow", reg, tools)
    assert c.execution_service(db_session).submit(c.principal, "system.ping", {}).status == ExecutionStatus.SUCCEEDED
    viewer_c = build_agent_context(user(("task:read",)), "narrow", reg, tools)          # user lacks system:read
    with pytest.raises(PolicyDeniedError):
        viewer_c.execution_service(db_session).submit(viewer_c.principal, "system.ping", {})


def test_medium_risk_tool_for_a_writer_agent_still_needs_human_approval(agents, tools, db_session):
    c = ctx(agents, tools, agent="task_writer")
    svc = c.execution_service(db_session)
    ex = svc.submit(c.principal, "aceden.task.update", {"task_id": 5})
    assert ex.status == ExecutionStatus.AWAITING_APPROVAL and CALLS == []
    approval = db_session.scalar(select(Approval).where(Approval.execution_id == ex.id))
    with pytest.raises(ApprovalPermissionError):                                          # the agent can't approve itself
        ApprovalService(db_session).decide(approval.id, c.principal, approve=True)
    with pytest.raises(ApprovalPermissionError):                                          # nor can the requesting user
        ApprovalService(db_session).decide(approval.id, c.user_principal, approve=True)
    ApprovalService(db_session).decide(approval.id, user(uid="u2"), approve=True)         # a different person can
    assert svc.execute_approved(c.principal, ex.id).status == ExecutionStatus.SUCCEEDED
    assert CALLS == [("update", "w1", "task_writer")]


def test_policy_change_after_approval_is_still_enforced_for_agents(agents, tools, db_session):
    c = ctx(agents, tools, agent="task_writer")
    ex = c.execution_service(db_session).submit(c.principal, "aceden.task.update", {"task_id": 5})
    approval = db_session.scalar(select(Approval).where(Approval.execution_id == ex.id))
    ApprovalService(db_session).decide(approval.id, user(uid="u2"), approve=True)
    off = dataclasses.replace(c, base_policy_provider=lambda w: WorkspacePolicy(disabled_tools=frozenset({"aceden.task.update"})))
    with pytest.raises(PolicyDeniedError):
        off.execution_service(db_session).execute_approved(off.principal, ex.id)
    assert CALLS == []


def test_coordinator_with_no_tools_can_run_nothing(agents, tools, db_session):
    c = ctx(agents, tools, agent="coordinator")
    assert c.policy("w1").disabled_tools == {t.id for t in tools.list()}
    for tool_id, args in (("system.ping", {}), ("aceden.task.list", {})):
        with pytest.raises(PolicyDeniedError):
            c.execution_service(db_session).submit(c.principal, tool_id, args)


# ------------------------------------------------------------------ agent-scoped AI chain
def test_catalog_is_the_agents_view_not_the_users(agents, tools):
    assert [e.tool_id for e in ctx(agents, tools, agent="ops_agent").catalog()] == ["aceden.task.list", "system.ping"]
    assert [e.tool_id for e in ctx(agents, tools, agent="task_writer").catalog()] == ["aceden.task.list", "aceden.task.update"]
    assert ctx(agents, tools, agent="coordinator").catalog() == []
    direct = {e.tool_id for e in build_agent_context(user(), "ops_agent", agents, tools).catalog()}
    assert direct <= {t.id for t in tools.list()}


def _llm(db, script):
    fp = FakeProvider(script)
    return LLMService(db, fp, Settings(app_env="test", database_url="sqlite:///:memory:", _env_file=None), sleep=lambda s: None), fp


def test_understanding_and_planning_use_the_agents_restricted_view(agents, tools, db_session):
    c = ctx(agents, tools, agent="ops_agent")
    intent = json.dumps(dict(kind="tool_request", summary="s", candidate_tools=["aceden.task.update", "aceden.task.list"], confidence=0.9))
    plan = json.dumps(dict(tool_id="aceden.task.list", arguments={}, rationale="r", confidence=0.9, missing_information=[]))
    llm, fp = _llm(db_session, [intent, plan])
    resolved = RequestUnderstandingService(llm, tools, policy_provider=c.policy).understand(c.principal, "list tasks")
    assert [t.tool_id for t in resolved.candidate_tools] == ["aceden.task.list"] and "unknown_tools_dropped" in resolved.warnings
    system = "\n".join(m.content for m in fp.requests[0].messages if m.role.value == "system")
    assert "aceden.task.update" not in system and "aceden.customer.delete" not in system
    result = ToolCallPlanner(llm, tools, policy_provider=c.policy).plan(c.principal, "list tasks", resolved)
    assert result.status == PlanStatus.PROPOSED and result.proposal.agent == "ops_agent"


def test_planner_refuses_a_tool_the_agent_may_not_use_even_if_the_intent_names_it(agents, tools, db_session):
    from app.intelligence.understanding import CandidateTool, IntentKind, ResolvedIntent
    c = ctx(agents, tools, agent="ops_agent")
    forged = ResolvedIntent(kind=IntentKind.TOOL_REQUEST, summary="s", confidence=0.9, needs_clarification=False,
                            candidate_tools=[CandidateTool(tool_id="aceden.customer.delete", description="d", risk_level="high", requires_approval=True)])
    llm, fp = _llm(db_session, ["{}"])
    r = ToolCallPlanner(llm, tools, policy_provider=c.policy).plan(c.principal, "x", forged)
    assert r.reason == "no_tools_available" and fp.requests == []


def _proposal(agents, tools, db_session, agent="ops_agent", ws="w1"):
    c = ctx(agents, tools, agent=agent, ws=ws)
    intent = json.dumps(dict(kind="tool_request", summary="s", candidate_tools=["aceden.task.list"], confidence=0.9))
    plan = json.dumps(dict(tool_id="aceden.task.list", arguments={}, rationale="r", confidence=0.9, missing_information=[]))
    llm, _ = _llm(db_session, [intent, plan])
    resolved = RequestUnderstandingService(llm, tools, policy_provider=c.policy).understand(c.principal, "list")
    return c, ToolCallPlanner(llm, tools, policy_provider=c.policy).plan(c.principal, "list", resolved).proposal


def test_agent_proposals_are_bound_to_that_agent(agents, tools, db_session):
    c, proposal = _proposal(agents, tools, db_session)
    svc = c.execution_service(db_session)
    with pytest.raises(ProposalMismatchError):                          # as the plain user: refused
        submit_proposal(svc, c.user_principal, proposal)
    other = ctx(agents, tools, agent="task_writer")
    with pytest.raises(ProposalMismatchError):                          # as a different agent: refused
        submit_proposal(other.execution_service(db_session), other.principal, proposal)
    assert CALLS == []
    assert submit_proposal(svc, c.principal, proposal).status == ExecutionStatus.SUCCEEDED
    assert CALLS == [("list", "w1", "ops_agent")]


def test_agent_proposal_cannot_cross_workspaces(agents, tools, db_session):
    c, proposal = _proposal(agents, tools, db_session)
    foreign = ctx(agents, tools, agent="ops_agent", ws="w2")
    with pytest.raises(ProposalMismatchError):
        submit_proposal(foreign.execution_service(db_session), foreign.principal, proposal)
    assert CALLS == []


def test_ai_audit_events_name_the_agent_only_when_one_acted(agents, tools, db_session):
    _proposal(agents, tools, db_session)
    evs = {e.event_type: e.payload for e in db_session.scalars(select(SystemEvent))}
    assert evs["intent.resolved"]["agent"] == "ops_agent" and evs["plan.proposed"]["agent"] == "ops_agent"
