import time

import pytest
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select

from app.kernel.errors import (ExecutionStateError, IdempotencyConflictError, PolicyDeniedError,
                               ToolInputError, ToolNotFoundError)
from app.kernel.permissions import Principal
from app.kernel.policy import WorkspacePolicy
from app.kernel.registry import ToolDefinition, ToolRegistry
from app.kernel.service import ToolExecutionService
from app.models import ApprovalStatus, ExecutionStatus, RiskLevel, SystemEvent, ToolExecution
from app.kernel.approvals import ApprovalService

pytestmark = pytest.mark.usefixtures("seed_workspaces")


class In(BaseModel):
    model_config = ConfigDict(extra="forbid")
    n: int = 1


class Out(BaseModel):
    value: int


class Rig:
    def __init__(self, db):
        self.calls = []
        self.registry = ToolRegistry()
        self.policy = WorkspacePolicy()
        self.svc = ToolExecutionService(db, self.registry, policy_provider=lambda ws: self.policy)
        self.db = db

    def tool(self, id="aceden.customer.read", perm="customer:read", risk=RiskLevel.LOW, handler=None, **kw):
        def default(ctx, data):
            self.calls.append(ctx)
            return {"value": data.n}
        self.registry.register(ToolDefinition(id=id, description="d", input_schema=In, output_schema=Out,
                                              required_permission=perm, risk_level=risk,
                                              handler=handler or default, **kw))


def P(uid="u1", ws="w1", perms=("*",), **kw):
    return Principal(user_id=uid, workspace_id=ws, permissions=frozenset(perms), **kw)


def boss(ws="w1"):
    return P(uid="boss", ws=ws, perms=("approval:decide", "*"))


@pytest.fixture
def rig(db_session):
    return Rig(db_session)


def types(rig, ex):
    return [e.event_type for e in rig.svc.audit_trail(ex.id, ex.workspace_id)]


# ---------------------------------------------------------------- happy path
def test_low_risk_runs_immediately_and_is_audited(rig):
    rig.tool()
    ex = rig.svc.submit(P(), "aceden.customer.read", {"n": 7})
    assert ex.status == ExecutionStatus.SUCCEEDED and ex.output == {"value": 7}
    assert ex.finished_at and ex.started_at
    assert types(rig, ex) == ["execution.created", "execution.started", "execution.succeeded"]
    assert rig.calls[0].workspace_id == "w1" and rig.calls[0].user_id == "u1"


def test_agent_attribution_recorded(rig):
    rig.tool()
    p = P(agent="sales", agent_scope=frozenset({"customer:*"}))
    assert rig.svc.submit(p, "aceden.customer.read", {}).agent == "sales"


# ------------------------------------------------------------------- denials
def test_unknown_tool_audited_and_raises(rig):
    with pytest.raises(ToolNotFoundError):
        rig.svc.submit(P(), "no.such.tool", {})
    ev = rig.db.scalar(select(SystemEvent).where(SystemEvent.event_type == "execution.denied"))
    assert ev.payload["reason"] == "tool_not_found"


def test_invalid_input_never_reaches_handler(rig):
    rig.tool()
    with pytest.raises(ToolInputError):
        rig.svc.submit(P(), "aceden.customer.read", {"n": "x"})
    assert rig.calls == []
    assert rig.db.scalar(select(func.count()).select_from(ToolExecution)) == 0


def test_permission_denied_no_run_no_row_but_audited(rig):
    rig.tool()
    with pytest.raises(PolicyDeniedError) as e:
        rig.svc.submit(P(perms=("other:read",)), "aceden.customer.read", {})
    assert e.value.reason_code == "permission_denied" and rig.calls == []
    assert rig.db.scalar(select(func.count()).select_from(ToolExecution)) == 0
    ev = rig.db.scalar(select(SystemEvent).where(SystemEvent.event_type == "execution.denied"))
    assert ev.payload["reason"] == "permission_denied"


def test_disabled_tool_denied(rig):
    rig.tool()
    rig.policy = WorkspacePolicy(disabled_tools=frozenset({"aceden.customer.read"}))
    with pytest.raises(PolicyDeniedError):
        rig.svc.submit(P(), "aceden.customer.read", {})


# ----------------------------------------------------------------- approvals
def high(rig):
    rig.tool(id="aceden.customer.delete", perm="customer:delete", risk=RiskLevel.HIGH)


def test_high_risk_waits_for_approval_and_does_not_run(rig):
    high(rig)
    ex = rig.svc.submit(P(), "aceden.customer.delete", {})
    assert ex.status == ExecutionStatus.AWAITING_APPROVAL and rig.calls == []


def test_full_approval_journey(rig):
    high(rig)
    ex = rig.svc.submit(P(), "aceden.customer.delete", {"n": 3})
    appr = rig.db.scalar(select(ex.approvals[0].__class__))
    ApprovalService(rig.db).decide(appr.id, boss(), approve=True)
    done = rig.svc.execute_approved(P(), ex.id)
    assert done.status == ExecutionStatus.SUCCEEDED and done.output == {"value": 3}
    assert rig.db.get(type(appr), appr.id).status == ApprovalStatus.EXECUTED
    assert types(rig, ex) == ["execution.created", "approval.requested", "approval.approved",
                              "execution.started", "execution.succeeded", "approval.executed"]


def test_BYPASS_execute_before_approval_blocked(rig):
    high(rig)
    ex = rig.svc.submit(P(), "aceden.customer.delete", {})
    with pytest.raises(ExecutionStateError):
        rig.svc.execute_approved(P(), ex.id)
    assert rig.calls == []


def test_BYPASS_forged_status_without_approval_row_blocked(rig):
    high(rig)
    ex = rig.svc.submit(P(), "aceden.customer.delete", {})
    ex.status = ExecutionStatus.APPROVED          # attacker flips the status only
    rig.db.commit()
    with pytest.raises(ExecutionStateError):
        rig.svc.execute_approved(P(), ex.id)
    assert rig.calls == []


def test_BYPASS_rejected_execution_cannot_run(rig):
    high(rig)
    ex = rig.svc.submit(P(), "aceden.customer.delete", {})
    ApprovalService(rig.db).decide(ex.approvals[0].id, boss(), approve=False)
    with pytest.raises(ExecutionStateError):
        rig.svc.execute_approved(P(), ex.id)
    assert rig.calls == []


def test_BYPASS_cannot_run_approved_twice(rig):
    high(rig)
    ex = rig.svc.submit(P(), "aceden.customer.delete", {})
    ApprovalService(rig.db).decide(ex.approvals[0].id, boss(), approve=True)
    rig.svc.execute_approved(P(), ex.id)
    with pytest.raises(ExecutionStateError):
        rig.svc.execute_approved(P(), ex.id)
    assert len(rig.calls) == 1


def test_BYPASS_other_workspace_cannot_execute(rig):
    high(rig)
    ex = rig.svc.submit(P(), "aceden.customer.delete", {})
    ApprovalService(rig.db).decide(ex.approvals[0].id, boss(), approve=True)
    with pytest.raises(ExecutionStateError):
        rig.svc.execute_approved(P(ws="w2"), ex.id)
    assert rig.calls == []


def test_permission_revoked_after_approval_blocks_run(rig):
    high(rig)
    ex = rig.svc.submit(P(), "aceden.customer.delete", {})
    ApprovalService(rig.db).decide(ex.approvals[0].id, boss(), approve=True)
    with pytest.raises(PolicyDeniedError):
        rig.svc.execute_approved(P(perms=("customer:read",)), ex.id)
    assert rig.calls == []


def test_workspace_policy_can_force_approval_on_read(rig):
    rig.tool()
    rig.policy = WorkspacePolicy(approval_required_tools=frozenset({"aceden.customer.read"}))
    assert rig.svc.submit(P(), "aceden.customer.read", {}).status == ExecutionStatus.AWAITING_APPROVAL


# --------------------------------------------------------------- idempotency
def test_idempotency_returns_same_execution_and_runs_once(rig):
    rig.tool()
    a = rig.svc.submit(P(), "aceden.customer.read", {"n": 1}, idempotency_key="k")
    b = rig.svc.submit(P(), "aceden.customer.read", {"n": 1}, idempotency_key="k")
    assert a.id == b.id and len(rig.calls) == 1


def test_idempotency_key_conflict_and_workspace_scope(rig):
    rig.tool()
    rig.svc.submit(P(), "aceden.customer.read", {"n": 1}, idempotency_key="k")
    with pytest.raises(IdempotencyConflictError):
        rig.svc.submit(P(), "aceden.customer.read", {"n": 2}, idempotency_key="k")
    other = rig.svc.submit(P(ws="w2"), "aceden.customer.read", {"n": 2}, idempotency_key="k")
    assert other.workspace_id == "w2" and len(rig.calls) == 2


# ------------------------------------------------------------- reliability
def test_handler_error_is_failed_and_sanitized(rig):
    def boom(ctx, data):
        raise RuntimeError("password=hunter2")
    rig.tool(handler=boom)
    ex = rig.svc.submit(P(), "aceden.customer.read", {})
    assert ex.status == ExecutionStatus.FAILED and "hunter2" not in ex.error
    assert "execution.failed" in types(rig, ex)


def test_invalid_output_fails_verification(rig):
    rig.tool(handler=lambda ctx, d: {"wrong": 1})
    ex = rig.svc.submit(P(), "aceden.customer.read", {})
    assert ex.status == ExecutionStatus.FAILED and ex.output is None


def test_timeout_fails_and_is_not_retried(rig):
    n = {"c": 0}

    def slow(ctx, d):
        n["c"] += 1
        time.sleep(1.4)
        return {"value": 1}
    rig.tool(handler=slow, timeout_seconds=1, max_retries=2)
    ex = rig.svc.submit(P(), "aceden.customer.read", {})
    assert ex.status == ExecutionStatus.FAILED and ex.error == "Tool timed out" and n["c"] == 1


def test_low_risk_tool_retries_then_succeeds(rig):
    n = {"c": 0}

    def flaky(ctx, d):
        n["c"] += 1
        if n["c"] == 1:
            raise RuntimeError("transient")
        return {"value": 9}
    rig.tool(handler=flaky, max_retries=1)
    ex = rig.svc.submit(P(), "aceden.customer.read", {})
    assert ex.status == ExecutionStatus.SUCCEEDED and n["c"] == 2


def test_tool_without_handler_fails_safely(rig):
    rig.registry.register(ToolDefinition(id="x.y", description="d", input_schema=In, output_schema=Out,
                                         required_permission="x:read", risk_level=RiskLevel.LOW))
    assert rig.svc.submit(P(), "x.y", {}).status == ExecutionStatus.FAILED
