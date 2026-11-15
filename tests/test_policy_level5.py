"""Substep 12.5: autonomy level 5 = level 4 plus mandatory guardrails (cap, escalation rule, owner-routed high-risk approvals). No extra authority."""
import pytest
from sqlalchemy import select

from app.kernel.policy_store import to_workspace_policy
from app.models.enums import ApprovalStatus, ExecutionStatus
from app.models.policy import WorkspacePolicyRecord
from tests.test_policy_execution_limit import kernel_for
from tests.test_policy_level4 import CAP, tools  # noqa: F401
from tests.test_policy_store import put, url
from tests.test_workspace_connectors import principal, team  # noqa: F401

ESC = {"threshold": 3, "window_seconds": 3600}
ROUTE = {"high": "owner"}


def l5(client, h, ws, **kw):
    body = dict(expected_version=kw.pop("v", 0), autonomy_level=5, execution_limit=CAP, escalation=ESC, approval_routing=ROUTE)
    body.update(kw)
    return put(client, h, ws, **body)


def test_level_5_is_set_with_all_guardrails_and_returned(client, team, tools):
    hs, ws = team
    r = l5(client, hs["admin"], ws, auto_execute_tools=["t.med"])
    assert r.status_code == 200
    j = r.json()
    assert (j["autonomy_level"], j["autonomy_name"], j["auto_execute_tools"]) == (5, "autonomous", ["t.med"])
    assert (j["execution_limit"], j["escalation"], j["approval_routing"]) == (CAP, ESC, ROUTE)


@pytest.mark.parametrize("drop", ["execution_limit", "escalation", "approval_routing"])
def test_each_missing_guardrail_refuses_level_5_and_changes_nothing(client, team, db_session, tools, drop):
    hs, ws = team
    body = dict(expected_version=0, autonomy_level=5, execution_limit=CAP, escalation=ESC, approval_routing=ROUTE)
    del body[drop]
    r = put(client, hs["admin"], ws, **body)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_policy"
    assert db_session.scalar(select(WorkspacePolicyRecord)) is None


def test_routing_medium_only_is_not_enough_for_level_5(client, team, db_session, tools):
    hs, ws = team
    assert l5(client, hs["admin"], ws, approval_routing={"medium": "owner"}).status_code == 422


def test_members_cannot_set_level_5(client, team, tools):
    hs, ws = team
    assert l5(client, hs["member"], ws).status_code == 403


def test_level_5_grants_nothing_beyond_level_4(client, team, db_session, tools):
    hs, ws = team
    me, k = principal(db_session, "member@x.com", ws["id"]), kernel_for(client, db_session)
    assert l5(client, hs["admin"], ws, auto_execute_tools=["t.med"]).status_code == 200
    assert k.submit(me, "t.med", {"message": "a"}).status == ExecutionStatus.SUCCEEDED
    for tool in ("t.med2", "t.high", "t.medapp"):                       # unlisted, high and own-approval tools all still park
        assert k.submit(me, tool, {}).status == ExecutionStatus.AWAITING_APPROVAL
    assert l5(client, hs["admin"], ws, v=1, auto_execute_tools=["t.high"]).status_code == 422     # the allowlist rules are the same


def test_level_5_without_an_allowlist_is_baseline_execution(client, team, db_session, tools):
    hs, ws = team
    me, k = principal(db_session, "member@x.com", ws["id"]), kernel_for(client, db_session)
    assert l5(client, hs["admin"], ws).status_code == 200
    assert k.submit(me, "t.med", {}).status == ExecutionStatus.AWAITING_APPROVAL


def test_level_5_high_risk_approvals_are_owner_only_and_the_cap_still_binds(client, team, db_session, tools):
    from app.kernel.approvals import ApprovalService
    from app.kernel.errors import ApprovalPermissionError, PolicyDeniedError
    from app.kernel.policy_store import db_policy_provider
    from tests.test_policy_store import factory
    hs, ws = team
    me, k = principal(db_session, "member@x.com", ws["id"]), kernel_for(client, db_session)
    assert l5(client, hs["admin"], ws, auto_execute_tools=["t.med"], execution_limit={"max_executions": 1, "window_seconds": 3600}).status_code == 200
    ex = k.submit(me, "t.high", {})
    svc = ApprovalService(db_session, policy_provider=db_policy_provider(factory(db_session)))
    with pytest.raises(ApprovalPermissionError):
        svc.decide(ex.approvals[0].id, principal(db_session, "admin@x.com", ws["id"]), approve=True)
    assert svc.decide(ex.approvals[0].id, principal(db_session, "owner@x.com", ws["id"]), approve=True).status == ApprovalStatus.APPROVED
    assert k.submit(me, "t.med", {"message": "1"}).status == ExecutionStatus.SUCCEEDED
    with pytest.raises(PolicyDeniedError):
        k.submit(me, "t.med", {"message": "2"})


@pytest.mark.parametrize("limit,esc,route", [(None, ESC, ROUTE), (CAP, None, ROUTE), (CAP, ESC, {}), (CAP, ESC, {"medium": "owner"})])
def test_a_stored_level_5_missing_a_guardrail_fails_closed(limit, esc, route):
    rec = WorkspacePolicyRecord(workspace_id="w", updated_by="u", version=1, autonomy_level=5, disabled_tools=[], approval_required_tools=[],
                                risk_overrides={}, execution_limit=limit, escalation=esc, approval_routing=route, auto_execute_tools=[])
    with pytest.raises(ValueError):
        to_workspace_policy(rec)
