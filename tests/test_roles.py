import pytest

from app.identity.roles import ROLE_PERMISSIONS, outranks_or_equals, permissions_for
from app.kernel.permissions import Principal
from app.models.enums import Role


def P(role):
    return Principal(user_id="u", workspace_id="w", permissions=permissions_for(role))


def test_every_role_is_mapped_and_ranked():
    assert set(ROLE_PERMISSIONS) == set(Role)
    assert outranks_or_equals(Role.OWNER, Role.ADMIN) and not outranks_or_equals(Role.ADMIN, Role.OWNER)
    assert outranks_or_equals(Role.MEMBER, Role.MEMBER)


def test_viewer_is_read_only():
    v = P(Role.VIEWER)
    assert v.can("task:read") and v.can("system:read") and v.can("workspace:read")
    for p in ("task:write", "approval:decide", "member:manage", "connection:write", "workspace:delete"):
        assert not v.can(p)


def test_member_can_write_tasks_but_not_decide_or_manage():
    m = P(Role.MEMBER)
    assert m.can("task:write") and m.can("task:read")
    assert not m.can("approval:decide") and not m.can("member:manage")


def test_admin_manages_but_cannot_delete_workspace_or_bill():
    a = P(Role.ADMIN)
    assert a.can("approval:decide") and a.can("member:manage") and a.can("connection:write")
    assert not a.can("workspace:delete") and not a.can("billing:manage")


def test_owner_has_everything_and_unknown_permissions_are_owner_only():
    assert P(Role.OWNER).can("anything:new")
    for r in (Role.ADMIN, Role.MEMBER, Role.VIEWER):
        assert not P(r).can("brandnew:action")


def test_registered_tool_permissions_are_reachable_by_viewer():
    from app.kernel.builtin_tools import SYSTEM_PING
    assert P(Role.VIEWER).can(SYSTEM_PING.required_permission)
    assert P(Role.VIEWER).can("task:read")          # aceden.task.* tools
