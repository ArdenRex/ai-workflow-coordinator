"""Substep 12.4: autonomy level 4. The only loosening: an explicit allowlist of tools (own risk <= medium) may run unattended, under a cap."""
import pytest
from sqlalchemy import select

from app.kernel.builtin_tools import PingInput, PingOutput, _ping
from app.kernel.errors import PolicyDeniedError
from app.kernel.permissions import Principal
from app.kernel.policy import Outcome, WorkspacePolicy, evaluate
from app.kernel.policy_store import to_workspace_policy
from app.kernel.registry import ToolDefinition
from app.models.enums import ExecutionStatus, RiskLevel
from app.models.kernel import SystemEvent
from app.models.policy import WorkspacePolicyRecord
from tests.test_policy_execution_limit import kernel_for
from tests.test_policy_store import put, url
from tests.test_workspace_connectors import principal, mkws, team  # noqa: F401

CAP = {"max_executions": 5, "window_seconds": 3600}


def mk(tid, risk, approval=None):
    return ToolDefinition(id=tid, description="d", input_schema=PingInput, output_schema=PingOutput, required_permission="system:read",
                          risk_level=risk, requires_approval=approval, timeout_seconds=5, handler=_ping)


@pytest.fixture
def tools(client):
    reg = client.app.state.tool_registry
    for t in (mk("t.med", RiskLevel.MEDIUM), mk("t.med2", RiskLevel.MEDIUM), mk("t.high", RiskLevel.HIGH), mk("t.medapp", RiskLevel.MEDIUM, approval=True)):
        if not reg.has(t.id):
            reg.register(t)
    return reg


def l4(client, h, ws, **kw):
    body = dict(expected_version=kw.pop("v", 0), autonomy_level=4, execution_limit=CAP)
    body.update(kw)
    return put(client, h, ws, **body)


def pr():
    return Principal(user_id="u", workspace_id="w", permissions=frozenset({"system:read"}))


# ------------------------------------------------------------------ store + HTTP
def test_level_4_needs_a_cap(client, team, tools):
    hs, ws = team
    r = put(client, hs["admin"], ws, expected_version=0, autonomy_level=4)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_policy"
    r = l4(client, hs["admin"], ws, auto_execute_tools=["t.med"])
    assert r.status_code == 200
    j = r.json()
    assert (j["autonomy_level"], j["autonomy_name"], j["auto_execute_tools"]) == (4, "execute_low", ["t.med"]) and j["execution_limit"] == CAP
    assert client.get(url(ws), headers=hs["owner"]).json()["auto_execute_tools"] == ["t.med"]


@pytest.mark.parametrize("extra", [
    {"auto_execute_tools": ["no.such"]}, {"auto_execute_tools": ["t.high"]}, {"auto_execute_tools": ["t.medapp"]},
    {"auto_execute_tools": ["t.med"], "disabled_tools": ["t.med"]}, {"auto_execute_tools": ["t.med"], "approval_required_tools": ["t.med"]},
    {"auto_execute_tools": ["t.med"], "risk_overrides": {"t.med": "high"}}, {"auto_execute_tools": "t.med"}, {"auto_execute_tools": [1]},
    {"auto_execute_tools": None},
])
def test_unsafe_allowlists_are_refused_and_change_nothing(client, team, db_session, tools, extra):
    hs, ws = team
    r = l4(client, hs["admin"], ws, **extra)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_policy"
    assert db_session.scalar(select(WorkspacePolicyRecord)) is None


@pytest.mark.parametrize("level", [1, 2, 3])
def test_an_allowlist_below_level_4_is_refused(client, team, db_session, tools, level):
    hs, ws = team
    r = put(client, hs["admin"], ws, expected_version=0, autonomy_level=level, execution_limit=CAP, auto_execute_tools=["t.med"])
    assert r.status_code == 422 and db_session.scalar(select(WorkspacePolicyRecord)) is None


def test_members_cannot_set_level_4(client, team, db_session, tools):
    hs, ws = team
    assert l4(client, hs["member"], ws, auto_execute_tools=["t.med"]).status_code == 403


@pytest.mark.parametrize("level,limit,tools_", [(3, CAP, ["t.med"]), (4, None, ["t.med"])])
def test_a_malformed_stored_allowlist_fails_closed(level, limit, tools_):
    rec = WorkspacePolicyRecord(workspace_id="w", updated_by="u", version=1, autonomy_level=level, disabled_tools=[], approval_required_tools=[],
                                risk_overrides={}, execution_limit=limit, auto_execute_tools=tools_)
    with pytest.raises(ValueError):
        to_workspace_policy(rec)


# ------------------------------------------------------------------ engine (pure)
def test_engine_allows_only_a_listed_tool_and_never_over_a_stronger_rule():
    med, high = mk("a.med", RiskLevel.MEDIUM), mk("a.high", RiskLevel.HIGH)
    on = WorkspacePolicy(auto_execute_tools=frozenset({"a.med", "a.high", "a.app", "a.over"}))
    assert evaluate(med, pr(), "w", WorkspacePolicy()).outcome == Outcome.REQUIRE_APPROVAL                    # baseline: unchanged
    assert evaluate(med, pr(), "w", on).outcome == Outcome.ALLOW
    assert evaluate(mk("a.other", RiskLevel.MEDIUM), pr(), "w", on).outcome == Outcome.REQUIRE_APPROVAL      # not listed
    assert evaluate(high, pr(), "w", on).reason_code == "high_risk"                                           # high is never waived
    assert evaluate(mk("a.app", RiskLevel.MEDIUM, approval=True), pr(), "w", on).reason_code == "tool_requires_approval"
    over = WorkspacePolicy(auto_execute_tools=frozenset({"a.over"}), risk_overrides={"a.over": RiskLevel.HIGH})
    assert evaluate(mk("a.over", RiskLevel.MEDIUM), pr(), "w", over).reason_code == "workspace_risk_override"
    rule = WorkspacePolicy(auto_execute_tools=frozenset({"a.med"}), approval_required_tools=frozenset({"a.med"}))
    assert evaluate(med, pr(), "w", rule).reason_code == "workspace_policy"
    assert evaluate(med, pr(), "w", WorkspacePolicy(auto_execute_tools=frozenset({"a.med"}), disabled_tools=frozenset({"a.med"}))).outcome == Outcome.DENY


def test_engine_still_checks_permission_and_workspace_before_the_allowlist():
    med = mk("a.med", RiskLevel.MEDIUM)
    on = WorkspacePolicy(auto_execute_tools=frozenset({"a.med"}))
    no_perm = Principal(user_id="u", workspace_id="w", permissions=frozenset())
    assert evaluate(med, no_perm, "w", on).reason_code == "permission_denied"
    assert evaluate(med, pr(), "other", on).reason_code == "workspace_mismatch"
    agent = Principal(user_id="u", workspace_id="w", permissions=frozenset({"system:read"}), agent="a", agent_scope=frozenset({"task:read"}))
    assert evaluate(med, agent, "w", on).reason_code == "agent_scope_denied"


# ------------------------------------------------------------------ real kernel
def test_a_listed_tool_runs_unattended_at_level_4_and_an_unlisted_one_still_parks(client, team, db_session, tools):
    hs, ws = team
    me, k = principal(db_session, "member@x.com", ws["id"]), kernel_for(client, db_session)
    assert k.submit(me, "t.med", {}).status == ExecutionStatus.AWAITING_APPROVAL          # baseline: parked
    assert l4(client, hs["admin"], ws, auto_execute_tools=["t.med"]).status_code == 200
    assert k.submit(me, "t.med", {"message": "a"}).status == ExecutionStatus.SUCCEEDED
    assert k.submit(me, "t.med2", {}).status == ExecutionStatus.AWAITING_APPROVAL
    assert k.submit(me, "t.high", {}).status == ExecutionStatus.AWAITING_APPROVAL


def test_level_4_runs_count_against_the_cap(client, team, db_session, tools):
    hs, ws = team
    me, k = principal(db_session, "member@x.com", ws["id"]), kernel_for(client, db_session)
    l4(client, hs["admin"], ws, auto_execute_tools=["t.med"], execution_limit={"max_executions": 2, "window_seconds": 3600})
    for i in range(2):
        assert k.submit(me, "t.med", {"message": str(i)}).status == ExecutionStatus.SUCCEEDED
    with pytest.raises(PolicyDeniedError) as e:
        k.submit(me, "t.med", {})
    assert e.value.reason_code == "execution_limit_reached"


def test_escalation_still_parks_a_listed_tool(client, team, db_session, tools):
    hs, ws = team
    me, k = principal(db_session, "member@x.com", ws["id"]), kernel_for(client, db_session)
    l4(client, hs["admin"], ws, auto_execute_tools=["t.med"], escalation={"threshold": 1, "window_seconds": 3600})
    from tests.test_policy_escalation import fail_rows
    fail_rows(db_session, ws["id"], 1)
    ex = k.submit(me, "t.med", {})
    assert ex.status == ExecutionStatus.AWAITING_APPROVAL
    assert db_session.scalar(select(SystemEvent).where(SystemEvent.execution_id == ex.id, SystemEvent.event_type == "execution.created")).payload["policy"] == "escalation_threshold"


def test_lowering_the_level_restores_the_baseline_and_other_workspaces_are_unaffected(client, team, db_session, tools):
    hs, ws = team
    other = mkws(client, hs["outsider"])
    l4(client, hs["outsider"], other, auto_execute_tools=["t.med"])
    me, k = principal(db_session, "member@x.com", ws["id"]), kernel_for(client, db_session)
    assert k.submit(me, "t.med", {}).status == ExecutionStatus.AWAITING_APPROVAL         # their level 4 is not ours
    l4(client, hs["admin"], ws, auto_execute_tools=["t.med"])
    assert k.submit(me, "t.med", {"message": "x"}).status == ExecutionStatus.SUCCEEDED
    assert put(client, hs["admin"], ws, expected_version=1, autonomy_level=3).status_code == 200
    assert k.submit(me, "t.med", {"message": "y"}).status == ExecutionStatus.AWAITING_APPROVAL
