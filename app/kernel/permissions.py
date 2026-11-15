"""Permission model: who is acting, and what they (and their agent) may do.

Roles/memberships arrive in Step 4; until then the permission set is supplied
by the caller. Both the user AND the acting agent must allow an action.
"""
from dataclasses import dataclass
from typing import FrozenSet, Optional


def permission_matches(granted: str, required: str) -> bool:
    """Exact match, trailing wildcard ('customer:*'), or global '*'."""
    if granted == required or granted == "*":
        return True
    if granted.endswith(":*"):
        return required.startswith(granted[:-1])  # keeps the ':' so 'cust:*' != 'customer:read'
    return False


def has_permission(granted: FrozenSet[str], required: str) -> bool:
    return any(permission_matches(g, required) for g in granted)


@dataclass(frozen=True)
class Principal:
    user_id: str
    workspace_id: str
    permissions: FrozenSet[str]
    agent: Optional[str] = None
    # If set, the agent may only use permissions matching these patterns,
    # even when the user holds more. None = no agent (direct user action).
    agent_scope: Optional[FrozenSet[str]] = None

    def __post_init__(self) -> None:
        if not self.user_id or not self.workspace_id:
            raise ValueError("Principal requires user_id and workspace_id")
        if self.agent and self.agent_scope is None:
            raise ValueError("An agent principal must declare an explicit agent_scope")

    def can(self, required: str) -> bool:
        if not has_permission(self.permissions, required):
            return False
        if self.agent is not None:
            return has_permission(self.agent_scope or frozenset(), required)
        return True
