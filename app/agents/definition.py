"""Declarative agent definition.

    Agent = capabilities (what it is for) + tool access rules (which tools it may ever name)
          + permission scope (the ceiling on what it may do, intersected with the user's own rights by the kernel)
          + risk ceiling (the riskiest tool it may use)

Validation is strict and fails closed. Agents can never be granted the permission namespaces that
govern the platform itself (approvals, members, connections, policy, audit, billing, workspace),
so an agent can never approve its own work or change who can do what.
"""
import re
from dataclasses import dataclass, field
from typing import FrozenSet, Iterable, List, Tuple

from app.agents.errors import InvalidAgentDefinitionError
from app.kernel.permissions import has_permission
from app.kernel.registry import PERMISSION_RE, TOOL_ID_RE, ToolDefinition, ToolRegistry
from app.models.enums import RiskLevel

AGENT_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
CAPABILITY_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){0,2}$")
_PREFIX_RE = CAPABILITY_RE                                   # same shape: 1-3 literal segments
FORBIDDEN_AGENT_NAMESPACES = frozenset({"approval", "member", "connection", "policy", "audit", "billing",
                                        "workspace", "agent"})
RISK_RANK = {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1, RiskLevel.HIGH: 2}
MAX_CAPABILITIES, MAX_TOOL_PATTERNS, MAX_SCOPE = 10, 20, 20


def _bad(msg: str) -> InvalidAgentDefinitionError:
    return InvalidAgentDefinitionError(msg)


def _validate_tool_pattern(pattern: str) -> None:
    """Exact tool id (e.g. system.ping) or '<literal prefix>.*' (e.g. aceden.task.*). Never a bare '*'."""
    if pattern.endswith(".*"):
        if not _PREFIX_RE.match(pattern[:-2]):
            raise _bad(f"Invalid tool pattern: {pattern!r}")
    elif not TOOL_ID_RE.match(pattern):
        raise _bad(f"Invalid tool pattern: {pattern!r}")


_WILDCARD_BASE_RE = re.compile(r"^[a-z][a-z0-9_]*(:[a-z][a-z0-9_]*)*$")


def _validate_scope_permission(perm: str) -> None:
    """'resource:action' or 'resource:*' (trailing wildcard only), never in a platform namespace."""
    if perm.endswith(":*"):
        if not _WILDCARD_BASE_RE.match(perm[:-2]):
            raise _bad(f"Invalid permission: {perm!r}")
    elif "*" in perm or not PERMISSION_RE.match(perm):
        raise _bad(f"Invalid permission: {perm!r}")
    namespace = perm.split(":", 1)[0]
    if namespace in FORBIDDEN_AGENT_NAMESPACES:
        raise _bad(f"Agents may not hold {namespace!r} permissions")


@dataclass(frozen=True)
class AgentDefinition:
    id: str
    name: str
    description: str
    capabilities: FrozenSet[str] = frozenset()
    tool_patterns: Tuple[str, ...] = ()
    scope_permissions: FrozenSet[str] = frozenset()
    max_risk: RiskLevel = RiskLevel.LOW

    def __post_init__(self) -> None:
        # Normalise whatever iterable was supplied into immutable, de-duplicated collections.
        object.__setattr__(self, "capabilities", frozenset(self.capabilities))
        object.__setattr__(self, "tool_patterns", tuple(dict.fromkeys(self.tool_patterns)))
        object.__setattr__(self, "scope_permissions", frozenset(self.scope_permissions))
        if not AGENT_ID_RE.match(self.id or ""):
            raise _bad(f"Invalid agent id: {self.id!r}")
        if not self.name.strip() or len(self.name) > 64:
            raise _bad("Agent name is required (max 64 chars)")
        if not self.description.strip() or len(self.description) > 300:
            raise _bad("Agent description is required (max 300 chars)")
        if not isinstance(self.max_risk, RiskLevel):
            raise _bad("max_risk must be a RiskLevel")
        if len(self.capabilities) > MAX_CAPABILITIES or len(self.tool_patterns) > MAX_TOOL_PATTERNS \
                or len(self.scope_permissions) > MAX_SCOPE:
            raise _bad("Too many capabilities, tool patterns or permissions")
        for cap in self.capabilities:
            if not CAPABILITY_RE.match(cap):
                raise _bad(f"Invalid capability: {cap!r}")
        for pattern in self.tool_patterns:
            _validate_tool_pattern(pattern)
        for perm in self.scope_permissions:
            _validate_scope_permission(perm)
        if self.tool_patterns and not self.scope_permissions:
            raise _bad("An agent with tools needs an explicit permission scope")

    # ------------------------------------------------------------------ rules
    def allows_tool_id(self, tool_id: str) -> bool:
        """Tool-access rule only (names). Permissions and risk are applied in effective_tools / the kernel."""
        for pattern in self.tool_patterns:
            if pattern.endswith(".*"):
                if tool_id.startswith(pattern[:-1]):          # keeps the '.': 'a.task.*' != 'a.tasks.x'
                    return True
            elif tool_id == pattern:
                return True
        return False

    def describe(self) -> dict:
        return {"id": self.id, "name": self.name, "description": self.description,
                "capabilities": sorted(self.capabilities), "max_risk": self.max_risk.value}


def effective_tools(agent: AgentDefinition, registry: ToolRegistry) -> List[ToolDefinition]:
    """Tools this agent can ever use: named by its rules AND covered by its scope AND within its risk ceiling.
    (The kernel additionally intersects with the acting user's permissions and workspace policy.)"""
    return [t for t in registry.list()
            if agent.allows_tool_id(t.id)
            and has_permission(agent.scope_permissions, t.required_permission)
            and RISK_RANK[t.risk_level] <= RISK_RANK[agent.max_risk]]
