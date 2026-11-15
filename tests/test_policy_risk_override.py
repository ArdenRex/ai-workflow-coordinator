"""Substep 12.3a: per-workspace risk override per tool. Tighten only: effective risk = max(tool risk, override)."""
import pathlib

import pytest
from pydantic import BaseModel
from sqlalchemy import select

from app.kernel.permissions import Principal
from app.kernel.policy import Outcome, WorkspacePolicy, effective_risk, evaluate
from app.kernel.policy_store import to_workspace_policy
from app.kernel.registry import ToolDefinition
from app.kernel.service import ToolExecutionService
from app.kernel.policy_store import db_policy_provider
from app.models.enums import ExecutionStatus, RiskLevel
from app.models.kernel import SystemEvent
from app.models.policy import WorkspacePolicyRecord
from tests.test_policy_store import factory, put, url
from tests.test_workspace_connectors import principal, signup, mkws, public_dns, team  # noqa: F401


class _Io(BaseModel):
    pass


def tool(tid, risk, approval=None):
    return ToolDefinition(id=tid, description="d", input_schema=_Io, output_schema=_Io, required_permission="x:read",
                          risk_level=risk, requires_approval=approval)


def pr(ws="w"):
    return Principal(user_id="u", workspace_id=ws, permissions=frozenset({"x:read"}))


# ------------------------------------------------------------------ engine (pure)
def test_an_override_raises_risk_and_never_lowers_it():
    low, med, high = tool("a.low", RiskLevel.LOW), tool("a.med", RiskLevel.MEDIUM), tool("a.high", RiskLevel.HIGH)
    pol = WorkspacePolicy(risk_overrides={"a.low": RiskLevel.HIGH, "a.med": RiskLevel.LOW, "a.high": RiskLevel.LOW})
    assert effective_risk(low, pol) == RiskLevel.HIGH
    assert effective_risk(med, pol) == RiskLevel.MEDIUM          # a lower override is ignored even if one got stored
    assert effective_risk(high, pol) == RiskLevel.HIGH
    assert effective_risk(low, None) == RiskLevel.LOW and effective_risk(low, WorkspacePolicy()) == RiskLevel.LOW


def test_an_override_forces_approval_with_its_own_reason_code_and_changes_nothing_else():
    low = tool("a.low", RiskLevel.LOW)
    assert evaluate(low, pr(), "w", WorkspacePolicy()).outcome == Outcome.ALLOW
    for level in (RiskLevel.MEDIUM, RiskLevel.HIGH):
        d = evaluate(low, pr(), "w", WorkspacePolicy(risk_overrides={"a.low": level}))
        assert (d.outcome, d.reason_code) == (Outcome.REQUIRE_APPROVAL, "workspace_risk_override")
    other = evaluate(tool("a.other", RiskLevel.LOW), pr(), "w", WorkspacePolicy(risk_overrides={"a.low": RiskLevel.HIGH}))
    assert other.outcome == Outcome.ALLOW                         # only the named tool is affected
    # deny rules still come first, and the tool's own rules keep their own codes
    assert evaluate(low, pr(), "w", WorkspacePolicy(disabled_tools=frozenset({"a.low"}), risk_overrides={"a.low": RiskLevel.HIGH})).reason_code == "tool_disabled"
    assert evaluate(tool("a.h", RiskLevel.HIGH), pr(), "w", WorkspacePolicy(risk_overrides={"a.h": RiskLevel.HIGH})).reason_code == "high_risk"
    assert evaluate(tool("a.m", RiskLevel.MEDIUM, approval=True), pr(), "w", WorkspacePolicy(risk_overrides={"a.m": RiskLevel.MEDIUM})).reason_code in (
        "tool_requires_approval", "risk_above_auto_limit")


def test_the_override_cannot_raise_the_automatic_limit():
    assert WorkspacePolicy().auto_execute_max_risk == RiskLevel.LOW
    rec = WorkspacePolicyRecord(workspace_id="w", updated_by="u", version=1, autonomy_level=3, disabled_tools=[],
                                approval_required_tools=[], risk_overrides={"system.ping": "high"})
    pol = to_workspace_policy(rec)
    assert pol.auto_execute_max_risk == RiskLevel.LOW and pol.risk_overrides == {"system.ping": RiskLevel.HIGH}


# ------------------------------------------------------------------ store + HTTP
def test_overrides_are_stored_versioned_and_returned(client, team, db_session):
    hs, ws = team
    r = put(client, hs["admin"], ws, expected_version=0, autonomy_level=3, risk_overrides={"system.ping": "medium"})
    assert r.status_code == 200 and r.json()["risk_overrides"] == {"system.ping": "medium"} and r.json()["version"] == 1
    assert client.get(url(ws), headers=hs["owner"]).json()["risk_overrides"] == {"system.ping": "medium"}
    r2 = put(client, hs["admin"], ws, expected_version=1, autonomy_level=3)               # a write replaces the whole policy
    assert r2.json()["risk_overrides"] == {}
    ev = db_session.scalar(select(SystemEvent).where(SystemEvent.event_type == "policy.created"))
    assert ev.payload["risk_override_count"] == 1 and "system.ping" not in str(ev.payload)


@pytest.mark.parametrize("overrides", [
    {"system.ping": "low"},            # not above the tool's own risk: a no-op or a loosening is refused
    {"system.ping": "critical"}, {"system.ping": 2}, {"system.ping": None},
    {"no.such.tool": "high"}, {1: "high"}, ["system.ping"], "high", 5,
])
def test_invalid_overrides_are_refused_and_change_nothing(client, team, db_session, overrides):
    hs, ws = team
    r = put(client, hs["admin"], ws, expected_version=0, autonomy_level=3, risk_overrides=overrides)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_policy"
    assert "system.ping" not in str(r.json()) and "no.such.tool" not in str(r.json())
    assert db_session.scalar(select(WorkspacePolicyRecord)) is None


def test_members_cannot_set_overrides(client, team, db_session):
    hs, ws = team
    assert put(client, hs["member"], ws, expected_version=0, autonomy_level=3, risk_overrides={"system.ping": "high"}).status_code == 403
    assert db_session.scalar(select(WorkspacePolicyRecord)) is None


# ------------------------------------------------------------------ real kernel
def test_the_kernel_parks_an_overridden_tool_and_records_the_effective_risk(client, team, db_session):
    hs, ws = team
    tools = client.app.state.tool_registry
    me = principal(db_session, "admin@x.com", ws["id"])
    kernel = ToolExecutionService(db_session, tools, policy_provider=db_policy_provider(factory(db_session)))
    assert kernel.submit(me, "system.ping", {}).status == ExecutionStatus.SUCCEEDED
    put(client, hs["admin"], ws, expected_version=0, autonomy_level=3, risk_overrides={"system.ping": "high"})
    ex = kernel.submit(me, "system.ping", {})
    assert ex.status == ExecutionStatus.AWAITING_APPROVAL and ex.risk_level == RiskLevel.HIGH
    created = db_session.scalar(select(SystemEvent).where(SystemEvent.execution_id == ex.id, SystemEvent.event_type == "execution.created"))
    assert created.payload["policy"] == "workspace_risk_override"
    put(client, hs["admin"], ws, expected_version=1, autonomy_level=3)                    # clearing it restores the baseline
    assert kernel.submit(me, "system.ping", {}).status == ExecutionStatus.SUCCEEDED


def test_another_workspace_is_unaffected(client, team, db_session):
    hs, ws = team
    other = mkws(client, hs["outsider"])
    put(client, hs["admin"], ws, expected_version=0, autonomy_level=3, risk_overrides={"system.ping": "high"})
    provider = db_policy_provider(factory(db_session))
    assert provider(other["id"]) == WorkspacePolicy() and provider(ws["id"]).risk_overrides == {"system.ping": RiskLevel.HIGH}


def test_the_engine_has_no_connector_or_agent_authority():
    src = pathlib.Path("app/kernel/policy.py").read_text()
    assert "connector" not in src.lower() and "httpx" not in src
