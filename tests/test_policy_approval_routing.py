"""Substep 12.3e: approval routing (tighten only). Approvals of a routed risk level need the owner-only permission to decide."""
import pathlib
import re

import pytest
from sqlalchemy import select

from app.kernel.approvals import ApprovalService
from app.kernel.errors import ApprovalPermissionError
from app.kernel.policy import WorkspacePolicy, extra_decider_permission
from app.kernel.policy_store import db_policy_provider, to_workspace_policy
from app.models.enums import ApprovalStatus, ExecutionStatus, RiskLevel
from app.models.kernel import SystemEvent
from app.models.policy import WorkspacePolicyRecord
from tests.test_policy_execution_limit import kernel_for
from tests.test_policy_store import factory, put, url
from tests.test_workspace_connectors import principal, team  # noqa: F401


def svc(client, db):
    return ApprovalService(db, policy_provider=db_policy_provider(factory(db)))


def parked(client, team, db, routing, *, override="high"):
    hs, ws = team
    r = put(client, hs["admin"], ws, expected_version=0, autonomy_level=3, risk_overrides={"system.ping": override}, approval_routing=routing)
    assert r.status_code == 200
    ex = kernel_for(client, db).submit(principal(db, "member@x.com", ws["id"]), "system.ping", {})
    assert ex.status == ExecutionStatus.AWAITING_APPROVAL and ex.risk_level.value == override
    return ex


# ------------------------------------------------------------------ store + HTTP
def test_routing_is_stored_returned_audited_and_cleared_by_a_replace(client, team, db_session):
    hs, ws = team
    assert client.get(url(ws), headers=hs["owner"]).json()["approval_routing"] == {}
    r = put(client, hs["admin"], ws, expected_version=0, autonomy_level=3, approval_routing={"high": "owner", "medium": "owner"})
    assert r.status_code == 200 and r.json()["approval_routing"] == {"high": "owner", "medium": "owner"}
    assert db_session.scalar(select(SystemEvent).where(SystemEvent.event_type == "policy.created")).payload["approval_routing_count"] == 2
    assert put(client, hs["admin"], ws, expected_version=1, autonomy_level=3).json()["approval_routing"] == {}


@pytest.mark.parametrize("routing", [{"low": "owner"}, {"high": "admin"}, {"high": "member"}, {"high": ""}, {"high": None}, {"x": "owner"},
                                      {"high": "owner", "extra": "owner"}, [], "owner", 1, None, {"high": ["owner"]}])
def test_invalid_routing_is_refused_and_changes_nothing(client, team, db_session, routing):
    hs, ws = team
    r = put(client, hs["admin"], ws, expected_version=0, autonomy_level=3, approval_routing=routing)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_policy"
    assert db_session.scalar(select(WorkspacePolicyRecord)) is None


def test_members_cannot_set_routing(client, team, db_session):
    hs, ws = team
    assert put(client, hs["member"], ws, expected_version=0, autonomy_level=3, approval_routing={"high": "owner"}).status_code == 403


@pytest.mark.parametrize("bad", [{"high": "admin"}, {"low": "owner"}, {"high": 1}])
def test_a_malformed_stored_routing_fails_closed(bad):
    rec = WorkspacePolicyRecord(workspace_id="w", updated_by="u", version=1, autonomy_level=3, disabled_tools=[],
                                approval_required_tools=[], risk_overrides={}, approval_routing=bad)
    with pytest.raises(ValueError):
        to_workspace_policy(rec)
    assert to_workspace_policy(None).approval_routing == {}


def test_pure_rule_only_adds_a_requirement():
    pol = WorkspacePolicy(approval_routing={"high": "owner"})
    assert extra_decider_permission(RiskLevel.HIGH, pol) == "owner:approve"
    assert extra_decider_permission(RiskLevel.MEDIUM, pol) is None and extra_decider_permission(RiskLevel.HIGH, None) is None


# ------------------------------------------------------------------ real approval service
def test_baseline_admin_can_decide_a_high_risk_approval(client, team, db_session):
    hs, ws = team
    put(client, hs["admin"], ws, expected_version=0, autonomy_level=3, risk_overrides={"system.ping": "high"})
    ex = kernel_for(client, db_session).submit(principal(db_session, "member@x.com", ws["id"]), "system.ping", {})
    a = svc(client, db_session).decide(ex.approvals[0].id, principal(db_session, "admin@x.com", ws["id"]), approve=True)
    assert a.status == ApprovalStatus.APPROVED


def test_routed_high_risk_needs_the_owner_and_an_admin_is_refused_and_it_stays_pending(client, team, db_session):
    ex = parked(client, team, db_session, {"high": "owner"})
    s = svc(client, db_session)
    with pytest.raises(ApprovalPermissionError):
        s.decide(ex.approvals[0].id, principal(db_session, "admin@x.com", team[1]["id"]), approve=True)
    db_session.refresh(ex)
    assert ex.approvals[0].status == ApprovalStatus.PENDING and ex.status == ExecutionStatus.AWAITING_APPROVAL
    ev = db_session.scalar(select(SystemEvent).where(SystemEvent.event_type == "approval.decision_refused"))
    assert ev.payload["reason"] == "approval_routing"
    a = s.decide(ex.approvals[0].id, principal(db_session, "owner@x.com", team[1]["id"]), approve=True)
    assert a.status == ApprovalStatus.APPROVED
    assert kernel_for(client, db_session).execute_approved(principal(db_session, "member@x.com", team[1]["id"]), ex.id).status == ExecutionStatus.SUCCEEDED


def test_an_admin_cannot_even_reject_a_routed_approval(client, team, db_session):
    ex = parked(client, team, db_session, {"high": "owner"})
    with pytest.raises(ApprovalPermissionError):
        svc(client, db_session).decide(ex.approvals[0].id, principal(db_session, "admin@x.com", team[1]["id"]), approve=False)


def test_routing_only_applies_to_the_routed_risk_level(client, team, db_session):
    ex = parked(client, team, db_session, {"high": "owner"}, override="medium")
    a = svc(client, db_session).decide(ex.approvals[0].id, principal(db_session, "admin@x.com", team[1]["id"]), approve=True)
    assert a.status == ApprovalStatus.APPROVED


def test_routing_adds_to_existing_checks_the_requester_still_cannot_self_approve(client, team, db_session):
    hs, ws = team
    put(client, hs["admin"], ws, expected_version=0, autonomy_level=3, risk_overrides={"system.ping": "high"}, approval_routing={"high": "owner"})
    ex = kernel_for(client, db_session).submit(principal(db_session, "owner@x.com", ws["id"]), "system.ping", {})
    with pytest.raises(ApprovalPermissionError):
        svc(client, db_session).decide(ex.approvals[0].id, principal(db_session, "owner@x.com", ws["id"]), approve=True)


def test_another_workspaces_routing_does_not_apply(client, team, db_session):
    from tests.test_workspace_connectors import mkws
    hs, ws = team
    other = mkws(client, hs["outsider"])
    put(client, hs["outsider"], other, expected_version=0, autonomy_level=3, approval_routing={"high": "owner", "medium": "owner"})
    ex = parked(client, team, db_session, {}, override="high")
    assert svc(client, db_session).decide(ex.approvals[0].id, principal(db_session, "admin@x.com", ws["id"]), approve=True).status == ApprovalStatus.APPROVED


# ------------------------------------------------------------------ closing guard
def test_every_approval_service_in_app_has_a_policy_provider_except_system_withdrawals():
    root = pathlib.Path(__file__).resolve().parents[1] / "app"
    seen, offenders = 0, []
    for f in root.rglob("*.py"):
        rel = f.relative_to(root).as_posix()
        for n, line in enumerate(f.read_text().splitlines(), 1):
            if re.search(r"(?<![A-Za-z_])ApprovalService\(", line) and not line.lstrip().startswith(("class ", "#")):
                seen += 1
                if "policy_provider" not in line and rel != "agents/runs.py":    # runs.py only withdraws (rejects) approvals: tighter, never looser
                    offenders.append(f"{rel}:{n}")
    assert seen >= 2, "guard found no ApprovalService constructions: its pattern is broken"
    assert offenders == []
