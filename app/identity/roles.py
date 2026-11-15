"""Role -> permission mapping. This is the ONLY place a role becomes kernel permissions.

Safe default: permissions are allow-lists, and any permission not listed here (e.g. a new
tool's) is held only by OWNER ('*') until it is deliberately assigned to other roles.
"""
from typing import FrozenSet

from app.models.enums import Role

ROLE_RANK = {Role.VIEWER: 0, Role.MEMBER: 1, Role.ADMIN: 2, Role.OWNER: 3}

_VIEWER = {"system:read", "task:read", "customer:read", "workspace:read", "memory:read"}
_MEMBER = _VIEWER | {"task:write", "ai:use", "agent:run", "memory:write"}
_ADMIN = _MEMBER | {"system:*", "task:*", "customer:*", "approval:*", "connection:*", "member:*",
                    "policy:*", "audit:*", "workspace:update", "agent:*", "memory:*",
                    # Business domains (Step 10): admin-only until Step 11/12 assign them deliberately.
                    "email:*", "calendar:*", "crm:*", "chat:*", "project:*",
                    # Business capabilities (Step 11.2/11.3): composite read tools; admin-only like the domains they read.
                    "insight:*", "sales:*"}

ROLE_PERMISSIONS: dict[Role, FrozenSet[str]] = {
    Role.VIEWER: frozenset(_VIEWER),
    Role.MEMBER: frozenset(_MEMBER),
    Role.ADMIN: frozenset(_ADMIN),
    Role.OWNER: frozenset({"*"}),
}


def permissions_for(role: Role) -> FrozenSet[str]:
    return ROLE_PERMISSIONS[role]


def outranks_or_equals(a: Role, b: Role) -> bool:
    return ROLE_RANK[a] >= ROLE_RANK[b]
