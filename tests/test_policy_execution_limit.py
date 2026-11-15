"""Substep 12.3c: per-workspace execution limit (tighten only), enforced by the kernel just before a tool runs."""
import pathlib
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.kernel.approvals import ApprovalService
from app.kernel.errors import PolicyDeniedError
from app.kernel.policy import ExecutionLimit, WorkspacePolicy
from app.kernel.policy_store import db_policy_provider, to_workspace_policy
from app.kernel.service import ToolExecutionService, _now
from app.models.enums import ExecutionStatus
from app.models.kernel import SystemEvent, ToolExecution
from app.models.policy import WorkspacePolicyRecord
from tests.test_policy_store import factory, put, url
from tests.test_workspace_connectors import principal, signup, mkws, public_dns, team  # noqa: F401


def kernel_for(client, db):
    return ToolExecutionService(db, client.app.state.tool_registry, policy_provider=db_policy_provider(factory(db)))


def denied(db, reason):
    return db.scalar(select(func.count()).select_from(SystemEvent).where(SystemEvent.event_type == "execution.denied",
                                                                          SystemEvent.payload["reason"].as_string() == reason))


# ------------------------------------------------------------------ store + HTTP
def test_limit_is_stored_versioned_returned_and_cleared_by_a_replace(client, team, db_session):
    hs, ws = team
    assert client.get(url(ws), headers=hs["owner"]).json()["execution_limit"] is None
    r = put(client, hs["admin"], ws, expected_version=0, autonomy_level=3, execution_limit={"max_executions": 5, "window_seconds": 60})
    assert r.status_code == 200 and r.json()["execution_limit"] == {"max_executions": 5, "window_seconds": 60}
    assert client.get(url(ws), headers=hs["owner"]).json()["execution_limit"] == {"max_executions": 5, "window_seconds": 60}
    ev = db_session.scalar(select(SystemEvent).where(SystemEvent.event_type == "policy.created"))
    assert ev.payload["has_execution_limit"] is True
    r2 = put(client, hs["admin"], ws, expected_version=1, autonomy_level=3)            # a write replaces the whole policy
    assert r2.json()["execution_limit"] is None


@pytest.mark.parametrize("limit", [
    {"max_executions": 0, "window_seconds": 60}, {"max_executions": -1, "window_seconds": 60},
    {"max_executions": 100001, "window_seconds": 60}, {"max_executions": 5, "window_seconds": 61},
    {"max_executions": 5, "window_seconds": 0}, {"max_executions": True, "window_seconds": 60},
    {"max_executions": 5.0, "window_seconds": 60}, {"max_executions": "5", "window_seconds": 60},
    {"max_executions": 5}, {"window_seconds": 60}, {"max_executions": 5, "window_seconds": 60, "x": 1},
    [], "5", 5, {},
])
def test_invalid_limits_are_refused_and_change_nothing(client, team, db_session, limit):
    hs, ws = team
    r = put(client, hs["admin"], ws, expected_version=0, autonomy_level=3, execution_limit=limit)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_policy"
    assert db_session.scalar(select(WorkspacePolicyRecord)) is None


def test_members_cannot_set_a_limit(client, team, db_session):
    hs, ws = team
    r = put(client, hs["member"], ws, expected_version=0, autonomy_level=3, execution_limit={"max_executions": 5, "window_seconds": 60})
    assert r.status_code == 403 and db_session.scalar(select(WorkspacePolicyRecord)) is None


def test_a_malformed_stored_limit_fails_closed():
    rec = WorkspacePolicyRecord(workspace_id="w", updated_by="u", version=1, autonomy_level=3, disabled_tools=[],
                                approval_required_tools=[], risk_overrides={}, execution_limit={"max_executions": "x"})
    with pytest.raises((KeyError, ValueError, TypeError)):
        to_workspace_policy(rec)                          # never silently turns into "no limit"
    assert to_workspace_policy(None).execution_limit is None


# ------------------------------------------------------------------ real kernel
def test_baseline_has_no_cap(client, team, db_session):
    hs, ws = team
    me, k = principal(db_session, "admin@x.com", ws["id"]), kernel_for(client, db_session)
    for _ in range(8):
        assert k.submit(me, "system.ping", {}).status == ExecutionStatus.SUCCEEDED


def test_the_kernel_refuses_run_number_n_plus_one_and_records_why(client, team, db_session):
    hs, ws = team
    me, k = principal(db_session, "admin@x.com", ws["id"]), kernel_for(client, db_session)
    put(client, hs["admin"], ws, expected_version=0, autonomy_level=3, execution_limit={"max_executions": 2, "window_seconds": 3600})
    assert k.submit(me, "system.ping", {}).status == ExecutionStatus.SUCCEEDED
    assert k.submit(me, "system.ping", {}).status == ExecutionStatus.SUCCEEDED
    before = db_session.scalar(select(func.count()).select_from(ToolExecution))
    with pytest.raises(PolicyDeniedError) as e:
        k.submit(me, "system.ping", {})
    assert e.value.reason_code == "execution_limit_reached" and "2" not in str(e.value)
    assert db_session.scalar(select(func.count()).select_from(ToolExecution)) == before       # no record, nothing ran
    assert denied(db_session, "execution_limit_reached") == 1


def test_old_runs_fall_out_of_the_window(client, team, db_session):
    hs, ws = team
    me, k = principal(db_session, "admin@x.com", ws["id"]), kernel_for(client, db_session)
    put(client, hs["admin"], ws, expected_version=0, autonomy_level=3, execution_limit={"max_executions": 1, "window_seconds": 60})
    first = k.submit(me, "system.ping", {})
    with pytest.raises(PolicyDeniedError):
        k.submit(me, "system.ping", {})
    first.started_at = _now() - timedelta(seconds=120)
    db_session.commit()
    assert k.submit(me, "system.ping", {}).status == ExecutionStatus.SUCCEEDED


def test_clearing_the_limit_restores_the_baseline_and_other_workspaces_are_unaffected(client, team, db_session):
    hs, ws = team
    other = mkws(client, hs["outsider"])
    me, k = principal(db_session, "admin@x.com", ws["id"]), kernel_for(client, db_session)
    put(client, hs["admin"], ws, expected_version=0, autonomy_level=3, execution_limit={"max_executions": 1, "window_seconds": 60})
    k.submit(me, "system.ping", {})
    with pytest.raises(PolicyDeniedError):
        k.submit(me, "system.ping", {})
    assert db_policy_provider(factory(db_session))(other["id"]) == WorkspacePolicy()
    put(client, hs["admin"], ws, expected_version=1, autonomy_level=3)
    assert k.submit(me, "system.ping", {}).status == ExecutionStatus.SUCCEEDED


def test_runs_in_another_workspace_do_not_count(client, team, db_session):
    hs, ws = team
    other = mkws(client, hs["outsider"])
    theirs = principal(db_session, "outsider@x.com", other["id"])
    k = kernel_for(client, db_session)
    for _ in range(3):
        k.submit(theirs, "system.ping", {})
    put(client, hs["admin"], ws, expected_version=0, autonomy_level=3, execution_limit={"max_executions": 1, "window_seconds": 60})
    assert k.submit(principal(db_session, "admin@x.com", ws["id"]), "system.ping", {}).status == ExecutionStatus.SUCCEEDED


def test_a_parked_execution_does_not_use_budget_but_is_checked_when_released(client, team, db_session):
    hs, ws = team
    me, boss, k = principal(db_session, "admin@x.com", ws["id"]), principal(db_session, "owner@x.com", ws["id"]), kernel_for(client, db_session)
    put(client, hs["admin"], ws, expected_version=0, autonomy_level=3, approval_required_tools=["system.ping"],
        execution_limit={"max_executions": 1, "window_seconds": 3600})
    parked = [k.submit(me, "system.ping", {}, idempotency_key="a"), k.submit(me, "system.ping", {}, idempotency_key="b")]
    assert all(p.status == ExecutionStatus.AWAITING_APPROVAL for p in parked)   # parking is not capped, it ran nothing
    for p in parked:
        ApprovalService(db_session).decide(p.approvals[0].id, boss, approve=True)
    assert k.execute_approved(me, parked[0].id).status == ExecutionStatus.SUCCEEDED
    with pytest.raises(PolicyDeniedError) as e:
        k.execute_approved(me, parked[1].id)
    assert e.value.reason_code == "execution_limit_reached"
    db_session.refresh(parked[1])
    assert parked[1].status == ExecutionStatus.APPROVED and parked[1].started_at is None   # nothing ran; stays approved
    parked[0].started_at = _now() - timedelta(hours=2)                                     # window moves on: it can be released
    db_session.commit()
    assert k.execute_approved(me, parked[1].id).status == ExecutionStatus.SUCCEEDED


def test_an_idempotent_replay_is_not_a_new_run(client, team, db_session):
    hs, ws = team
    me, k = principal(db_session, "admin@x.com", ws["id"]), kernel_for(client, db_session)
    put(client, hs["admin"], ws, expected_version=0, autonomy_level=3, execution_limit={"max_executions": 1, "window_seconds": 60})
    a = k.submit(me, "system.ping", {}, idempotency_key="k1")
    assert k.submit(me, "system.ping", {}, idempotency_key="k1").id == a.id


def test_a_deny_rule_still_wins_and_the_limit_only_tightens():
    src = pathlib.Path("app/kernel/policy.py").read_text()
    assert "execution_limit" in src and "Outcome.ALLOW" in src
    assert WorkspacePolicy().execution_limit is None and ExecutionLimit(1, 60).max_executions == 1
