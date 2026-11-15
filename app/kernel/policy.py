"""Policy evaluation: allow / require approval / deny, with explicit reason codes.

Order is fixed and deny-first:
  1 workspace isolation  2 tool disabled  3 user permission  4 agent scope
  5 approval requirement (tool rule, workspace policy, risk ceiling)
Workspace policy can only TIGHTEN approval, never loosen it: a tool's own
approval requirement (and HIGH risk) cannot be waived.
"""
import enum
from dataclasses import dataclass, field
from typing import Dict, FrozenSet

from app.kernel.permissions import Principal, has_permission
from app.kernel.registry import ToolDefinition
from app.models.enums import RiskLevel

_RANK = {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1, RiskLevel.HIGH: 2}


class Outcome(str, enum.Enum):
    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"


ALLOWED_WINDOWS = (60, 3600, 86400)     # seconds: a minute, an hour, a day
MAX_EXECUTIONS_CEILING = 100_000


@dataclass(frozen=True)
class ExecutionLimit:
    """At most `max_executions` tool runs started in any `window_seconds` window, per workspace (12.3c). Only ever restricts."""
    max_executions: int
    window_seconds: int


MAX_ESCALATION_THRESHOLD = 1000
ROUTING_RISKS = ("medium", "high")      # risk levels whose approvals can be routed
ROUTING_TARGET = "owner"                # the only target: decisions need a permission only the OWNER role holds
OWNER_ONLY_PERMISSION = "owner:approve"  # not in any non-owner role in identity/roles.py; owner's "*" matches it


@dataclass(frozen=True)
class EscalationRule:
    """Once `threshold` failed runs plus denied attempts have happened in the last `window_seconds`, runs that would
    have executed unattended need approval instead (12.3d). Only ever tightens."""
    threshold: int
    window_seconds: int


@dataclass(frozen=True)
class WorkspacePolicy:
    disabled_tools: FrozenSet[str] = frozenset()
    approval_required_tools: FrozenSet[str] = frozenset()
    # Anything riskier than this needs approval (LOW => only reads run unattended).
    auto_execute_max_risk: RiskLevel = RiskLevel.LOW
    # Per-tool risk override (12.3a). TIGHTEN ONLY: the effective risk is the higher of the tool's own risk and the override.
    risk_overrides: Dict[str, RiskLevel] = field(default_factory=dict, hash=False)
    # Per-workspace execution cap (12.3c). None = no cap (baseline). Enforced by the kernel just before a tool would run.
    execution_limit: "ExecutionLimit | None" = None
    # Failure/denial escalation (12.3d). None = off (baseline). Evaluated by the kernel, which can see recent history.
    escalation: "EscalationRule | None" = None
    # Approval routing (12.3e): risk level -> "owner". Deciding an approval of that (effective) risk then also needs the owner-only permission.
    approval_routing: Dict[str, str] = field(default_factory=dict, hash=False)
    # Level 4 (12.4): tools a workspace lets run WITHOUT approval although their risk is above the automatic limit. The ONLY loosening in the
    # policy, so it is narrow: explicit tool ids, effective risk at most MEDIUM, and never over a tool's own approval requirement or an approval rule.
    auto_execute_tools: FrozenSet[str] = frozenset()


def effective_risk(tool: ToolDefinition, policy: "WorkspacePolicy | None" = None) -> RiskLevel:
    """The tool's own risk, raised (never lowered) by a workspace override."""
    override = (policy.risk_overrides if policy else {}).get(tool.id)
    if override is not None and _RANK[override] > _RANK[tool.risk_level]:
        return override
    return tool.risk_level


def extra_decider_permission(risk: "RiskLevel | str", policy: "WorkspacePolicy | None") -> "str | None":
    """Permission a decider needs IN ADDITION to approval:decide for an approval of this risk, or None. Only ever adds a requirement."""
    value = risk.value if isinstance(risk, RiskLevel) else str(risk)
    if policy and policy.approval_routing.get(value) == ROUTING_TARGET:
        return OWNER_ONLY_PERMISSION
    return None


@dataclass(frozen=True)
class PolicyDecision:
    outcome: Outcome
    reason_code: str
    message: str

    @property
    def allowed(self) -> bool:
        return self.outcome != Outcome.DENY


def _deny(code: str, msg: str) -> PolicyDecision:
    return PolicyDecision(Outcome.DENY, code, msg)


def evaluate(tool: ToolDefinition, principal: Principal, workspace_id: str,
             policy: WorkspacePolicy | None = None) -> PolicyDecision:
    policy = policy or WorkspacePolicy()

    if principal.workspace_id != workspace_id:
        return _deny("workspace_mismatch", "Action is outside the caller's workspace")
    if tool.id in policy.disabled_tools:
        return _deny("tool_disabled", "This tool is disabled for the workspace")
    if not has_permission(principal.permissions, tool.required_permission):
        return _deny("permission_denied", "Missing required permission")
    if not principal.can(tool.required_permission):
        return _deny("agent_scope_denied", "Agent is not permitted to use this tool")

    risk = effective_risk(tool, policy)
    if risk == RiskLevel.HIGH:
        if tool.risk_level != RiskLevel.HIGH:
            return PolicyDecision(Outcome.REQUIRE_APPROVAL, "workspace_risk_override", "Workspace risk override requires approval")
        return PolicyDecision(Outcome.REQUIRE_APPROVAL, "high_risk", "High-risk action needs approval")
    if tool.approval_required:
        return PolicyDecision(Outcome.REQUIRE_APPROVAL, "tool_requires_approval", "Tool requires approval")
    if tool.id in policy.approval_required_tools:
        return PolicyDecision(Outcome.REQUIRE_APPROVAL, "workspace_policy", "Workspace policy requires approval")
    if _RANK[risk] > _RANK[policy.auto_execute_max_risk] and not (tool.id in policy.auto_execute_tools and _RANK[risk] <= _RANK[RiskLevel.MEDIUM]):
        code = "risk_above_auto_limit" if risk == tool.risk_level else "workspace_risk_override"
        return PolicyDecision(Outcome.REQUIRE_APPROVAL, code,
                              "Risk exceeds the workspace's automatic-execution limit")
    return PolicyDecision(Outcome.ALLOW, "allowed", "Allowed")
