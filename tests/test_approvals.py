from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.kernel.approvals import ApprovalService
from app.kernel.audit import redact
from app.kernel.errors import (ApprovalExpiredError, ApprovalNotFoundError,
                               ApprovalPermissionError, ApprovalStateError)
from app.kernel.permissions import Principal
from app.models import ApprovalStatus, ExecutionStatus, RiskLevel, SystemEvent, ToolExecution

pytestmark = pytest.mark.usefixtures("seed_workspaces")

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def mk_exec(db, ws="w1", by="requester"):
    e = ToolExecution(workspace_id=ws, tool_id="crm.lead.create", requested_by=by,
                      risk_level=RiskLevel.HIGH, input={})
    db.add(e)
    db.commit()
    return e


def approver(uid="boss", ws="w1", perms=("approval:decide",), **kw):
    return Principal(user_id=uid, workspace_id=ws, permissions=frozenset(perms), **kw)


def events(db):
    return [e.event_type for e in db.scalars(select(SystemEvent).order_by(SystemEvent.created_at))]


def test_request_sets_pending_and_audits(db_session):
    e = mk_exec(db_session)
    a = ApprovalService(db_session).request(e, now=NOW)
    assert a.status == ApprovalStatus.PENDING and e.status == ExecutionStatus.AWAITING_APPROVAL
    assert a.expires_at is not None and "approval.requested" in events(db_session)


def test_approve_flow(db_session):
    svc = ApprovalService(db_session)
    e = mk_exec(db_session)
    a = svc.request(e, now=NOW)
    a = svc.decide(a.id, approver(), approve=True, reason="ok", now=NOW)
    assert a.status == ApprovalStatus.APPROVED and a.decided_by == "boss"
    assert e.status == ExecutionStatus.APPROVED
    svc.mark_executed(a)
    assert a.status == ApprovalStatus.EXECUTED
    assert events(db_session) == ["approval.requested", "approval.approved", "approval.executed"]


def test_reject_flow(db_session):
    svc = ApprovalService(db_session)
    e = mk_exec(db_session)
    a = svc.decide(svc.request(e, now=NOW).id, approver(), approve=False, reason="no", now=NOW)
    assert a.status == ApprovalStatus.REJECTED and e.status == ExecutionStatus.REJECTED


def test_self_approval_blocked_by_default(db_session):
    svc = ApprovalService(db_session)
    a = svc.request(mk_exec(db_session, by="boss"), now=NOW)
    with pytest.raises(ApprovalPermissionError):
        svc.decide(a.id, approver(uid="boss"), approve=True, now=NOW)


def test_self_approval_only_if_explicitly_enabled(db_session):
    svc = ApprovalService(db_session, allow_self_approval=True)
    a = svc.request(mk_exec(db_session, by="boss"), now=NOW)
    assert svc.decide(a.id, approver(uid="boss"), approve=True, now=NOW).status == ApprovalStatus.APPROVED


def test_agent_can_never_decide_even_with_all_permissions(db_session):
    svc = ApprovalService(db_session)
    a = svc.request(mk_exec(db_session), now=NOW)
    ai = approver(uid="boss", perms=("*",), agent="sales", agent_scope=frozenset({"*"}))
    with pytest.raises(ApprovalPermissionError):
        svc.decide(a.id, ai, approve=True, now=NOW)
    assert a.status == ApprovalStatus.PENDING


def test_missing_permission_blocked(db_session):
    svc = ApprovalService(db_session)
    a = svc.request(mk_exec(db_session), now=NOW)
    with pytest.raises(ApprovalPermissionError):
        svc.decide(a.id, approver(perms=("customer:read",)), approve=True, now=NOW)


def test_cross_workspace_decision_is_not_found(db_session):
    svc = ApprovalService(db_session)
    a = svc.request(mk_exec(db_session, ws="w1"), now=NOW)
    with pytest.raises(ApprovalNotFoundError):
        svc.decide(a.id, approver(ws="w2"), approve=True, now=NOW)
    assert a.status == ApprovalStatus.PENDING


def test_double_decision_rejected_and_terminal_immutable(db_session):
    svc = ApprovalService(db_session)
    a = svc.request(mk_exec(db_session), now=NOW)
    svc.decide(a.id, approver(), approve=True, now=NOW)
    with pytest.raises(ApprovalStateError):
        svc.decide(a.id, approver(uid="other"), approve=False, now=NOW)
    assert svc.get(a.id, "w1").status == ApprovalStatus.APPROVED


def test_decide_after_expiry_expires_it(db_session):
    svc = ApprovalService(db_session, ttl=timedelta(hours=1))
    e = mk_exec(db_session)
    a = svc.request(e, now=NOW)
    with pytest.raises(ApprovalExpiredError):
        svc.decide(a.id, approver(), approve=True, now=NOW + timedelta(hours=2))
    assert a.status == ApprovalStatus.EXPIRED and e.status == ExecutionStatus.EXPIRED
    with pytest.raises(ApprovalStateError):  # cannot revive
        svc.decide(a.id, approver(), approve=True, now=NOW)


def test_expire_stale_is_workspace_scoped(db_session):
    svc = ApprovalService(db_session, ttl=timedelta(hours=1))
    a1 = svc.request(mk_exec(db_session, ws="w1"), now=NOW)
    a2 = svc.request(mk_exec(db_session, ws="w2"), now=NOW)
    assert svc.expire_stale("w1", now=NOW + timedelta(hours=2)) == 1
    assert a1.status == ApprovalStatus.EXPIRED and a2.status == ApprovalStatus.PENDING


def test_mark_executed_requires_approved(db_session):
    svc = ApprovalService(db_session)
    a = svc.request(mk_exec(db_session), now=NOW)
    with pytest.raises(ApprovalStateError):
        svc.mark_executed(a)


def test_cannot_request_approval_for_finished_execution(db_session):
    e = mk_exec(db_session)
    e.status = ExecutionStatus.SUCCEEDED
    with pytest.raises(ApprovalStateError):
        ApprovalService(db_session).request(e, now=NOW)


def test_audit_redacts_secrets():
    out = redact({"api_key": "k", "nested": {"Password": "p", "ok": 1}, "list": [{"token": "t"}]})
    assert out == {"api_key": "[REDACTED]", "nested": {"Password": "[REDACTED]", "ok": 1},
                   "list": [{"token": "[REDACTED]"}]}
