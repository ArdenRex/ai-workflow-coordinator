"""Substep 12.3d: escalation rule (tighten only). Recent failures/denials make unattended runs need approval."""
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.kernel.approvals import ApprovalService
from app.kernel.errors import ToolNotFoundError
from app.kernel.policy import EscalationRule, WorkspacePolicy
from app.kernel.policy_store import to_workspace_policy
from app.kernel.service import ToolExecutionService, _now
from app.models.enums import ExecutionStatus, RiskLevel
from app.models.kernel import SystemEvent, ToolExecution
from app.models.policy import WorkspacePolicyRecord
from tests.test_policy_execution_limit import kernel_for
from tests.test_policy_store import put, url
from tests.test_workspace_connectors import principal, mkws, team  # noqa: F401

RULE = {"threshold": 2, "window_seconds": 3600}


def fail_rows(db, ws, n, *, age=0):
    for _ in range(n):
        t = _now() - timedelta(seconds=age)
        db.add(ToolExecution(workspace_id=ws, tool_id="system.ping", requested_by="u", risk_level=RiskLevel.LOW,
                             status=ExecutionStatus.FAILED, input={}, started_at=t, finished_at=t, error="x"))
    db.commit()


def deny(k, me, n):
    for _ in range(n):
        with pytest.raises(ToolNotFoundError):
            k.submit(me, "no.such.tool", {})


# ------------------------------------------------------------------ store + HTTP
def test_escalation_is_stored_returned_audited_and_cleared_by_a_replace(client, team, db_session):
    hs, ws = team
    assert client.get(url(ws), headers=hs["owner"]).json()["escalation"] is None
    r = put(client, hs["admin"], ws, expected_version=0, autonomy_level=3, escalation=RULE)
    assert r.status_code == 200 and r.json()["escalation"] == RULE
    assert db_session.scalar(select(SystemEvent).where(SystemEvent.event_type == "policy.created")).payload["has_escalation"] is True
    assert put(client, hs["admin"], ws, expected_version=1, autonomy_level=3).json()["escalation"] is None


@pytest.mark.parametrize("rule", [
    {"threshold": 0, "window_seconds": 60}, {"threshold": 1001, "window_seconds": 60}, {"threshold": 2, "window_seconds": 61},
    {"threshold": True, "window_seconds": 60}, {"threshold": 2.0, "window_seconds": 60}, {"threshold": "2", "window_seconds": 60},
    {"threshold": 2}, {"window_seconds": 60}, {"threshold": 2, "window_seconds": 60, "x": 1}, [], "2", 2, {},
])
def test_invalid_escalation_is_refused_and_changes_nothing(client, team, db_session, rule):
    hs, ws = team
    r = put(client, hs["admin"], ws, expected_version=0, autonomy_level=3, escalation=rule)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_policy"
    assert db_session.scalar(select(WorkspacePolicyRecord)) is None


def test_members_cannot_set_escalation(client, team, db_session):
    hs, ws = team
    assert put(client, hs["member"], ws, expected_version=0, autonomy_level=3, escalation=RULE).status_code == 403


def test_a_malformed_stored_escalation_fails_closed():
    rec = WorkspacePolicyRecord(workspace_id="w", updated_by="u", version=1, autonomy_level=3, disabled_tools=[],
                                approval_required_tools=[], risk_overrides={}, escalation={"threshold": "x"})
    with pytest.raises((KeyError, ValueError, TypeError)):
        to_workspace_policy(rec)
    assert to_workspace_policy(None).escalation is None
    assert to_workspace_policy(None) == WorkspacePolicy()


# ------------------------------------------------------------------ real kernel
def test_baseline_never_escalates_however_many_failures(client, team, db_session):
    hs, ws = team
    me, k = principal(db_session, "admin@x.com", ws["id"]), kernel_for(client, db_session)
    fail_rows(db_session, ws["id"], 5)
    assert k.submit(me, "system.ping", {}).status == ExecutionStatus.SUCCEEDED


def test_below_the_threshold_runs_unattended(client, team, db_session):
    hs, ws = team
    me, k = principal(db_session, "admin@x.com", ws["id"]), kernel_for(client, db_session)
    put(client, hs["admin"], ws, expected_version=0, autonomy_level=3, escalation=RULE)
    fail_rows(db_session, ws["id"], 1)
    assert k.submit(me, "system.ping", {}).status == ExecutionStatus.SUCCEEDED


def test_failures_at_the_threshold_park_the_next_run_for_approval(client, team, db_session):
    hs, ws = team
    me, k = principal(db_session, "admin@x.com", ws["id"]), kernel_for(client, db_session)
    put(client, hs["admin"], ws, expected_version=0, autonomy_level=3, escalation=RULE)
    fail_rows(db_session, ws["id"], 2)
    ex = k.submit(me, "system.ping", {})
    assert ex.status == ExecutionStatus.AWAITING_APPROVAL and ex.started_at is None        # nothing ran
    ev = db_session.scalar(select(SystemEvent).where(SystemEvent.event_type == "execution.created", SystemEvent.execution_id == ex.id))
    assert ev.payload["policy"] == "escalation_threshold"


def test_denied_attempts_count_too(client, team, db_session):
    hs, ws = team
    me, k = principal(db_session, "admin@x.com", ws["id"]), kernel_for(client, db_session)
    put(client, hs["admin"], ws, expected_version=0, autonomy_level=3, escalation=RULE)
    deny(k, me, 2)
    assert k.submit(me, "system.ping", {}).status == ExecutionStatus.AWAITING_APPROVAL


def test_old_failures_fall_out_of_the_window(client, team, db_session):
    hs, ws = team
    me, k = principal(db_session, "admin@x.com", ws["id"]), kernel_for(client, db_session)
    put(client, hs["admin"], ws, expected_version=0, autonomy_level=3, escalation={"threshold": 2, "window_seconds": 60})
    fail_rows(db_session, ws["id"], 3, age=600)
    assert k.submit(me, "system.ping", {}).status == ExecutionStatus.SUCCEEDED


def test_other_workspaces_failures_do_not_count(client, team, db_session):
    hs, ws = team
    other = mkws(client, hs["outsider"])
    me, k = principal(db_session, "admin@x.com", ws["id"]), kernel_for(client, db_session)
    put(client, hs["admin"], ws, expected_version=0, autonomy_level=3, escalation=RULE)
    fail_rows(db_session, other["id"], 5)
    assert k.submit(me, "system.ping", {}).status == ExecutionStatus.SUCCEEDED


def test_an_escalated_run_still_works_after_a_human_approves_it(client, team, db_session):
    hs, ws = team
    me, boss, k = principal(db_session, "admin@x.com", ws["id"]), principal(db_session, "owner@x.com", ws["id"]), kernel_for(client, db_session)
    put(client, hs["admin"], ws, expected_version=0, autonomy_level=3, escalation=RULE)
    fail_rows(db_session, ws["id"], 2)
    ex = k.submit(me, "system.ping", {})
    ApprovalService(db_session).decide(ex.approvals[0].id, boss, approve=True)
    assert k.execute_approved(me, ex.id).status == ExecutionStatus.SUCCEEDED               # a human already looked


def test_clearing_escalation_restores_the_baseline(client, team, db_session):
    hs, ws = team
    me, k = principal(db_session, "admin@x.com", ws["id"]), kernel_for(client, db_session)
    put(client, hs["admin"], ws, expected_version=0, autonomy_level=3, escalation=RULE)
    fail_rows(db_session, ws["id"], 2)
    assert k.submit(me, "system.ping", {}).status == ExecutionStatus.AWAITING_APPROVAL
    put(client, hs["admin"], ws, expected_version=1, autonomy_level=3)
    assert k.submit(me, "system.ping", {}).status == ExecutionStatus.SUCCEEDED


def test_escalation_never_loosens_a_deny_and_never_creates_a_run(client, team, db_session):
    hs, ws = team
    me, k = principal(db_session, "admin@x.com", ws["id"]), kernel_for(client, db_session)
    put(client, hs["admin"], ws, expected_version=0, autonomy_level=3, escalation=RULE, disabled_tools=["system.ping"])
    fail_rows(db_session, ws["id"], 2)
    before = db_session.scalar(select(func.count()).select_from(ToolExecution).where(ToolExecution.status == ExecutionStatus.SUCCEEDED))
    with pytest.raises(Exception) as e:
        k.submit(me, "system.ping", {})
    assert getattr(e.value, "reason_code", "") == "tool_disabled"
    assert db_session.scalar(select(func.count()).select_from(ToolExecution).where(ToolExecution.status == ExecutionStatus.SUCCEEDED)) == before
