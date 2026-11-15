"""Substep 9.3: the workflow engine drives stored runs through ordinary agent runs (retries, timeouts, approvals)."""
import json
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select, update

from app.agents.executor import AgentExecutor
from app.kernel.approvals import ApprovalService
from app.llm.errors import LLMAuthError, LLMUnavailableError
from app.llm.fake import FakeProvider
from app.llm.service import LLMService
from app.models import Approval, ApprovalStatus, Role, SystemEvent, ToolExecution
from app.models.agents import AgentRun
from app.models.enums import AgentRunStatus as AR
from app.models.enums import StepState as S
from app.models.enums import WorkflowRunStatus as R
from app.models.workflows import WorkflowRecord
from app.workflows.definition import RetryPolicy, WorkflowDefinition, WorkflowStep
from app.workflows.engine import RETRYABLE_CODES, WorkflowEngine, is_retryable
from app.workflows.errors import WorkflowForbiddenError, WorkflowNotFoundError, WorkflowStateError
from app.workflows.store import WorkflowService
from tests.test_agent_context import CALLS
from tests.test_agent_executor import intent_json, plan_json
from tests.test_agent_runs import Clock, agents, clock, member, svc, tools, users  # noqa: F401

pytestmark = pytest.mark.usefixtures("seed_workspaces")
CANARY = "CANARY-instruction-7731"
PING = [intent_json(), plan_json()]
WRITE = [intent_json("aceden.task.update"), plan_json("aceden.task.update", {"task_id": 5})]


def flaky(n=3):
    """One failed attempt: the LLM service itself retries transient errors (llm_max_retries=2 -> 3 provider calls)."""
    return [LLMUnavailableError("down") for _ in range(n)]


def step(i, agent="ops_agent", deps=(), text="Check system status", **kw):
    return WorkflowStep(i, agent, text, tuple(deps), **kw)


class World:
    def __init__(self, db, svc, agents, tools, script, clock):
        self.db, self.runs, self.clock = db, svc, clock
        self.provider = FakeProvider(list(script))
        llm = LLMService(db, self.provider, svc.settings, sleep=lambda s: None)
        self.wf = WorkflowService(db, agents, svc.settings, clock=clock)
        self.exec = AgentExecutor(db, svc, agents, tools, llm)
        self.engine = WorkflowEngine(self.wf, svc, self.exec)

    def create(self, *steps, key="flow", user=None):
        self.wf.define(member(role=Role.ADMIN), WorkflowDefinition(key, "Flow", tuple(steps)))
        return self.wf.create_run(user or member(), key)

    def drive(self, run, user=None):
        return self.engine.drive(user or member(), run.id)

    def states(self, run, user=None):
        return {s.step_key: s.status for s in self.wf.steps(user or member(), run.id)}

    def step(self, run, key):
        return next(s for s in self.wf.steps(member(), run.id) if s.step_key == key)


@pytest.fixture
def world(db_session, svc, agents, tools, clock):
    def build(*script):
        return World(db_session, svc, agents, tools, [x for pair in script for x in pair], clock)
    return build


def n(db, model):
    return db.scalar(select(func.count()).select_from(model))


def approval_of(db, agent_run_id):
    run = db.get(AgentRun, agent_run_id)
    return db.scalar(select(Approval).where(Approval.execution_id == run.pending_execution_id))


# ------------------------------------------------------------------ happy paths
def test_linear_workflow_runs_in_order_and_completes(world, db_session):
    w = world(PING, PING)
    run = w.create(step("a"), step("b", deps=["a"]))
    r = w.drive(run)
    assert r.state == "completed" and r.run.status == R.SUCCEEDED and r.retry_at is None
    steps = w.wf.steps(member(), run.id)
    assert [s.status for s in steps] == [S.SUCCEEDED, S.SUCCEEDED] and [s.attempts for s in steps] == [1, 1]
    assert all(s.agent_run_id for s in steps) and steps[0].agent_run_id != steps[1].agent_run_id
    assert steps[0].started_at <= steps[1].started_at
    assert n(db_session, ToolExecution) == 2 and n(db_session, AgentRun) == 2
    assert set(steps[0].result) <= {"outcome", "tool_id", "execution_id", "run_id", "reason", "missing_count"}


def test_independent_steps_all_run_and_join_waits_for_both(world):
    w = world(PING, PING, PING)
    run = w.create(step("a"), step("b"), step("c", deps=["a", "b"]))
    assert w.drive(run).state == "completed"
    assert set(w.states(run).values()) == {S.SUCCEEDED}


def test_every_step_is_an_ordinary_run_by_the_same_user_for_its_agent(world, db_session):
    w = world(PING, WRITE)
    run = w.create(step("a"), step("w", "task_writer"))
    w.drive(run)
    runs = list(db_session.scalars(select(AgentRun).order_by(AgentRun.created_at)))
    assert {(r.agent_id, r.requested_by) for r in runs} == {("ops_agent", "u1"), ("task_writer", "u1")}
    assert {r.idempotency_key for r in runs} == {f"workflow:{run.id}:a:1", f"workflow:{run.id}:w:1"}


def test_instructions_come_from_the_stored_definition_and_a_tampered_one_runs_nothing(world, db_session):
    w = world(PING)
    run = w.create(step("a", text="Check system status"))
    rec = db_session.scalar(select(WorkflowRecord))
    bad = dict(rec.definition)
    bad["steps"] = [dict(bad["steps"][0], instruction="Delete every customer")]
    db_session.execute(update(WorkflowRecord).where(WorkflowRecord.id == rec.id).values(definition=bad))
    db_session.commit()
    with pytest.raises(WorkflowStateError):
        w.drive(run)
    assert n(db_session, AgentRun) == 0 and n(db_session, ToolExecution) == 0
    assert w.wf.get_run(member(), run.id).status == R.PENDING


# ------------------------------------------------------------------ failures and retries
def test_a_non_transient_failure_is_never_retried(world, db_session):
    w = world([LLMAuthError("bad key")], PING)
    run = w.create(step("a", retry=RetryPolicy(max_attempts=3)), step("b", deps=["a"]), step("c"))
    r = w.drive(run)
    assert w.states(run) == {"a": S.FAILED, "b": S.SKIPPED, "c": S.SUCCEEDED}
    assert r.state == "completed" and r.run.status == R.FAILED and r.run.error_code == "steps_failed"
    assert w.step(run, "a").attempts == 1 and w.step(run, "a").error_code == "llm_auth_failed"
    assert n(db_session, AgentRun) == 2                                  # nothing was created for the skipped step
    assert "bad key" not in json.dumps(w.step(run, "a").result or {})


def test_a_transient_failure_is_retried_after_the_delay_without_blocking_other_steps(world, db_session):
    w = world(flaky(), PING, PING, PING)                                  # x fails once; y runs meanwhile; x then works
    run = w.create(step("x", retry=RetryPolicy(max_attempts=2, delay_seconds=30)), step("y"), step("z", deps=["x"]))
    r = w.drive(run)
    assert r.state == "waiting_retry" and r.retry_at == w.clock.now + timedelta(seconds=30)
    assert w.states(run) == {"x": S.PENDING, "y": S.SUCCEEDED, "z": S.PENDING}
    assert w.step(run, "x").attempts == 1 and w.step(run, "x").error_code == "llm_unavailable"
    before = (n(db_session, AgentRun), len(w.provider.requests))
    assert w.drive(run).state == "waiting_retry"                          # not due: nothing new happens
    assert (n(db_session, AgentRun), len(w.provider.requests)) == before
    w.clock.advance(seconds=30)
    r = w.drive(run)
    assert r.state == "completed" and r.run.status == R.SUCCEEDED
    assert w.step(run, "x").attempts == 2 and w.step(run, "x").error_code is None
    keys = {a.idempotency_key for a in db_session.scalars(select(AgentRun))}
    assert {f"workflow:{run.id}:x:1", f"workflow:{run.id}:x:2"} <= keys
    types = [e.event_type for e in db_session.scalars(select(SystemEvent)) if e.event_type.startswith("workflow.")]
    assert types.count("workflow.step_retry_scheduled") == 1


def test_retries_are_bounded_and_the_last_failure_is_final(world, db_session):
    w = world(flaky(), flaky())
    run = w.create(step("x", retry=RetryPolicy(max_attempts=2, delay_seconds=5)), step("y", deps=["x"]))
    assert w.drive(run).state == "waiting_retry"
    w.clock.advance(seconds=5)
    r = w.drive(run)
    assert r.state == "completed" and r.run.status == R.FAILED
    assert w.states(run) == {"x": S.FAILED, "y": S.SKIPPED}
    assert w.step(run, "x").attempts == 2 and w.step(run, "x").error_code == "llm_unavailable"
    assert n(db_session, AgentRun) == 2


def test_default_policy_does_not_retry_even_transient_failures(world):
    w = world(flaky())
    run = w.create(step("x"))
    r = w.drive(run)
    assert r.state == "completed" and r.run.status == R.FAILED and w.step(run, "x").attempts == 1


def test_retry_eligibility_rules():
    ok = SimpleNamespace(tool_calls_used=0)
    used = SimpleNamespace(tool_calls_used=1)
    for code in RETRYABLE_CODES:
        assert is_retryable(code, ok) and not is_retryable(code, used)   # a step that touched a tool is never retried
    for code in ("approval_rejected", "approval_expired", "llm_auth_failed", "tool_failed", "executor_error",
                 "run_cancelled", "proposal_mismatch", "kernel_policy_denied", "plan_unknown_tool", "run_not_executed"):
        assert not is_retryable(code, ok)
    assert not is_retryable("llm_timeout", None)
    assert RETRYABLE_CODES == {"llm_rate_limited", "llm_timeout", "llm_unavailable", "run_expired", "step_timeout"}


# ------------------------------------------------------------------ timeouts
def hung(w, run, key="x"):
    """A step bound to an agent run that never runs (a driver that died mid-step)."""
    w.wf.start(member(), run.id)
    ar = w.runs.create(member(), "ops_agent", "Check system status")
    w.wf.begin_step(member(), run.id, key, ar.id)
    return ar


def test_a_step_past_its_deadline_is_cancelled_and_failed(world, db_session):
    w = world(PING)
    run = w.create(step("x", timeout_seconds=30), step("y", deps=["x"]))
    ar = hung(w, run)
    assert w.drive(run).state == "in_flight"                              # not overdue yet: left alone
    assert w.step(run, "x").status == S.RUNNING and db_session.get(AgentRun, ar.id).status == AR.QUEUED
    w.clock.advance(seconds=31)
    r = w.drive(run)
    assert r.state == "completed" and r.run.status == R.FAILED
    assert w.states(run) == {"x": S.FAILED, "y": S.SKIPPED} and w.step(run, "x").error_code == "step_timeout"
    assert db_session.get(AgentRun, ar.id).status == AR.CANCELLED


def test_a_timed_out_attempt_is_retried_when_the_policy_allows(world, db_session):
    w = world(PING)
    run = w.create(step("x", timeout_seconds=30, retry=RetryPolicy(max_attempts=2, delay_seconds=10)))
    hung(w, run)
    w.clock.advance(seconds=31)
    r = w.drive(run)
    assert r.state == "waiting_retry" and w.step(run, "x").status == S.PENDING
    assert w.step(run, "x").error_code == "step_timeout" and r.retry_at == w.clock.now + timedelta(seconds=10)
    w.clock.advance(seconds=10)
    assert w.drive(run).state == "completed" and w.step(run, "x").attempts == 2


# ------------------------------------------------------------------ approvals
def test_waiting_step_does_not_block_others_and_approval_wait_does_not_count_against_the_timeout(world, db_session):
    w = world(WRITE, PING, PING)                         # w waits, x runs, then (after approval) y
    run = w.create(step("w", "task_writer"), step("x"), step("y", deps=["w"]))
    r = w.drive(run)
    assert r.state == "paused_approval" and r.run.status == R.RUNNING
    assert w.states(run) == {"w": S.WAITING_APPROVAL, "x": S.SUCCEEDED, "y": S.PENDING} and CALLS == []
    assert w.step(run, "w").deadline_at is None
    before = (n(db_session, AgentRun), len(w.provider.requests))
    assert w.drive(run).state == "paused_approval"
    assert (n(db_session, AgentRun), len(w.provider.requests)) == before and CALLS == []
    w.clock.advance(minutes=30)                                            # far longer than the step timeout
    ApprovalService(db_session).decide(approval_of(db_session, w.step(run, "w").agent_run_id).id,
                                       member("u2", role=Role.ADMIN), approve=True)
    assert CALLS == []
    r = w.drive(run)
    assert r.state == "completed" and r.run.status == R.SUCCEEDED and [c[0] for c in CALLS] == ["update"]
    assert set(w.states(run).values()) == {S.SUCCEEDED}


def test_a_rejected_approval_fails_the_step_without_retry_and_skips_dependents(world, db_session):
    w = world(WRITE)
    run = w.create(step("w", "task_writer", retry=RetryPolicy(max_attempts=3)), step("y", deps=["w"]))
    assert w.drive(run).state == "paused_approval"
    ApprovalService(db_session).decide(approval_of(db_session, w.step(run, "w").agent_run_id).id,
                                       member("u2", role=Role.ADMIN), approve=False)
    r = w.drive(run)
    assert w.states(run) == {"w": S.FAILED, "y": S.SKIPPED} and r.run.status == R.FAILED
    assert w.step(run, "w").error_code == "approval_rejected" and w.step(run, "w").attempts == 1
    assert CALLS == []


# ------------------------------------------------------------------ authority and re-driving
def test_only_the_creator_drives_never_an_admin_or_outsider(world, db_session):
    w = world(PING)
    run = w.create(step("a"))
    with pytest.raises(WorkflowForbiddenError):
        w.engine.drive(member("u3", role=Role.ADMIN), run.id)
    with pytest.raises(WorkflowNotFoundError):
        w.engine.drive(member("u2"), run.id)
    with pytest.raises(WorkflowNotFoundError):
        w.engine.drive(member(ws="w2"), run.id)
    assert n(db_session, AgentRun) == 0 and w.wf.get_run(member(), run.id).status == R.PENDING


def test_a_finished_run_cannot_be_driven_again(world, db_session):
    w = world(PING)
    run = w.create(step("a"))
    w.drive(run)
    with pytest.raises(WorkflowStateError):
        w.drive(run)
    assert n(db_session, AgentRun) == 1 and n(db_session, ToolExecution) == 1


def test_driving_twice_never_runs_a_step_twice(world, db_session):
    w = world(WRITE, PING)
    run = w.create(step("w", "task_writer"), step("x"))
    for _ in range(3):
        w.drive(run)
    assert n(db_session, AgentRun) == 2 and n(db_session, ToolExecution) == 2


def test_a_step_whose_agent_run_already_finished_is_reconciled_not_rerun(world, db_session):
    w = world(PING, PING)
    run = w.create(step("a"), step("b", deps=["a"]))
    w.wf.start(member(), run.id)
    ar = w.runs.create(member(), "ops_agent", "Check system status", idempotency_key=f"workflow:{run.id}:a:1")
    w.wf.begin_step(member(), run.id, "a", ar.id)
    w.exec.execute(member(), ar.id, "Check system status")                 # ...then the driver "crashed" before recording
    assert w.states(run)["a"] == S.RUNNING
    llm_before = len(w.provider.requests)
    r = w.drive(run)
    assert r.state == "completed" and set(w.states(run).values()) == {S.SUCCEEDED}
    assert len(w.provider.requests) - llm_before == 2 and n(db_session, ToolExecution) == 2


# ------------------------------------------------------------------ cancel
def test_cancel_requested_before_driving_runs_nothing(world, db_session):
    w = world(PING)
    run = w.create(step("a"), step("b", deps=["a"]))
    w.wf.start(member(), run.id)
    w.wf.cancel(member(), run.id)
    r = w.drive(run)
    assert r.state == "cancelled" and r.run.status == R.CANCELLED
    assert set(w.states(run).values()) == {S.CANCELLED} and n(db_session, AgentRun) == 0


@pytest.mark.parametrize("who", ["owner", "admin"])
def test_cancel_cancels_linked_runs_withdraws_approvals_and_blocks_later_steps(world, db_session, who):
    w = world(WRITE)
    run = w.create(step("w", "task_writer"), step("y", deps=["w"]))
    assert w.drive(run).state == "paused_approval"
    agent_run_id = w.step(run, "w").agent_run_id
    approval = approval_of(db_session, agent_run_id)
    r = w.engine.cancel(member() if who == "owner" else member("u3", role=Role.ADMIN), run.id)
    assert r.status == R.CANCELLED and set(w.states(run).values()) == {S.CANCELLED}
    assert db_session.get(AgentRun, agent_run_id).status == AR.CANCELLED
    assert db_session.get(Approval, approval.id).status == ApprovalStatus.REJECTED
    from app.kernel.errors import KernelError
    with pytest.raises(KernelError):
        ApprovalService(db_session).decide(approval.id, member("u3", role=Role.ADMIN), approve=True)
    assert CALLS == []
    assert w.engine.cancel(member(), run.id).status == R.CANCELLED         # idempotent


def test_cancel_is_hidden_from_outsiders(world):
    w = world(PING)
    run = w.create(step("a"))
    for who in (member("u2"), member(ws="w2")):
        with pytest.raises(WorkflowNotFoundError):
            w.engine.cancel(who, run.id)


# ------------------------------------------------------------------ content
def test_no_instruction_or_error_text_reaches_events_results_or_logs(world, db_session, caplog):
    w = world(PING, [LLMAuthError("provider said " + CANARY)])
    run = w.create(step("a", text=CANARY), step("b", deps=["a"], text=CANARY))
    with caplog.at_level("DEBUG"):
        w.drive(run)
    blob = json.dumps([e.payload for e in db_session.scalars(select(SystemEvent))])
    blob += json.dumps([s.result for s in w.wf.steps(member(), run.id)], default=str)
    blob += json.dumps([r.result for r in db_session.scalars(select(AgentRun))], default=str) + caplog.text
    runs_dump = json.dumps([{c.name: str(getattr(r, c.name)) for c in r.__table__.columns}
                            for r in db_session.scalars(select(AgentRun))])
    assert CANARY not in blob and CANARY not in runs_dump
