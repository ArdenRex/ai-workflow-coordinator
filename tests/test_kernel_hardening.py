"""Step 2 closing tests: architectural guard + remaining bypass/edge cases."""
import pathlib
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.kernel.approvals import ApprovalService
from app.kernel.errors import ExecutionStateError, PolicyDeniedError, ToolInputError
from app.kernel.policy import WorkspacePolicy
from app.models import ApprovalStatus, ExecutionStatus, RiskLevel, SystemEvent
from tests.test_execution_service import P, Rig, boss, high, types  # reuse the rig

pytestmark = pytest.mark.usefixtures("seed_workspaces")


@pytest.fixture
def rig(db_session):
    return Rig(db_session)


def approve(rig, ex):
    ApprovalService(rig.db).decide(ex.approvals[0].id, boss(), approve=True)


# ---- architecture: handlers are only ever invoked by the execution service
def test_only_execution_service_invokes_tool_handlers():
    root = pathlib.Path(__file__).resolve().parents[1] / "app"
    offenders = [str(f.relative_to(root)) for f in root.rglob("*.py")
                 if f.name != "service.py" and (".handler(" in f.read_text() or "tool.handler" in f.read_text())]
    assert offenders == []


# ---- approval is bound to the exact input
def test_BYPASS_input_changed_after_approval_is_blocked(rig):
    high(rig)
    ex = rig.svc.submit(P(), "aceden.customer.delete", {"n": 1})
    approve(rig, ex)
    ex.input = {"n": 999}                       # valid but different from what was approved
    rig.db.commit()
    with pytest.raises(ExecutionStateError):
        rig.svc.execute_approved(P(), ex.id)
    assert rig.calls == []
    denied = rig.db.scalar(select(SystemEvent).where(SystemEvent.event_type == "execution.denied"))
    assert denied.payload["reason"] == "approved_input_mismatch"


def test_BYPASS_missing_request_record_blocks_run(rig):
    high(rig)
    ex = rig.svc.submit(P(), "aceden.customer.delete", {})
    approve(rig, ex)
    rig.db.delete(rig.db.scalar(select(SystemEvent).where(SystemEvent.event_type == "approval.requested")))
    rig.db.commit()
    with pytest.raises(ExecutionStateError):
        rig.svc.execute_approved(P(), ex.id)


def test_tampered_invalid_input_never_runs(rig):
    high(rig)
    ex = rig.svc.submit(P(), "aceden.customer.delete", {})
    approve(rig, ex)
    ex.input = {"n": "bad"}
    rig.db.commit()
    with pytest.raises((ExecutionStateError, ToolInputError)):
        rig.svc.execute_approved(P(), ex.id)
    assert rig.calls == []


# ---- agents / scope
def test_agent_cannot_exceed_its_scope_even_if_user_can(rig):
    rig.tool()
    p = P(agent="support", agent_scope=frozenset({"email:*"}))
    with pytest.raises(PolicyDeniedError) as e:
        rig.svc.submit(p, "aceden.customer.read", {})
    assert e.value.reason_code == "agent_scope_denied" and rig.calls == []


# ---- risk policy at the service level
def test_medium_risk_needs_approval_by_default_and_auto_when_workspace_allows(rig):
    rig.tool(id="crm.lead.create", perm="lead:write", risk=RiskLevel.MEDIUM)
    assert rig.svc.submit(P(), "crm.lead.create", {}).status == ExecutionStatus.AWAITING_APPROVAL
    rig.policy = WorkspacePolicy(auto_execute_max_risk=RiskLevel.MEDIUM)
    assert rig.svc.submit(P(), "crm.lead.create", {"n": 2}).status == ExecutionStatus.SUCCEEDED


def test_high_risk_still_needs_approval_under_most_permissive_policy(rig):
    high(rig)
    rig.policy = WorkspacePolicy(auto_execute_max_risk=RiskLevel.HIGH)
    assert rig.svc.submit(P(), "aceden.customer.delete", {}).status == ExecutionStatus.AWAITING_APPROVAL
    assert rig.calls == []


# ---- lifecycle edges
def test_expired_approval_cannot_execute(rig):
    high(rig)
    ex = rig.svc.submit(P(), "aceden.customer.delete", {})
    ex.approvals[0].expires_at = ex.approvals[0].created_at - timedelta(hours=1)
    rig.db.commit()
    ApprovalService(rig.db).expire_stale("w1")
    assert ex.status == ExecutionStatus.EXPIRED
    with pytest.raises(ExecutionStateError):
        rig.svc.execute_approved(P(), ex.id)
    assert rig.calls == []


def test_failed_execution_cannot_be_rerun_without_new_submission(rig):
    def boom(ctx, d):
        raise RuntimeError("x")
    rig.tool(id="aceden.customer.delete", perm="customer:delete", risk=RiskLevel.HIGH, handler=boom)
    ex = rig.svc.submit(P(), "aceden.customer.delete", {})
    approve(rig, ex)
    assert rig.svc.execute_approved(P(), ex.id).status == ExecutionStatus.FAILED
    assert ex.approvals[0].status == ApprovalStatus.APPROVED   # not EXECUTED: it did not succeed
    with pytest.raises(ExecutionStateError):
        rig.svc.execute_approved(P(), ex.id)


def test_claim_is_exclusive(rig):
    rig.tool()
    ex = rig.svc.submit(P(), "aceden.customer.read", {})          # already SUCCEEDED
    assert rig.svc._claim(ex) == "lost"


def test_idempotent_replay_of_pending_approval_creates_no_second_approval(rig):
    high(rig)
    a = rig.svc.submit(P(), "aceden.customer.delete", {}, idempotency_key="z")
    b = rig.svc.submit(P(), "aceden.customer.delete", {}, idempotency_key="z")
    assert a.id == b.id and len(a.approvals) == 1


# ---- isolation on reads
def test_other_workspace_cannot_read_execution_or_audit(rig):
    rig.tool()
    ex = rig.svc.submit(P(), "aceden.customer.read", {})
    with pytest.raises(ExecutionStateError):
        rig.svc.get(ex.id, "w2")
    with pytest.raises(ExecutionStateError):
        rig.svc.audit_trail(ex.id, "w2")


def test_audit_trail_is_ordered_and_complete(rig):
    high(rig)
    ex = rig.svc.submit(P(), "aceden.customer.delete", {})
    approve(rig, ex)
    rig.svc.execute_approved(P(), ex.id)
    assert types(rig, ex)[0] == "execution.created" and types(rig, ex)[-1] == "approval.executed"
