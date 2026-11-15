"""Substep 7.2: plan persistence, lifecycle state machine, authority, content-free audit."""
import json

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from app.config import Settings
from app.models import Role, SystemEvent
from app.models.enums import PlanStatus as P
from app.models.enums import StepState as S
from app.models.orchestration import PlanRecord, PlanStepRecord
from app.orchestration.errors import (InvalidPlanError, InvalidPlanRequestError, PlanCancelledError, PlanConflictError,
                                      PlanForbiddenError, PlanNotFoundError, PlanStateError)
from app.orchestration.plan import ExecutionPlan, PlanStep
from app.orchestration.store import PlanService
from tests.test_agent_runs import (Clock, agents, clock, member, svc, tools, users)  # noqa: F401

pytestmark = pytest.mark.usefixtures("seed_workspaces")
SECRET_GOAL = "Goal with CANARY-goal-77 inside"
SECRET_STEP = "Instruction with CANARY-step-88 inside"


def mkplan(text="do the thing"):
    return ExecutionPlan((PlanStep("a", "ops_agent", text), PlanStep("b", "task_writer", text, ("a",)),
                          PlanStep("c", "ops_agent", text, ("a",)), PlanStep("d", "ops_agent", text, ("b", "c")),
                          PlanStep("e", "ops_agent", text)))


@pytest.fixture
def ps(db_session, agents, clock):
    return PlanService(db_session, agents, Settings(app_env="test", database_url="sqlite:///:memory:", _env_file=None),
                       clock=clock)


def ev(db, plan=None):
    rows = [e for e in db.scalars(select(SystemEvent).order_by(SystemEvent.created_at))
            if e.event_type.startswith("orchestration.")]
    return [e for e in rows if plan is None or e.payload.get("plan_id") == plan.id]


def run_for(svc, step_agent="ops_agent", user=None):
    return svc.create(user or member(), step_agent, "a goal for this step")


def running(ps):
    p = ps.create(member(), "goal", mkplan())
    return ps.start(member(), p.id)


def do(ps, svc, plan, key, agent="ops_agent", to=S.SUCCEEDED, **kw):
    ps.begin_step(member(), plan.id, key, run_for(svc, agent).id)
    return ps.finish_step(member(), plan.id, key, to, **kw)


# ------------------------------------------------------------------ create
def test_create_stores_structure_and_digests_never_content(ps, db_session):
    p = ps.create(member(), SECRET_GOAL, mkplan(SECRET_STEP))
    assert p.status == P.PENDING and p.step_count == 5 and p.goal_chars == len(SECRET_GOAL)
    assert p.plan_digest == mkplan(SECRET_STEP).digest() and len(p.goal_digest) == 64
    steps = ps.steps(member(), p.id)
    assert [s.step_key for s in steps] == list("abcde") and all(s.status == S.PENDING for s in steps)
    assert steps[3].depends_on == ["b", "c"] and steps[1].agent_id == "task_writer"
    dump = json.dumps([{c.name: str(getattr(x, c.name)) for c in x.__table__.columns}
                       for x in [p, *steps]] + [e.payload for e in ev(db_session)], default=str)
    assert "CANARY" not in dump
    assert [e.event_type for e in ev(db_session, p)] == ["orchestration.created"]


@pytest.mark.parametrize("who", [member(role=Role.VIEWER)])
def test_viewers_and_agents_cannot_create(ps, who):
    with pytest.raises(PlanForbiddenError):
        ps.create(who, "g", mkplan())
    agent_p = Principal_with_agent()
    with pytest.raises(PlanForbiddenError):
        ps.create(agent_p, "g", mkplan())


def Principal_with_agent():
    from app.kernel.permissions import Principal
    from app.identity.roles import permissions_for
    return Principal(user_id="u1", workspace_id="w1", permissions=permissions_for(Role.MEMBER), agent="ops_agent",
                     agent_scope=frozenset({"system:read"}))


def test_create_validates_goal_agents_and_size(ps, db_session):
    for bad in ("", "   ", "x" * 4001):
        with pytest.raises(InvalidPlanRequestError):
            ps.create(member(), bad, mkplan())
    with pytest.raises(InvalidPlanRequestError):
        ps.create(member(), "g", mkplan(), idempotency_key="")
    ghost = ExecutionPlan((PlanStep("a", "ghost_agent", "x"),))
    with pytest.raises(InvalidPlanError) as e:
        ps.create(member(), "g", ghost)
    assert e.value.code == "unknown_agent"
    big = ExecutionPlan(tuple(PlanStep(f"s{i}", "ops_agent", "x") for i in range(9)))
    with pytest.raises(InvalidPlanError) as e:
        ps.create(member(), "g", big)
    assert e.value.code == "plan_too_large"
    assert db_session.scalar(select(func.count()).select_from(PlanRecord)) == 0


def test_idempotency_replays_and_conflicts(ps, db_session):
    a = ps.create(member(), "g", mkplan(), idempotency_key="k1")
    assert ps.create(member(), "g", mkplan(), idempotency_key="k1").id == a.id
    for who, goal, plan in ((member("u2"), "g", mkplan()), (member(), "other", mkplan()), (member(), "g", mkplan("x"))):
        with pytest.raises(PlanConflictError):
            ps.create(who, goal, plan, idempotency_key="k1")
    b = ps.create(member(ws="w2"), "g", mkplan(), idempotency_key="k1")            # same key, other workspace
    assert b.id != a.id
    assert db_session.scalar(select(func.count()).select_from(PlanRecord)) == 2


# ------------------------------------------------------------------ visibility
def test_visibility_and_listing(ps):
    p = ps.create(member(), "g", mkplan())
    admin = member("u2", role=Role.ADMIN)
    assert ps.get(member(), p.id).id == p.id and ps.get(admin, p.id).id == p.id
    for hidden in (member("u3"), member(ws="w2"), member("u2", "w2", Role.ADMIN), Principal_with_agent()):
        with pytest.raises(PlanNotFoundError):
            ps.get(hidden, p.id)
    with pytest.raises(PlanNotFoundError):
        ps.get(member(), "missing")
    assert [x.id for x in ps.list(member())] == [p.id] and ps.list(member("u3")) == [] and \
        [x.id for x in ps.list(admin)] == [p.id] and ps.list(member(ws="w2")) == []
    assert ps.list(Principal_with_agent()) == [] and ps.list(member(), status=P.RUNNING) == []


# ------------------------------------------------------------------ driving
def test_only_the_creator_drives_a_plan(ps):
    p = ps.create(member(), "g", mkplan())
    with pytest.raises(PlanForbiddenError):
        ps.start(member("u2", role=Role.ADMIN), p.id)                                # admin sees, cannot drive
    for hidden in (member("u3"), member(ws="w2"), Principal_with_agent()):
        with pytest.raises(PlanNotFoundError):
            ps.start(hidden, p.id)
    assert ps.start(member(), p.id).status == P.RUNNING
    with pytest.raises(PlanStateError):
        ps.start(member(), p.id)                                                     # no double start


def test_dependency_order_is_enforced_in_the_store(ps, svc):
    p = running(ps)
    with pytest.raises(PlanStateError):
        ps.begin_step(member(), p.id, "b", run_for(svc, "task_writer").id)           # a has not succeeded
    do(ps, svc, p, "a")
    ps.begin_step(member(), p.id, "b", run_for(svc, "task_writer").id)               # now fine
    with pytest.raises(PlanStateError):
        ps.begin_step(member(), p.id, "d", run_for(svc).id)                          # needs b AND c


@pytest.mark.parametrize("dead", [S.FAILED, S.CANCELLED])
def test_a_dead_dependency_never_unblocks(ps, svc, dead):
    p = running(ps)
    do(ps, svc, p, "a", to=dead)
    with pytest.raises(PlanStateError):
        ps.begin_step(member(), p.id, "b", run_for(svc, "task_writer").id)


def test_step_must_be_bound_to_a_matching_run_used_once(ps, svc):
    p = running(ps)
    with pytest.raises(InvalidPlanRequestError):
        ps.begin_step(member(), p.id, "a", run_for(svc, "task_writer").id)           # wrong agent
    other_users_run = svc.create(member("u2"), "ops_agent", "g")
    with pytest.raises(InvalidPlanRequestError):
        ps.begin_step(member(), p.id, "a", other_users_run.id)                       # someone else's run
    with pytest.raises(InvalidPlanRequestError):
        ps.begin_step(member(), p.id, "a", "no-such-run")
    other_ws = svc.create(member(ws="w2"), "ops_agent", "g")
    with pytest.raises(InvalidPlanRequestError):
        ps.begin_step(member(), p.id, "a", other_ws.id)                              # other workspace's run
    r = run_for(svc)
    ps.begin_step(member(), p.id, "a", r.id)
    with pytest.raises(PlanStateError):
        ps.begin_step(member(), p.id, "a", r.id)                           # a is already running
    with pytest.raises(PlanConflictError):
        ps.begin_step(member(), p.id, "e", r.id)                                     # run already serves step a


def test_step_state_machine_and_terminal_states_are_final(ps, svc, db_session):
    p = running(ps)
    ps.begin_step(member(), p.id, "a", run_for(svc).id)
    assert ps.mark_step_waiting(member(), p.id, "a").status == S.WAITING_APPROVAL
    with pytest.raises(PlanStateError):
        ps.mark_step_waiting(member(), p.id, "a")
    assert ps.resume_step(member(), p.id, "a").status == S.RUNNING
    with pytest.raises(PlanStateError):
        ps.resume_step(member(), p.id, "a")
    done = ps.finish_step(member(), p.id, "a", S.SUCCEEDED, result={"outcome": "executed", "api_key": "sk-secret-1"})
    assert done.status == S.SUCCEEDED and "sk-secret-1" not in json.dumps(done.result) and done.finished_at
    for fn in (lambda: ps.finish_step(member(), p.id, "a", S.FAILED), lambda: ps.resume_step(member(), p.id, "a"),
               lambda: ps.finish_step(member(), p.id, "a", S.SUCCEEDED)):
        with pytest.raises(PlanStateError):
            fn()
    with pytest.raises(PlanStateError):
        ps.finish_step(member(), p.id, "e", S.SUCCEEDED)                              # never started
    assert ps.steps(member(), p.id)[0].status == S.SUCCEEDED


def test_finish_validation(ps, svc):
    p = running(ps)
    ps.begin_step(member(), p.id, "a", run_for(svc).id)
    for bad in (S.PENDING, S.SKIPPED, S.RUNNING):
        with pytest.raises(InvalidPlanRequestError):
            ps.finish_step(member(), p.id, "a", bad)
    with pytest.raises(InvalidPlanRequestError):
        ps.finish_step(member(), p.id, "a", S.FAILED, code="Not A Slug!")
    with pytest.raises(InvalidPlanRequestError):
        ps.finish_step(member(), p.id, "a", S.SUCCEEDED, result={"x": "y" * 20000})
    with pytest.raises(PlanNotFoundError):
        ps.finish_step(member(), p.id, "zzz", S.SUCCEEDED)
    assert ps.finish_step(member(), p.id, "a", S.FAILED).error_code == "step_failed"


# ------------------------------------------------------------------ failure handling + completion
def test_failure_skips_dependents_not_independent_branches_and_fails_the_plan(ps, svc, db_session):
    p = running(ps)
    do(ps, svc, p, "a", to=S.FAILED, code="tool_failed")
    assert set(ps.skip_blocked(member(), p.id)) == {"b", "c", "d"}
    assert ps.skip_blocked(member(), p.id) == []                                      # safe to repeat
    st = {s.step_key: s for s in ps.steps(member(), p.id)}
    assert st["e"].status == S.PENDING and st["b"].error_code == "dependency_failed"
    with pytest.raises(PlanStateError):
        ps.complete(member(), p.id)                                                   # e not finished
    do(ps, svc, p, "e")
    done = ps.complete(member(), p.id)
    assert done.status == P.FAILED and done.error_code == "steps_failed" and done.finished_at
    assert done.result["outcome"] == "failed" and done.result["steps"]["e"] == "succeeded"
    with pytest.raises(PlanStateError):
        ps.complete(member(), p.id)


def test_full_success_completes_the_plan_with_a_full_audit_trail(ps, svc, db_session):
    p = running(ps)
    for key, agent in (("a", "ops_agent"), ("b", "task_writer"), ("c", "ops_agent"), ("d", "ops_agent"),
                       ("e", "ops_agent")):
        do(ps, svc, p, key, agent)
    done = ps.complete(member(), p.id)
    assert done.status == P.SUCCEEDED and done.result["outcome"] == "succeeded" and done.error_code is None
    types = [e.event_type for e in ev(db_session, p)]
    assert types[0] == "orchestration.created" and types[1] == "orchestration.started" and types[-1] == \
        "orchestration.succeeded" and types.count("orchestration.step_started") == 5 and \
        types.count("orchestration.step_succeeded") == 5
    assert all(e.workspace_id == "w1" for e in ev(db_session, p))
    assert "CANARY" not in json.dumps([e.payload for e in ev(db_session)], default=str)


# ------------------------------------------------------------------ cancel
def test_cancelling_a_pending_plan_cancels_it_and_its_steps_at_once(ps):
    p = ps.create(member(), "g", mkplan())
    done = ps.cancel(member(), p.id)
    assert done.status == P.CANCELLED and all(s.status == S.CANCELLED for s in ps.steps(member(), p.id))
    assert ps.cancel(member(), p.id).status == P.CANCELLED                            # idempotent
    with pytest.raises(PlanStateError):
        ps.start(member(), p.id)


def test_cancel_authority(ps):
    p = ps.create(member(), "g", mkplan())
    for hidden in (member("u3"), member(ws="w2"), Principal_with_agent()):
        with pytest.raises(PlanNotFoundError):
            ps.cancel(hidden, p.id)
    assert ps.cancel(member("u2", role=Role.ADMIN), p.id).status == P.CANCELLED       # admins may cancel


def test_cancelling_a_running_plan_flags_it_and_checkpoint_finishes_it(ps, svc):
    p = running(ps)
    r = run_for(svc)
    ps.begin_step(member(), p.id, "a", r.id)
    flagged = ps.cancel(member("u2", role=Role.ADMIN), p.id)
    assert flagged.status == P.RUNNING and flagged.cancel_requested
    with pytest.raises(PlanStateError):
        ps.begin_step(member(), p.id, "e", run_for(svc).id)                          # no new work once flagged
    with pytest.raises(PlanCancelledError):
        ps.checkpoint(member(), p.id)
    final = ps.get(member(), p.id)
    assert final.status == P.CANCELLED and final.finished_at
    assert all(s.status == S.CANCELLED for s in ps.steps(member(), p.id))            # running step too
    with pytest.raises(PlanCancelledError):
        ps.checkpoint(member(), p.id)
    with pytest.raises(PlanStateError):
        ps.finish_step(member(), p.id, "a", S.SUCCEEDED)                              # cancelled steps stay cancelled


def test_finished_plans_cannot_be_cancelled_or_restarted(ps, svc):
    p = running(ps)
    for k, a in (("a", "ops_agent"), ("b", "task_writer"), ("c", "ops_agent"), ("d", "ops_agent"), ("e", "ops_agent")):
        do(ps, svc, p, k, a)
    ps.complete(member(), p.id)
    with pytest.raises(PlanStateError):
        ps.cancel(member(), p.id)
    with pytest.raises(PlanStateError):
        ps.start(member(), p.id)


def test_stale_objects_cannot_win_a_race(ps, db_session):
    p = ps.create(member(), "g", mkplan())
    stale = db_session.get(PlanRecord, p.id)
    ps.cancel(member(), p.id)
    with pytest.raises(PlanStateError):
        ps._plan_cas(stale, P.RUNNING, (P.PENDING,), "u1", "orchestration.started")
    assert ps.get(member(), p.id).status == P.CANCELLED


def test_database_constraints_back_the_service(ps, db_session):
    p = ps.create(member(), "g", mkplan())
    db_session.add(PlanStepRecord(plan_id=p.id, workspace_id="w1", step_key="a", position=9, agent_id="ops_agent",
                                  instruction_digest="x", instruction_chars=1, depends_on=[]))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
