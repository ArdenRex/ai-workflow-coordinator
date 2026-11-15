import pytest
from pydantic import BaseModel

from app.kernel.permissions import Principal, has_permission, permission_matches
from app.kernel.policy import Outcome, WorkspacePolicy, evaluate
from app.kernel.registry import ToolDefinition
from app.models.enums import RiskLevel


class S(BaseModel):
    pass


def tool(risk=RiskLevel.LOW, perm="customer:read", **kw):
    return ToolDefinition(id=kw.pop("id", "aceden.customer.read"), description="d", input_schema=S,
                          output_schema=S, required_permission=perm, risk_level=risk, **kw)


def user(perms=("customer:read",), ws="w1", **kw):
    return Principal(user_id="u1", workspace_id=ws, permissions=frozenset(perms), **kw)


# --- permission matching -------------------------------------------------
@pytest.mark.parametrize("granted,required,ok", [
    ("customer:read", "customer:read", True),
    ("customer:*", "customer:read", True),
    ("customer:*", "customer:contact:read", True),
    ("*", "anything:else", True),
    ("customer:read", "customer:write", False),
    ("cust:*", "customer:read", False),          # no prefix-injection
    ("customer:readx", "customer:read", False),
    ("customer", "customer:read", False),
])
def test_permission_matches(granted, required, ok):
    assert permission_matches(granted, required) is ok


def test_empty_permissions_deny_everything():
    assert has_permission(frozenset(), "customer:read") is False


def test_principal_validation():
    with pytest.raises(ValueError):
        Principal(user_id="", workspace_id="w", permissions=frozenset())
    with pytest.raises(ValueError):
        Principal(user_id="u", workspace_id="w", permissions=frozenset(), agent="sales")  # no scope


def test_agent_scope_narrows_user_permissions():
    p = user(perms=("customer:*",), agent="sales", agent_scope=frozenset({"customer:read"}))
    assert p.can("customer:read") and not p.can("customer:delete")


def test_agent_with_empty_scope_can_do_nothing():
    p = user(perms=("*",), agent="x", agent_scope=frozenset())
    assert not p.can("customer:read")


# --- policy ---------------------------------------------------------------
def test_low_risk_allowed():
    d = evaluate(tool(), user(), "w1")
    assert d.outcome == Outcome.ALLOW and d.allowed


def test_workspace_mismatch_denied_first():
    d = evaluate(tool(), user(ws="w1"), "w2")
    assert d.outcome == Outcome.DENY and d.reason_code == "workspace_mismatch"


def test_missing_permission_denied():
    d = evaluate(tool(), user(perms=("other:read",)), "w1")
    assert d.reason_code == "permission_denied" and not d.allowed


def test_agent_scope_denied():
    p = user(perms=("customer:*",), agent="a", agent_scope=frozenset({"email:*"}))
    assert evaluate(tool(), p, "w1").reason_code == "agent_scope_denied"


def test_disabled_tool_denied_even_for_admin():
    d = evaluate(tool(), user(perms=("*",)), "w1",
                 WorkspacePolicy(disabled_tools=frozenset({"aceden.customer.read"})))
    assert d.reason_code == "tool_disabled"


def test_high_risk_always_requires_approval_even_with_permissive_policy():
    t = tool(risk=RiskLevel.HIGH, perm="customer:delete", id="aceden.customer.delete")
    d = evaluate(t, user(perms=("*",)), "w1", WorkspacePolicy(auto_execute_max_risk=RiskLevel.HIGH))
    assert d.outcome == Outcome.REQUIRE_APPROVAL and d.reason_code == "high_risk"


def test_tool_level_approval_cannot_be_waived_by_policy():
    t = tool(risk=RiskLevel.MEDIUM, requires_approval=True, perm="customer:write")
    d = evaluate(t, user(perms=("customer:write",)), "w1",
                 WorkspacePolicy(auto_execute_max_risk=RiskLevel.HIGH))
    assert d.outcome == Outcome.REQUIRE_APPROVAL


def test_medium_risk_needs_approval_by_default_ceiling():
    t = tool(risk=RiskLevel.MEDIUM, perm="customer:write")
    d = evaluate(t, user(perms=("customer:write",)), "w1")
    assert d.reason_code == "risk_above_auto_limit"


def test_medium_risk_auto_when_workspace_raises_ceiling():
    t = tool(risk=RiskLevel.MEDIUM, perm="customer:write")
    d = evaluate(t, user(perms=("customer:write",)), "w1",
                 WorkspacePolicy(auto_execute_max_risk=RiskLevel.MEDIUM))
    assert d.outcome == Outcome.ALLOW


def test_workspace_can_force_approval_on_low_risk_tool():
    d = evaluate(tool(), user(), "w1",
                 WorkspacePolicy(approval_required_tools=frozenset({"aceden.customer.read"})))
    assert d.reason_code == "workspace_policy"


def test_deny_beats_approval():
    t = tool(risk=RiskLevel.HIGH, perm="customer:delete", id="aceden.customer.delete")
    assert evaluate(t, user(perms=("customer:read",)), "w1").outcome == Outcome.DENY
