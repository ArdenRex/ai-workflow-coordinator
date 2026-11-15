"""Substep 12.1: workspace policy store, autonomy levels and the fail-closed provider."""
import json
import pathlib

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.agents.starter import INSIGHT_AGENT
from app.kernel.errors import PolicyDeniedError
from app.kernel.policy import WorkspacePolicy
from app.kernel.policy_store import (DEFAULT_LEVEL, AutonomyLevel, InvalidPolicyError, PolicyService, VersionConflictError,
                                     db_policy_provider, to_workspace_policy)
from app.kernel.service import ToolExecutionService
from app.models.enums import ExecutionStatus, RiskLevel
from app.models.kernel import SystemEvent, ToolExecution
from app.models.policy import WorkspacePolicyRecord
from tests.test_workspace_connectors import principal, signup, mkws, public_dns, team  # noqa: F401

CANARY = "CANARY-policy-7731"


def url(ws):
    return f"/workspaces/{ws['id']}/policy"


def put(client, h, ws, **body):
    return client.put(url(ws), json=body, headers=h)


def count(db, model):
    return db.scalar(select(func.count()).select_from(model))


# ------------------------------------------------------------------ read
def test_default_policy_is_the_baseline_and_only_admins_can_read_it(client, team):
    hs, ws = team
    for who in ("admin", "owner"):
        r = client.get(url(ws), headers=hs[who])
        assert r.status_code == 200
        assert r.json() == {"workspace_id": ws["id"], "version": 0, "is_default": True, "autonomy_level": 3, "autonomy_name": "prepare",
                            "disabled_tools": [], "approval_required_tools": [], "risk_overrides": {}, "execution_limit": None, "escalation": None, "approval_routing": {}, "auto_execute_tools": [], "auto_execute_max_risk": "low",
                            "updated_at": None, "updated_by": None}
    assert client.get(url(ws), headers=hs["member"]).status_code == 403
    assert client.get(url(ws), headers=hs["outsider"]).status_code in (403, 404)
    assert client.get(url(ws)).status_code == 401
    assert to_workspace_policy(None) == WorkspacePolicy() and DEFAULT_LEVEL == AutonomyLevel.PREPARE


# ------------------------------------------------------------------ write
def test_first_write_then_updates_use_the_version_and_stale_writes_conflict(client, team, db_session):
    hs, ws = team
    r = put(client, hs["admin"], ws, expected_version=0, autonomy_level=2, disabled_tools=["system.ping"])
    assert r.status_code == 200 and (r.json()["version"], r.json()["autonomy_level"], r.json()["is_default"]) == (1, 2, False)
    assert r.json()["disabled_tools"] == ["system.ping"] and r.json()["autonomy_name"] == "recommend"
    assert client.get(url(ws), headers=hs["owner"]).json()["version"] == 1
    again = put(client, hs["owner"], ws, expected_version=0, autonomy_level=3)               # a second "first write" is stale
    assert again.status_code == 409 and again.json()["detail"]["code"] == "version_conflict"
    ok = put(client, hs["owner"], ws, expected_version=1, autonomy_level=1, approval_required_tools=["system.ping", "system.ping"])
    assert ok.status_code == 200 and ok.json()["version"] == 2 and ok.json()["approval_required_tools"] == ["system.ping"]
    assert ok.json()["disabled_tools"] == []                                               # a write replaces the whole policy
    assert put(client, hs["admin"], ws, expected_version=1, autonomy_level=3).status_code == 409
    assert count(db_session, WorkspacePolicyRecord) == 1


def test_only_admins_write_and_members_and_outsiders_change_nothing(client, team, db_session):
    hs, ws = team
    for who in ("member", "outsider"):
        assert put(client, hs[who], ws, expected_version=0, autonomy_level=1).status_code in (403, 404)
    assert client.put(url(ws), json={}).status_code == 401
    assert client.post(url(ws), json={}, headers=hs["admin"]).status_code == 405
    assert count(db_session, WorkspacePolicyRecord) == 0


@pytest.mark.parametrize("body, code", [
    ({"autonomy_level": 2}, "invalid_policy"),                                               # no expected_version
    ({"expected_version": 0}, "invalid_policy"),                                             # no level
    ({"expected_version": 0, "autonomy_level": 0}, "invalid_policy"),
    ({"expected_version": 0, "autonomy_level": 6}, "invalid_policy"),
    ({"expected_version": 0, "autonomy_level": True}, "invalid_policy"),
    ({"expected_version": -1, "autonomy_level": 2}, "invalid_policy"),
    ({"expected_version": 0, "autonomy_level": "2"}, "invalid_policy"),
    ({"expected_version": 0, "autonomy_level": 2, "extra": 1}, "invalid_policy"),
    ({"expected_version": 0, "autonomy_level": 2, "disabled_tools": "system.ping"}, "invalid_policy"),
    ({"expected_version": 0, "autonomy_level": 2, "disabled_tools": [f"no.such.{CANARY}"]}, "invalid_policy"),
    ({"expected_version": 0, "autonomy_level": 2, "approval_required_tools": [1]}, "invalid_policy"),
    ({"expected_version": 0, "autonomy_level": 2, "disabled_tools": ["system.ping"] * 101}, "invalid_policy"),
])
def test_invalid_policies_are_refused_with_fixed_text_and_change_nothing(client, team, db_session, body, code):
    hs, ws = team
    before = count(db_session, SystemEvent)
    r = client.put(url(ws), json=body, headers=hs["admin"])
    assert r.status_code == 422 and r.json()["detail"]["code"] == code and CANARY not in r.text
    assert count(db_session, WorkspacePolicyRecord) == 0 and count(db_session, SystemEvent) == before


def test_a_policy_is_per_workspace(client, team):
    hs, ws = team
    other = mkws(client, hs["outsider"])
    put(client, hs["admin"], ws, expected_version=0, autonomy_level=1, disabled_tools=["system.ping"])
    assert client.get(url(other), headers=hs["outsider"]).json()["is_default"] is True
    assert client.get(url(ws), headers=hs["outsider"]).status_code in (403, 404)
    assert put(client, hs["outsider"], other, expected_version=0, autonomy_level=3).status_code == 200
    assert client.get(url(ws), headers=hs["admin"]).json()["autonomy_level"] == 1


def test_an_agent_can_never_change_policy(client, team, db_session):
    hs, ws = team
    from app.agents.context import agent_principal
    svc = PolicyService(db_session, client.app.state.tool_registry)
    agent = agent_principal(principal(db_session, "admin@x.com", ws["id"]), INSIGHT_AGENT)
    with pytest.raises(InvalidPolicyError):
        svc.set(agent, {"expected_version": 0, "autonomy_level": 1})
    assert count(db_session, WorkspacePolicyRecord) == 0


def test_the_swap_is_atomic_even_when_the_read_was_stale(client, team, db_session, monkeypatch):
    hs, ws = team
    put(client, hs["admin"], ws, expected_version=0, autonomy_level=3)
    from types import SimpleNamespace
    svc = PolicyService(db_session, client.app.state.tool_registry)
    row = svc.get(ws["id"])
    stale = SimpleNamespace(id=row.id, version=1, autonomy_level=3)                          # a detached copy of what was read at v1
    put(client, hs["owner"], ws, expected_version=1, autonomy_level=2)                       # someone else wins in between
    db_session.expire_all()
    monkeypatch.setattr(svc, "get", lambda wid: stale)
    with pytest.raises(VersionConflictError):
        svc.set(principal(db_session, "admin@x.com", ws["id"]), {"expected_version": 1, "autonomy_level": 1})
    assert client.get(url(ws), headers=hs["admin"]).json()["autonomy_level"] == 2


# ------------------------------------------------------------------ audit
def test_every_change_is_audited_without_tool_names_or_text(client, team, db_session):
    hs, ws = team
    put(client, hs["admin"], ws, expected_version=0, autonomy_level=2, disabled_tools=["system.ping"], approval_required_tools=["system.ping"])
    put(client, hs["owner"], ws, expected_version=1, autonomy_level=1)
    evs = db_session.scalars(select(SystemEvent).where(SystemEvent.workspace_id == ws["id"], SystemEvent.event_type.like("policy.%"))
                             .order_by(SystemEvent.created_at)).all()
    assert [e.event_type for e in evs] == ["policy.created", "policy.updated"]
    assert evs[0].payload == {"version": 1, "autonomy_level": 2, "previous_level": 3, "disabled_count": 1, "approval_required_count": 1, "risk_override_count": 0, "has_execution_limit": False, "has_escalation": False, "approval_routing_count": 0, "auto_execute_count": 0}
    assert evs[1].payload["previous_level"] == 2 and evs[1].payload["disabled_count"] == 0 and evs[0].actor != evs[1].actor
    assert "system.ping" not in json.dumps([e.payload for e in evs])


# ------------------------------------------------------------------ the provider and the kernel
def factory(db):
    return sessionmaker(bind=db.get_bind(), autoflush=False, expire_on_commit=False)


def test_the_provider_reads_the_store_each_time_and_workspaces_do_not_mix(client, team, db_session):
    hs, ws = team
    other = mkws(client, hs["outsider"])
    provider = db_policy_provider(factory(db_session))
    assert provider(ws["id"]) == WorkspacePolicy()
    put(client, hs["admin"], ws, expected_version=0, autonomy_level=2, disabled_tools=["system.ping"], approval_required_tools=["task.x"][:0])
    assert provider(ws["id"]).disabled_tools == frozenset({"system.ping"}) and provider(other["id"]) == WorkspacePolicy()


def test_a_stored_policy_is_enforced_by_the_kernel_and_can_only_tighten(client, team, db_session):
    hs, ws = team
    tools = client.app.state.tool_registry
    ping = tools.get("system.ping")
    assert ping.risk_level == RiskLevel.LOW and not ping.approval_required
    me = principal(db_session, "admin@x.com", ws["id"])
    kernel = ToolExecutionService(db_session, tools, policy_provider=db_policy_provider(factory(db_session)))
    assert kernel.submit(me, "system.ping", {}).status == ExecutionStatus.SUCCEEDED         # baseline
    put(client, hs["admin"], ws, expected_version=0, autonomy_level=3, approval_required_tools=["system.ping"])
    assert kernel.submit(me, "system.ping", {}).status == ExecutionStatus.AWAITING_APPROVAL
    put(client, hs["admin"], ws, expected_version=1, autonomy_level=3, disabled_tools=["system.ping"])
    with pytest.raises(PolicyDeniedError):
        kernel.submit(me, "system.ping", {})
    put(client, hs["admin"], ws, expected_version=2, autonomy_level=1)                       # an empty policy restores the baseline only
    assert kernel.submit(me, "system.ping", {}).status == ExecutionStatus.SUCCEEDED
    for rec_level in range(1, 6):                                                           # no stored level can raise the automatic limit
        rec = WorkspacePolicyRecord(workspace_id=ws["id"], updated_by=me.user_id, version=1, autonomy_level=rec_level,
                                    disabled_tools=[], approval_required_tools=[],
                                    **({"execution_limit": {"max_executions": 1, "window_seconds": 60}, "escalation": {"threshold": 1, "window_seconds": 60},
                                        "approval_routing": {"high": "owner"}} if rec_level == 5 else {}))
        assert to_workspace_policy(rec).auto_execute_max_risk == RiskLevel.LOW


def test_the_provider_fails_closed_when_the_store_cannot_be_read():
    def broken():
        raise RuntimeError("db down")
    with pytest.raises(RuntimeError):
        db_policy_provider(broken)("any")


def test_the_module_has_no_connector_or_agent_authority_and_the_api_is_registered():
    for path in ("app/kernel/policy_store.py", "app/api/policy.py"):
        text = pathlib.Path(path).read_text()
        assert "app.connectors" not in text and "execute_approved" not in text and "import httpx" not in text
    assert "policy.router" in pathlib.Path("app/main.py").read_text()
