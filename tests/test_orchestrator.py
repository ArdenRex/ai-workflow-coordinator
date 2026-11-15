"""Step 7.4: the orchestrator drives stored plans through ordinary agent runs."""
import json

import pytest
from sqlalchemy import func, select

from app.agents.executor import AgentExecutor
from app.kernel.approvals import ApprovalService
from app.llm.errors import LLMAuthError
from app.llm.fake import FakeProvider
from app.llm.service import LLMService
from app.models import Approval, ApprovalStatus, Role, SystemEvent, ToolExecution
from app.models.agents import AgentRun
from app.models.enums import AgentRunStatus as R
from app.models.enums import PlanStatus as P
from app.models.enums import StepState as S
from app.orchestration.errors import (InvalidPlanRequestError, PlanCancelledError, PlanForbiddenError,
                                      PlanNotFoundError, PlanStateError)
from app.orchestration.orchestrator import PlanOrchestrator
from app.orchestration.plan import ExecutionPlan, PlanStep
from app.orchestration.store import PlanService
from tests.test_agent_context import CALLS
from tests.test_agent_executor import intent_json, plan_json
from tests.test_agent_runs import Clock, agents, clock, member, svc, tools, users  # noqa: F401

pytestmark = pytest.mark.usefixtures("seed_workspaces")
GOAL = "Check things and update the task"
CANARY = "CANARY-instruction-5521"
PING = [intent_json(), plan_json()]
WRITE = [intent_json("aceden.task.update"), plan_json("aceden.task.update", {"task_id": 5})]


def step(i, agent="ops_agent", deps=(), text="Check system status"):
    return PlanStep(i, agent, text, tuple(deps))


class World:
    def __init__(self, db, svc, agents, tools, script, clock):
        self.db, self.runs = db, svc
        self.provider = FakeProvider(list(script))
        llm = LLMService(db, self.provider, svc.settings, sleep=lambda s: None)
        self.plans = PlanService(db, agents, svc.settings, clock=clock)
        self.exec = AgentExecutor(db, svc, agents, tools, llm)
        self.orch = PlanOrchestrator(self.plans, svc, self.exec)

    def create(self, *steps, user=None):
        plan = ExecutionPlan(tuple(steps))
        rec = self.plans.create(user or member(), GOAL, plan)
        return rec, plan

    def drive(self, rec, plan, user=None):
        return self.orch.drive(user or member(), rec.id, GOAL, plan)

    def states(self, rec, user=None):
        return {s.step_key: s.status for s in self.plans.steps(user or member(), rec.id)}


@pytest.fixture
def world(db_session, svc, agents, tools, clock):
    def build(*script):
        return World(db_session, svc, agents, tools, [x for pair in script for x in pair], clock)
    return build


def n(db, model):
    return db.scalar(select(func.count()).select_from(model))


def approval_of(db, run_id):
    run = db.get(AgentRun, run_id)
    return db.scalar(select(Approval).where(Approval.execution_id == run.pending_execution_id))


# ------------------------------------------------------------------ happy paths
def test_linear_plan_runs_in_order_and_completes(world, db_session):
    w = world(PING, PING)
    rec, plan = w.create(step("a"), step("b", deps=["a"]))
    r = w.drive(rec, plan)
    assert r.state == "completed" and r.plan.status == P.SUCCEEDED
    assert w.states(rec) == {"a": S.SUCCEEDED, "b": S.SUCCEEDED}
    steps = w.plans.steps(member(), rec.id)
    assert all(s.run_id for s in steps) and steps[0].run_id != steps[1].run_id
    assert steps[0].started_at <= steps[1].started_at
    assert n(db_session, ToolExecution) == 2 and n(db_session, AgentRun) == 2
    assert set(steps[0].result) <= {"outcome", "tool_id", "execution_id", "run_id", "reason", "missing_count"}


def test_independent_steps_all_run_and_join_waits_for_both(world):
    w = world(PING, PING, PING)
    rec, plan = w.create(step("a"), step("b"), step("c", deps=["a", "b"]))
    assert w.drive(rec, plan).state == "completed"
    assert set(w.states(rec).values()) == {S.SUCCEEDED}


def test_every_step_is_an_ordinary_run_by_the_same_user_for_its_agent(world, db_session):
    w = world(PING, WRITE)
    rec, plan = w.create(step("a"), step("w", "task_writer"))
    w.drive(rec, plan)
    runs = list(db_session.scalars(select(AgentRun).order_by(AgentRun.created_at)))
    assert {(r.agent_id, r.requested_by) for r in runs} == {("ops_agent", "u1"), ("task_writer", "u1")}
    ex = list(db_session.scalars(select(ToolExecution)))
    assert {e.agent for e in ex} == {"ops_agent", "task_writer"}


# ------------------------------------------------------------------ failure handling
def test_failed_step_skips_dependents_but_not_independent_branches(world, db_session):
    w = world([LLMAuthError("bad key")], PING)          # a fails (model error), c is independent and succeeds
    rec, plan = w.create(step("a"), step("b", deps=["a"]), step("c"))
    r = w.drive(rec, plan)
    assert w.states(rec) == {"a": S.FAILED, "b": S.SKIPPED, "c": S.SUCCEEDED}
    assert r.state == "completed" and r.plan.status == P.FAILED and r.plan.error_code == "steps_failed"
    assert n(db_session, AgentRun) == 2                 # no run was ever created for the skipped step
    a = w.plans.steps(member(), rec.id)[0]
    assert a.error_code and "bad key" not in json.dumps(a.result or {})


# ------------------------------------------------------------------ approvals
def test_waiting_step_does_not_block_independent_steps_and_resumes_after_approval(world, db_session):
    w = world(WRITE, PING, PING)                         # w waits, x runs, then (after approval) y
    rec, plan = w.create(step("w", "task_writer"), step("x"), step("y", deps=["w"]))
    r = w.drive(rec, plan)
    assert r.state == "paused_approval" and r.plan.status == P.RUNNING
    assert w.states(rec) == {"w": S.WAITING_APPROVAL, "x": S.SUCCEEDED, "y": S.PENDING} and CALLS == []
    runs_before, llm_before = n(db_session, AgentRun), len(w.provider.requests)
    assert w.drive(rec, plan).state == "paused_approval"             # undecided: nothing new happens
    assert (n(db_session, AgentRun), len(w.provider.requests)) == (runs_before, llm_before) and CALLS == []
    wstep = w.plans.steps(member(), rec.id)[0]
    ApprovalService(db_session).decide(approval_of(db_session, wstep.run_id).id, member("u2", role=Role.ADMIN), approve=True)
    assert CALLS == []                                                # approving alone runs nothing
    r = w.drive(rec, plan)
    assert r.state == "completed" and r.plan.status == P.SUCCEEDED and [c[0] for c in CALLS] == ["update"]
    assert set(w.states(rec).values()) == {S.SUCCEEDED}


def test_rejected_approval_fails_the_step_and_skips_dependents(world, db_session):
    w = world(WRITE)
    rec, plan = w.create(step("w", "task_writer"), step("y", deps=["w"]))
    assert w.drive(rec, plan).state == "paused_approval"
    run_id = w.plans.steps(member(), rec.id)[0].run_id
    ApprovalService(db_session).decide(approval_of(db_session, run_id).id, member("u2", role=Role.ADMIN), approve=False)
    r = w.drive(rec, plan)
    assert w.states(rec) == {"w": S.FAILED, "y": S.SKIPPED} and r.plan.status == P.FAILED and CALLS == []
    assert w.plans.steps(member(), rec.id)[0].error_code == "approval_rejected"


# ------------------------------------------------------------------ authority and integrity
def test_goal_and_plan_must_match_the_stored_digests(world, db_session):
    w = world(PING)
    rec, plan = w.create(step("a"))
    with pytest.raises(InvalidPlanRequestError):
        w.orch.drive(member(), rec.id, "a different goal", plan)
    with pytest.raises(InvalidPlanRequestError):
        w.orch.drive(member(), rec.id, GOAL, ExecutionPlan((step("a", text="Delete everything"),)))
    assert n(db_session, AgentRun) == 0 and w.plans.get(member(), rec.id).status == P.PENDING
    assert w.provider.requests == []


def test_only_the_creator_can_drive_never_an_admin_or_outsider(world, db_session):
    w = world(PING)
    rec, plan = w.create(step("a"))
    with pytest.raises(PlanForbiddenError):
        w.drive(rec, plan, user=member("u2", role=Role.ADMIN))
    with pytest.raises(PlanNotFoundError):
        w.drive(rec, plan, user=member("u2", role=Role.MEMBER))
    with pytest.raises(PlanNotFoundError):
        w.drive(rec, plan, user=member("u1", ws="w2"))
    assert n(db_session, AgentRun) == 0


def test_finished_plan_cannot_be_driven_again(world, db_session):
    w = world(PING)
    rec, plan = w.create(step("a"))
    w.drive(rec, plan)
    with pytest.raises(PlanStateError):
        w.drive(rec, plan)
    assert n(db_session, AgentRun) == 1 and n(db_session, ToolExecution) == 1


def test_driving_twice_never_runs_a_step_twice(world, db_session):
    w = world(WRITE, PING)
    rec, plan = w.create(step("w", "task_writer"), step("x"))
    w.drive(rec, plan)
    w.drive(rec, plan)
    w.drive(rec, plan)
    assert n(db_session, AgentRun) == 2 and n(db_session, ToolExecution) == 2


# ------------------------------------------------------------------ crash recovery
def test_a_step_whose_run_already_finished_is_reconciled_not_rerun(world, db_session):
    w = world(PING, PING)
    rec, plan = w.create(step("a"), step("b", deps=["a"]))
    w.plans.start(member(), rec.id)
    run = w.runs.create(member(), "ops_agent", "Check system status", idempotency_key=f"plan:{rec.id}:a")
    w.plans.begin_step(member(), rec.id, "a", run.id)
    w.exec.execute(member(), run.id, "Check system status")      # ...then the driver "crashed" before recording
    assert w.states(rec)["a"] == S.RUNNING
    llm_before = len(w.provider.requests)
    r = w.drive(rec, plan)
    assert r.state == "completed" and set(w.states(rec).values()) == {S.SUCCEEDED}
    assert len(w.provider.requests) - llm_before == 2             # only step b called the model
    assert n(db_session, ToolExecution) == 2


# ------------------------------------------------------------------ cancel
def test_cancel_requested_before_driving_runs_nothing(world, db_session):
    w = world(PING)
    rec, plan = w.create(step("a"), step("b", deps=["a"]))
    w.plans.start(member(), rec.id)
    w.plans.cancel(member(), rec.id)
    r = w.drive(rec, plan)
    assert r.state == "cancelled" and r.plan.status == P.CANCELLED
    assert set(w.states(rec).values()) == {S.CANCELLED} and n(db_session, AgentRun) == 0


@pytest.mark.parametrize("who", ["owner", "admin"])
def test_cancel_cancels_linked_runs_withdraws_approvals_and_blocks_later_steps(world, db_session, who):
    w = world(WRITE)
    rec, plan = w.create(step("w", "task_writer"), step("y", deps=["w"]))
    assert w.drive(rec, plan).state == "paused_approval"
    run_id = w.plans.steps(member(), rec.id)[0].run_id
    approval = approval_of(db_session, run_id)
    canceller = member() if who == "owner" else member("u2", role=Role.ADMIN)
    out = w.orch.cancel(canceller, rec.id)
    assert out.status == P.CANCELLED
    assert db_session.get(AgentRun, run_id).status == R.CANCELLED
    assert db_session.get(Approval, approval.id).status == ApprovalStatus.REJECTED
    assert set(w.states(rec).values()) == {S.CANCELLED}
    with pytest.raises(Exception):
        ApprovalService(db_session).decide(approval.id, member("u3", role=Role.ADMIN), approve=True)
    assert w.drive(rec, plan).state == "cancelled"                   # nothing more can start
    assert n(db_session, AgentRun) == 1 and CALLS == []


def test_cancel_is_idempotent_and_hidden_from_outsiders(world):
    w = world(WRITE)
    rec, plan = w.create(step("w", "task_writer"))
    w.drive(rec, plan)
    w.orch.cancel(member(), rec.id)
    assert w.orch.cancel(member(), rec.id).status == P.CANCELLED
    with pytest.raises(PlanNotFoundError):
        w.orch.cancel(member("u2", role=Role.MEMBER), rec.id)
    with pytest.raises(PlanNotFoundError):
        w.orch.cancel(member("u1", ws="w2", role=Role.OWNER), rec.id)


# ------------------------------------------------------------------ leaks
def test_no_instruction_or_goal_text_reaches_events_results_or_logs(world, db_session, caplog):
    w = world(PING, [LLMAuthError("provider said " + CANARY)])
    rec, plan = w.create(step("a", text=CANARY), step("b", deps=["a"], text=CANARY))
    with caplog.at_level("DEBUG"):
        w.drive(rec, plan)
    blob = json.dumps([e.payload for e in db_session.scalars(select(SystemEvent))])
    blob += json.dumps([s.result for s in w.plans.steps(member(), rec.id)], default=str)
    blob += json.dumps([r.result for r in db_session.scalars(select(AgentRun))], default=str) + caplog.text
    assert CANARY not in blob
