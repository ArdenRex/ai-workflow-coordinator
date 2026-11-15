"""Substep 13.3: kernel idempotency review. Replays must not run twice, must not bypass policy, and must survive a race."""
import pytest
from sqlalchemy import func, select

from app.kernel.errors import IdempotencyConflictError, PolicyDeniedError
from app.kernel.policy import WorkspacePolicy
from app.models import ExecutionStatus, RiskLevel, ToolExecution
from tests.test_execution_service import P, Rig, boss, rig  # noqa: F401

pytestmark = pytest.mark.usefixtures("seed_workspaces")


def count(rig):
    return rig.db.scalar(select(func.count()).select_from(ToolExecution))


def test_replay_of_a_failed_execution_returns_it_and_does_not_rerun(rig):
    def boom(ctx, d):
        rig.calls.append(1)
        raise RuntimeError("x")
    rig.tool(handler=boom)
    a = rig.svc.submit(P(), "aceden.customer.read", {}, idempotency_key="k")
    b = rig.svc.submit(P(), "aceden.customer.read", {}, idempotency_key="k")
    assert a.status == ExecutionStatus.FAILED and b.id == a.id and len(rig.calls) == 1


def test_replay_of_a_parked_approval_does_not_create_a_second_approval(rig):
    rig.tool(risk=RiskLevel.HIGH)
    a = rig.svc.submit(P(), "aceden.customer.read", {}, idempotency_key="k")
    b = rig.svc.submit(P(), "aceden.customer.read", {}, idempotency_key="k")
    assert a.id == b.id and count(rig) == 1 and rig.calls == []


def test_replay_does_not_bypass_a_disabled_tool(rig):
    rig.tool()
    rig.svc.submit(P(), "aceden.customer.read", {}, idempotency_key="k")
    rig.policy = WorkspacePolicy(disabled_tools=frozenset({"aceden.customer.read"}))
    with pytest.raises(PolicyDeniedError):
        rig.svc.submit(P(), "aceden.customer.read", {}, idempotency_key="k")


def test_replay_does_not_hand_a_result_to_a_caller_without_permission(rig):
    rig.tool()
    first = rig.svc.submit(P(), "aceden.customer.read", {}, idempotency_key="k")
    assert first.output is not None
    with pytest.raises(PolicyDeniedError):
        rig.svc.submit(P(uid="intruder", perms=()), "aceden.customer.read", {}, idempotency_key="k")


def test_a_lost_insert_race_returns_the_winner_instead_of_a_500(rig, monkeypatch):
    rig.tool()
    winner = rig.svc.submit(P(), "aceden.customer.read", {}, idempotency_key="k")
    real = rig.svc._find_idempotent
    state = {"n": 0}

    def blind_first(ws, key):                      # the loser's first lookup happens before the winner committed
        state["n"] += 1
        return None if state["n"] == 1 else real(ws, key)
    monkeypatch.setattr(rig.svc, "_find_idempotent", blind_first)
    again = rig.svc.submit(P(), "aceden.customer.read", {}, idempotency_key="k")
    assert again.id == winner.id and len(rig.calls) == 1 and count(rig) == 1


def test_a_lost_race_with_a_different_request_is_a_conflict(rig, monkeypatch):
    rig.tool()
    rig.svc.submit(P(), "aceden.customer.read", {"n": 1}, idempotency_key="k")
    real = rig.svc._find_idempotent
    state = {"n": 0}
    monkeypatch.setattr(rig.svc, "_find_idempotent",
                        lambda ws, key: (None if (state.__setitem__("n", state["n"] + 1) or state["n"] == 1) else real(ws, key)))
    with pytest.raises(IdempotencyConflictError):
        rig.svc.submit(P(), "aceden.customer.read", {"n": 2}, idempotency_key="k")


# ------------------------------------------------------------------ 14.2: the cap is re-checked inside the claim
def _cap(n):
    from app.kernel.policy import ExecutionLimit
    return WorkspacePolicy(execution_limit=ExecutionLimit(max_executions=n, window_seconds=3600))


def test_a_run_that_passes_the_early_check_but_loses_the_cap_is_refused_and_ended(rig, monkeypatch):
    rig.tool()
    rig.policy = _cap(1)
    rig.svc.submit(P(), "aceden.customer.read", {})
    monkeypatch.setattr(rig.svc, "_enforce_limit", lambda *a, **k: None)      # simulate: the early check saw room, the claim sees none
    with pytest.raises(PolicyDeniedError) as e:
        rig.svc.submit(P(), "aceden.customer.read", {})
    assert e.value.reason_code == "execution_limit_reached" and len(rig.calls) == 1
    late = rig.db.scalars(select(ToolExecution).where(ToolExecution.error == "execution_limit_reached")).one()
    assert late.status == ExecutionStatus.FAILED and late.started_at is None and late.finished_at is not None
