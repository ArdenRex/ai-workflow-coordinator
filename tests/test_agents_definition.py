"""Step 6.1: agent definitions, validation, registry."""
import dataclasses

import pytest
from pydantic import BaseModel, ConfigDict

from app.agents.definition import FORBIDDEN_AGENT_NAMESPACES, AgentDefinition, effective_tools
from app.agents.errors import (AgentNotFoundError, DuplicateAgentError, InvalidAgentDefinitionError,
                               UnknownToolPatternError)
from app.agents.registry import AgentRegistry
from app.kernel.registry import ToolDefinition, ToolRegistry
from app.models.enums import RiskLevel


class In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Out(BaseModel):
    ok: bool = True


def tool(id, perm, risk=RiskLevel.LOW):
    return ToolDefinition(id=id, description=f"Does {id}", input_schema=In, output_schema=Out,
                          required_permission=perm, risk_level=risk, handler=lambda c, d: {})


@pytest.fixture
def tools():
    r = ToolRegistry()
    for t in (tool("system.ping", "system:read"), tool("aceden.task.list", "task:read"),
              tool("aceden.task.get", "task:read"), tool("aceden.task.update", "task:write", RiskLevel.MEDIUM),
              tool("aceden.customer.delete", "customer:delete", RiskLevel.HIGH),
              tool("aceden.tasks.export", "task:read")):
        r.register(t)
    return r


def agent(**over):
    base = dict(id="ops_agent", name="Operations", description="Watches operations.",
                capabilities={"ops.monitor"}, tool_patterns=["system.ping", "aceden.task.*"],
                scope_permissions={"system:read", "task:read"})
    return AgentDefinition(**{**base, **over})


# ------------------------------------------------------------------ validity
def test_valid_definition_is_normalised_and_immutable():
    a = agent(capabilities=["ops.monitor", "ops.monitor"], tool_patterns=["system.ping", "system.ping"],
              scope_permissions=["task:read", "task:read"])
    assert a.capabilities == frozenset({"ops.monitor"}) and a.tool_patterns == ("system.ping",)
    assert a.scope_permissions == frozenset({"task:read"}) and a.max_risk == RiskLevel.LOW
    with pytest.raises(dataclasses.FrozenInstanceError):
        a.id = "other"


def test_agent_without_tools_is_allowed():
    a = agent(id="coordinator", tool_patterns=[], scope_permissions=[])
    assert a.tool_patterns == () and a.describe()["id"] == "coordinator"


@pytest.mark.parametrize("bad_id", ["", "A", "1agent", "ab cd", "x", "a" * 33, "agent-one", "agent.one", "../x"])
def test_bad_ids_rejected(bad_id):
    with pytest.raises(InvalidAgentDefinitionError):
        agent(id=bad_id)


@pytest.mark.parametrize("field,value", [("name", " "), ("name", "x" * 65), ("description", ""),
                                         ("description", "x" * 301), ("max_risk", "low")])
def test_text_and_risk_fields_validated(field, value):
    with pytest.raises(InvalidAgentDefinitionError):
        agent(**{field: value})


@pytest.mark.parametrize("cap", ["", "Ops", "ops monitor", "ops.", ".ops", "a.b.c.d", "ops-monitor", "*"])
def test_bad_capabilities_rejected(cap):
    with pytest.raises(InvalidAgentDefinitionError):
        agent(capabilities={cap})


@pytest.mark.parametrize("pattern", ["*", "*.*", "*.read", "aceden", "aceden.", "Aceden.task.list", "aceden.*.list",
                                     "aceden.task.*.x", "aceden task", "aceden.**", ".*", "a.b.c.d.e", "aceden.task.l*"])
def test_bad_tool_patterns_rejected(pattern):
    with pytest.raises(InvalidAgentDefinitionError):
        agent(tool_patterns=[pattern])


@pytest.mark.parametrize("pattern", ["system.ping", "aceden.task.list", "aceden.*", "aceden.task.*"])
def test_good_tool_patterns_accepted(pattern):
    assert agent(tool_patterns=[pattern]).tool_patterns == (pattern,)


@pytest.mark.parametrize("perm", ["*", "approval:decide", "approval:*", "member:manage", "member:*", "connection:write",
                                  "connection:*", "policy:*", "audit:read", "billing:manage", "workspace:read",
                                  "workspace:update", "agent:run", "task:wr*", "task:*:*", "Task:read", "task", ""])
def test_dangerous_or_malformed_permissions_rejected(perm):
    with pytest.raises(InvalidAgentDefinitionError):
        agent(scope_permissions={perm})


def test_every_platform_namespace_is_blocked_for_agents():
    for ns in FORBIDDEN_AGENT_NAMESPACES:
        for form in (f"{ns}:read", f"{ns}:*"):
            with pytest.raises(InvalidAgentDefinitionError):
                agent(scope_permissions={form})


@pytest.mark.parametrize("perm", ["task:read", "task:*", "customer:read", "system:read"])
def test_ordinary_permissions_accepted(perm):
    assert agent(scope_permissions={perm}).scope_permissions == frozenset({perm})


def test_agent_with_tools_must_declare_a_scope():
    with pytest.raises(InvalidAgentDefinitionError):
        agent(scope_permissions=set())


def test_collection_size_limits():
    with pytest.raises(InvalidAgentDefinitionError):
        agent(capabilities={f"cap.n{i}" for i in range(11)})
    with pytest.raises(InvalidAgentDefinitionError):
        agent(tool_patterns=[f"aceden.t{i}.list" for i in range(21)])
    with pytest.raises(InvalidAgentDefinitionError):
        agent(scope_permissions={f"res{i}:read" for i in range(21)})


# ------------------------------------------------------------------ tool access rules
def test_pattern_matching_semantics():
    a = agent(tool_patterns=["system.ping", "aceden.task.*"])
    assert a.allows_tool_id("system.ping") and a.allows_tool_id("aceden.task.list") and a.allows_tool_id("aceden.task.x.y")
    assert not a.allows_tool_id("aceden.tasks.export")          # sibling prefix is not a match
    assert not a.allows_tool_id("aceden.task")                  # the namespace itself is not a tool
    assert not a.allows_tool_id("system.pinger") and not a.allows_tool_id("aceden.customer.delete")
    assert not agent(tool_patterns=[]).allows_tool_id("system.ping")


def test_effective_tools_apply_names_scope_and_risk(tools):
    ids = lambda a: [t.id for t in effective_tools(a, tools)]
    assert ids(agent()) == ["aceden.task.get", "aceden.task.list", "system.ping"]
    narrow = agent(scope_permissions={"task:read"})                     # scope lacks system:read
    assert ids(narrow) == ["aceden.task.get", "aceden.task.list"]
    writer = agent(scope_permissions={"task:*", "system:read"}, max_risk=RiskLevel.MEDIUM)
    assert "aceden.task.update" in ids(writer)
    assert "aceden.task.update" not in ids(agent(scope_permissions={"task:*", "system:read"}))   # risk ceiling LOW
    broad = agent(tool_patterns=["aceden.*"], scope_permissions={"task:*", "customer:*"}, max_risk=RiskLevel.MEDIUM)
    assert "aceden.customer.delete" not in ids(broad)                    # HIGH is above the ceiling


# ------------------------------------------------------------------ registry
def test_registry_register_get_list_find(tools):
    reg = AgentRegistry(tools)
    reg.register(agent(id="b_agent", capabilities={"ops.monitor", "report.write"}))
    reg.register(agent(id="a_agent", capabilities={"ops.monitor"}))
    reg.register(agent(id="c_agent", capabilities={"other"}, tool_patterns=["system.ping"], scope_permissions={"system:read"}))
    assert [a.id for a in reg.list()] == ["a_agent", "b_agent", "c_agent"]
    assert [a.id for a in reg.find_by_capability("ops.monitor")] == ["a_agent", "b_agent"]
    assert reg.find_by_capability("missing") == [] and reg.has("a_agent") and not reg.has("zzz")
    assert reg.get("b_agent").id == "b_agent"


def test_registry_rejects_duplicates_and_unknown_agents(tools):
    reg = AgentRegistry(tools)
    reg.register(agent())
    with pytest.raises(DuplicateAgentError):
        reg.register(agent())
    with pytest.raises(AgentNotFoundError):
        reg.get("nobody")


def test_dead_tool_pattern_fails_at_registration(tools):
    reg = AgentRegistry(tools)
    for patterns in (["aceden.taks.*"], ["system.pong"], ["system.ping", "nothing.here.*"]):
        with pytest.raises(UnknownToolPatternError):
            reg.register(agent(tool_patterns=patterns))
    assert reg.list() == []


def test_agent_with_no_usable_tools_fails_at_registration(tools):
    reg = AgentRegistry(tools)
    with pytest.raises(InvalidAgentDefinitionError):                    # scope covers none of the named tools
        reg.register(agent(tool_patterns=["aceden.customer.delete"], scope_permissions={"task:read"}))
    with pytest.raises(InvalidAgentDefinitionError):                    # only HIGH tool named, ceiling LOW
        reg.register(agent(tool_patterns=["aceden.customer.delete"], scope_permissions={"customer:*"}))


def test_registry_without_tools_skips_cross_checks():
    reg = AgentRegistry()
    reg.register(agent(tool_patterns=["whatever.thing.*"]))
    assert reg.has("ops_agent")


def test_describe_never_exposes_permissions_or_patterns():
    d = agent().describe()
    assert set(d) == {"id", "name", "description", "capabilities", "max_risk"}
