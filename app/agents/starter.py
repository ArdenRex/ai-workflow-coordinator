"""Starter agents: a deliberately small set, all read-only (LOW risk ceiling).

More agents (Sales, Support, ...) arrive only when connectors and capabilities justify them. An agent is data;
it gains nothing here that the definition validation, the user's own permissions and the kernel do not allow.
"""
from app.agents.definition import AgentDefinition
from app.agents.registry import AgentRegistry
from app.kernel.registry import ToolRegistry
from app.models.enums import RiskLevel

OPS_AGENT = AgentDefinition(
    id="ops_agent", name="Operations Agent",
    description="Checks system health and reads operational task information. Read-only.",
    capabilities=frozenset({"operations.status", "operations.tasks"}),
    tool_patterns=("system.ping", "aceden.task.*"),
    scope_permissions=frozenset({"system:read", "task:read", "memory:read"}),
    max_risk=RiskLevel.LOW)

INSIGHT_AGENT = AgentDefinition(
    id="insight_agent", name="Business Insight Agent",
    description="Looks up task and pipeline information and summarises what requires attention, lists qualified sales "
                "opportunities and reports what changed this week, prepares tomorrow's meetings from connected systems. Read-only.",
    capabilities=frozenset({"intelligence.lookup", "insight.attention", "sales.opportunities",
                              "insight.changes", "insight.meetings"}),
    tool_patterns=("aceden.task.*", "insight.attention.read", "sales.opportunity.list",
                   "insight.changes.read", "insight.meetings.read"),
    # The composite tools (digest, opportunities, changes, meetings) read calendar, project, CRM and email through the kernel as this agent, so those read permissions are in
    # scope. Scope does not name tools: the agent can still only use the tools its patterns list.
    scope_permissions=frozenset({"task:read", "memory:read", "insight:read", "sales:read", "email:read", "calendar:read", "crm:read",
                                 "project:read"}),
    max_risk=RiskLevel.LOW)

STARTER_AGENTS = (OPS_AGENT, INSIGHT_AGENT)


def build_agent_registry(tools: ToolRegistry) -> AgentRegistry:
    """Validated against the tool registry, so a typo or dead pattern fails at startup, not at run time."""
    registry = AgentRegistry(tools)
    for agent in STARTER_AGENTS:
        registry.register(agent)
    return registry
