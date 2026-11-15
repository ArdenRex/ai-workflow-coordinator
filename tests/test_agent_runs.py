"""Step 6.3: agent run records, lifecycle state machine, limits, authority, audit."""
import itertools
import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.agents.context import build_agent_context
from app.agents.errors import (AgentNotFoundError, InvalidRunRequestError, RunCancelledError, RunConflictError,
                               RunExpiredError, RunForbiddenError, RunLimitError, RunNotFoundError, RunStateError)
from app.agents.registry import AgentRegistry
from app.agents.runs import ALLOWED_TRANSITIONS, TERMINAL, AgentRunService, is_terminal
from app.config import Settings
from app.identity.roles import permissions_for
from app.kernel.approvals import ApprovalService
from app.kernel.permissions import Principal
from app.models import AgentRun, Approval, ExecutionStatus, Role, SystemEvent, User
from app.models.enums import AgentRunStatus as S
from tests.test_agent_context import COORD, OPS, WRITER, build_tools

pytestmark = pytest.mark.usefixtures("seed_workspaces")
T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now

    def advance(self, **kw):
        self.now += timedelta(**kw)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def tools():
    return build_tools()


@pytest.fixture
def agents(tools):
    reg = AgentRegistry(tools)
    for a in (OPS, WRITER, COORD):
        reg.register(a)
    return reg


@pytest.fixture(autouse=True)
def users(db_session):
    for uid in ("u1", "u2", "u3"):
        db_session.add(User(id=uid, email=f"{uid}@x.com", password_hash="h"))
    db_session.commit()


def svc_for(db, agents, clock, **overrides):
    s = Settings(app_env="test", database_url="sqlite:///:memory:", _env_file=None, **overrides)
    return AgentRunService(db, agents, s, clock=clock)


@pytest.fixture
def svc(db_session, agents, clock):
    return svc_for(db_session, agents, clock)


def member(uid="u1", ws="w1", role=Role.MEMBER):
    return Principal(user_id=uid, workspace_id=ws, permissions=permissions_for(role))


def agent_p(agents, tools, agent="ops_agent", uid="u1", ws="w1", role=Role.MEMBER):
    return build_agent_context(member(uid, ws, role), agent, agents, tools).principal


def events(db, run, etype=None):
    q = select(SystemEvent).where(SystemEvent.workspace_id == run.workspace_id)
    evs = [e for e in db.scalars(q) if e.payload.get("run_id") == run.id]
    return [e for e in evs if etype is None or e.event_type == etype]


# ------------------------------------------------------------------ roles
def test_role_permissions_for_runs():
    assert not permissions_for(Role.VIEWER) & {"agent:run"}
    assert "agent:run" in permissions_for(Role.MEMBER) and "agent:manage" not in permissions_for(Role.MEMBER)
    assert "agent:*" in permissions_for(Role.ADMIN)


# ------------------------------------------------------------------ state machine table
def test_transition_table_is_closed_and_terminals_are_final():
    assert TERMINAL == {S.SUCCEEDED, S.FAILED, S.CANCELLED, S.EXPIRED}
    assert set(ALLOWED_TRANSITIONS) == set(S)
    for t in TERMINAL:
        assert ALLOWED_TRANSITIONS[t] == frozenset() and is_terminal(t)
    assert not is_terminal(S.WAITING_APPROVAL)
    assert S.QUEUED not in set().union(*ALLOWED_TRANSITIONS.values())          # nothing returns to QUEUED
    assert S.SUCCEEDED not in ALLOWED_TRANSITIONS[S.QUEUED]                    # can't succeed without running


# ------------------------------------------------------------------ create
def test_create_records_queued_run_with_content_free_fields(svc, db_session):
    run = svc.create(member(), "ops_agent", "  Check the status of my business  ")
    assert run.status == S.QUEUED and run.requested_by == "u1" and run.workspace_id == "w1"
    assert run.goal_chars == len("Check the status of my business") and len(run.goal_digest) == 64
    assert (run.steps_used, run.tool_calls_used, run.llm_calls_used) == (0, 0, 0) and not run.cancel_requested
    dump = json.dumps({c.name: str(getattr(run, c.name)) for c in AgentRun.__table__.columns})
    assert "business" not in dump                                            # the goal text is never stored
    (ev,) = events(db_session, run, "agent_run.created")
    assert ev.actor == "u1" and "business" not in json.dumps(ev.payload) and ev.payload["agent"] == "ops_agent"


def test_create_requires_permission_and_a_human_principal(svc, agents, tools):
    with pytest.raises(RunForbiddenError):
        svc.create(member(role=Role.VIEWER), "ops_agent", "go")
    with pytest.raises(RunForbiddenError):                                    # an agent can't start runs
        svc.create(agent_p(agents, tools), "ops_agent", "go")
    with pytest.raises(AgentNotFoundError):
        svc.create(member(), "ghost", "go")


@pytest.mark.parametrize("goal", ["", "   ", None, 5, "x" * 4001])
def test_create_validates_goal(svc, goal):
    with pytest.raises(InvalidRunRequestError):
        svc.create(member(), "ops_agent", goal)


def test_limits_default_to_ceilings_and_can_only_be_lowered(db_session, agents, clock):
    s = svc_for(db_session, agents, clock, agent_run_max_steps=6, agent_run_max_tool_calls=3,
                agent_run_max_llm_calls=4, agent_run_timeout_seconds=60)
    r = s.create(member(), "ops_agent", "g")
    assert (r.max_steps, r.max_tool_calls, r.max_llm_calls) == (6, 3, 4)
    assert r.expires_at.replace(tzinfo=timezone.utc) == T0 + timedelta(seconds=60)
    low = s.create(member(), "ops_agent", "g2", max_steps=2, max_tool_calls=0, max_llm_calls=1, timeout_seconds=10)
    assert (low.max_steps, low.max_tool_calls, low.max_llm_calls) == (2, 0, 1)
    assert low.expires_at.replace(tzinfo=timezone.utc) == T0 + timedelta(seconds=10)
    high = s.create(member(), "ops_agent", "g3", max_steps=999, max_tool_calls=999, max_llm_calls=999,
                    timeout_seconds=99999)
    assert (high.max_steps, high.max_tool_calls, high.max_llm_calls) == (6, 3, 4)       # clamped, not honoured
    assert high.expires_at.replace(tzinfo=timezone.utc) == T0 + timedelta(seconds=60)


@pytest.mark.parametrize("kw", [{"max_steps": 0}, {"max_steps": -1}, {"max_tool_calls": -1}, {"max_llm_calls": "5"},
                                {"max_steps": True}, {"timeout_seconds": 1}, {"max_steps": 2.5}])
def test_bad_limits_are_rejected(svc, kw):
    with pytest.raises(InvalidRunRequestError):
        svc.create(member(), "ops_agent", "g", **kw)


@pytest.mark.parametrize("name,value", [("agent_run_max_steps", 0), ("agent_run_max_steps", 51),
                                        ("agent_run_max_tool_calls", 26), ("agent_run_max_llm_calls", 0),
                                        ("agent_run_timeout_seconds", 4), ("agent_run_timeout_seconds", 3601),
                                        ("agent_run_approval_wait_seconds", 59)])
def test_settings_bounds(name, value):
    with pytest.raises(ValueError):
        Settings(app_env="test", database_url="sqlite:///:memory:", _env_file=None, **{name: value})


# ------------------------------------------------------------------ idempotency
def test_idempotency_replays_same_request_and_rejects_different_one(svc, db_session):
    a = svc.create(member(), "ops_agent", "same goal", idempotency_key="k1")
    b = svc.create(member(), "ops_agent", "same goal", idempotency_key="k1")
    assert a.id == b.id and len(events(db_session, a, "agent_run.created")) == 1
    for who, agent, goal in [(member(), "ops_agent", "other goal"), (member(), "task_writer", "same goal"),
                             (member("u2"), "ops_agent", "same goal")]:
        with pytest.raises(RunConflictError):
            svc.create(who, agent, goal, idempotency_key="k1")


def test_idempotency_keys_are_per_workspace(svc):
    a = svc.create(member(ws="w1"), "ops_agent", "g", idempotency_key="k")
    b = svc.create(member(ws="w2"), "ops_agent", "g", idempotency_key="k")
    assert a.id != b.id


def test_idempotency_key_length_validated(svc):
    with pytest.raises(InvalidRunRequestError):
        svc.create(member(), "ops_agent", "g", idempotency_key="")
    with pytest.raises(InvalidRunRequestError):
        svc.create(member(), "ops_agent", "g", idempotency_key="k" * 129)


def test_database_constraint_blocks_duplicate_key_even_if_service_is_bypassed(db_session, svc):
    a = svc.create(member(), "ops_agent", "g", idempotency_key="dup")
    db_session.add(AgentRun(workspace_id="w1", agent_id="ops_agent", requested_by="u1", goal_digest="d", goal_chars=1,
                            idempotency_key="dup", max_steps=1, max_tool_calls=0, max_llm_calls=0))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
    assert a.id


# ------------------------------------------------------------------ happy path + audit
def test_full_lifecycle_and_audit_trail(svc, db_session, clock):
    p = member()
    run = svc.create(p, "ops_agent", "goal")
    svc.start(p, run.id)
    assert run.status == S.RUNNING and run.started_at is not None
    for kind in ("step", "llm_call", "step", "tool_call"):
        svc.charge(p, run.id, kind)
    assert (run.steps_used, run.llm_calls_used, run.tool_calls_used) == (2, 1, 1)
    svc.succeed(p, run.id, {"summary": "all good", "api_key": "sk-secret"})
    assert run.status == S.SUCCEEDED and run.finished_at is not None and is_terminal(run.status)
    assert run.result == {"summary": "all good", "api_key": "[REDACTED]"}
    types = [e.event_type for e in sorted(events(db_session, run), key=lambda e: e.created_at)]
    assert sorted(types) == sorted(["agent_run.created", "agent_run.started", "agent_run.succeeded"])
    blob = json.dumps([e.payload for e in events(db_session, run)])
    assert "sk-secret" not in blob and "all good" not in blob and "goal" not in blob.replace("goal_chars", "")


def test_terminal_runs_never_move_again(svc):
    p = member()
    run = svc.create(p, "ops_agent", "g")
    svc.start(p, run.id)
    svc.succeed(p, run.id)
    for call in (lambda: svc.start(p, run.id), lambda: svc.fail(p, run.id, "x"), lambda: svc.resume(p, run.id),
                 lambda: svc.charge(p, run.id, "step"), lambda: svc.checkpoint(p, run.id),
                 lambda: svc.succeed(p, run.id), lambda: svc.cancel(p, run.id)):
        with pytest.raises(RunStateError):
            call()
    assert run.status == S.SUCCEEDED


def test_cannot_skip_states(svc):
    p = member()
    run = svc.create(p, "ops_agent", "g")
    with pytest.raises(RunStateError):
        svc.succeed(p, run.id)                         # QUEUED -> SUCCEEDED is not allowed
    with pytest.raises(RunStateError):
        svc.resume(p, run.id)                          # not waiting
    with pytest.raises(RunStateError):
        svc.charge(p, run.id, "step")                  # not running
    svc.start(p, run.id)
    with pytest.raises(RunStateError):
        svc.start(p, run.id)                           # already running
    assert run.status == S.RUNNING


def test_start_and_resume_are_not_interchangeable(svc, db_session, agents, tools):
    p = member()
    queued = svc.create(p, "ops_agent", "g")
    with pytest.raises(RunStateError):
        svc.resume(p, queued.id)                       # resume must not start a queued run
    assert queued.status == S.QUEUED
    c, ex = _pending_exec(db_session, agents, tools)
    waiting = svc.create(member(), "task_writer", "g2")
    svc.start(c.principal, waiting.id)
    svc.wait_for_approval(c.principal, waiting.id, ex.id)
    with pytest.raises(RunStateError):
        svc.start(c.principal, waiting.id)             # start must not skip the approval wait
    assert waiting.status == S.WAITING_APPROVAL


def test_fail_requires_a_slug_code_not_free_text(svc, db_session):
    p = member()
    run = svc.create(p, "ops_agent", "g")
    for bad in ("Secret: sk-123 leaked", "", "x" * 65, None, "has space"):
        with pytest.raises(InvalidRunRequestError):
            svc.fail(p, run.id, bad)
    svc.fail(p, run.id, "tool_denied")                 # QUEUED -> FAILED is allowed
    assert run.status == S.FAILED and run.error_code == "tool_denied"
    (ev,) = events(db_session, run, "agent_run.failed")
    assert ev.payload["error_code"] == "tool_denied"


def test_result_is_bounded_and_must_be_an_object(svc):
    p = member()
    run = svc.create(p, "ops_agent", "g")
    svc.start(p, run.id)
    with pytest.raises(InvalidRunRequestError):
        svc.succeed(p, run.id, {"blob": "x" * 20000})
    with pytest.raises(InvalidRunRequestError):
        svc.succeed(p, run.id, ["not", "an", "object"])
    assert run.status == S.RUNNING                     # a rejected result doesn't finish the run


# ------------------------------------------------------------------ limits
@pytest.mark.parametrize("kind,field,code", [("step", "max_steps", "limit_steps"),
                                              ("tool_call", "max_tool_calls", "limit_tool_calls"),
                                              ("llm_call", "max_llm_calls", "limit_llm_calls")])
def test_budget_exhaustion_fails_the_run_with_a_fixed_code(svc, db_session, kind, field, code):
    p = member()
    run = svc.create(p, "ops_agent", "g", **{field: 2})
    svc.start(p, run.id)
    svc.charge(p, run.id, kind)
    svc.charge(p, run.id, kind)
    with pytest.raises(RunLimitError):
        svc.charge(p, run.id, kind)
    assert run.status == S.FAILED and run.error_code == code
    assert getattr(run, {"step": "steps_used", "tool_call": "tool_calls_used", "llm_call": "llm_calls_used"}[kind]) == 2
    (ev,) = events(db_session, run, "agent_run.failed")
    assert ev.payload["error_code"] == code and ev.payload["reason"] == "limit"
    with pytest.raises(RunStateError):
        svc.charge(p, run.id, kind)                    # and it stays failed


def test_zero_tool_budget_means_no_tool_calls_at_all(svc):
    p = member()
    run = svc.create(p, "ops_agent", "g", max_tool_calls=0)
    svc.start(p, run.id)
    with pytest.raises(RunLimitError):
        svc.charge(p, run.id, "tool_call")


def test_unknown_budget_kind_rejected(svc):
    p = member()
    run = svc.create(p, "ops_agent", "g")
    svc.start(p, run.id)
    with pytest.raises(InvalidRunRequestError):
        svc.charge(p, run.id, "money")


def test_database_check_constraint_blocks_overspending_even_if_service_is_bypassed(db_session, svc):
    p = member()
    run = svc.create(p, "ops_agent", "g", max_steps=1)
    with pytest.raises(IntegrityError):
        db_session.execute(update(AgentRun).where(AgentRun.id == run.id).values(steps_used=2))
    db_session.rollback()


def test_charge_loses_cleanly_when_run_is_cancelled_by_someone_else(svc, db_session):
    p = member()
    run = svc.create(p, "ops_agent", "g")
    svc.start(p, run.id)
    db_session.execute(update(AgentRun).where(AgentRun.id == run.id).values(cancel_requested=True))
    db_session.commit()
    with pytest.raises(RunCancelledError):
        svc.charge(p, run.id, "step")
    assert run.status == S.CANCELLED and run.steps_used == 0


# ------------------------------------------------------------------ cancel
def test_cancel_queued_and_waiting_is_immediate_running_is_cooperative(svc, db_session):
    p = member()
    q = svc.create(p, "ops_agent", "g1")
    assert svc.cancel(p, q.id).status == S.CANCELLED and q.finished_at is not None

    r = svc.create(p, "ops_agent", "g2")
    svc.start(p, r.id)
    svc.cancel(p, r.id)
    assert r.status == S.RUNNING and r.cancel_requested is True                # flagged, not yet stopped
    assert len(events(db_session, r, "agent_run.cancel_requested")) == 1
    with pytest.raises(RunCancelledError):
        svc.checkpoint(p, r.id)                                                # stops at the next checkpoint
    assert r.status == S.CANCELLED and len(events(db_session, r, "agent_run.cancelled")) == 1


def test_cancel_is_idempotent_and_cannot_undo_a_finished_run(svc):
    p = member()
    run = svc.create(p, "ops_agent", "g")
    svc.cancel(p, run.id)
    assert svc.cancel(p, run.id).status == S.CANCELLED
    done = svc.create(p, "ops_agent", "g2")
    svc.start(p, done.id)
    svc.succeed(p, done.id)
    with pytest.raises(RunStateError):
        svc.cancel(p, done.id)
    assert done.status == S.SUCCEEDED


def test_succeed_after_cancel_request_is_honest_about_finished_work(svc):
    p = member()
    run = svc.create(p, "ops_agent", "g")
    svc.start(p, run.id)
    svc.cancel(p, run.id)
    svc.succeed(p, run.id, {"done": True})                  # work already completed; the record tells the truth
    assert run.status == S.SUCCEEDED


# ------------------------------------------------------------------ deadlines
def test_queue_wait_expires(svc, clock):
    p = member()
    run = svc.create(p, "ops_agent", "g")
    clock.advance(seconds=121)
    with pytest.raises(RunExpiredError):
        svc.start(p, run.id)
    assert run.status == S.EXPIRED and run.finished_at is not None


def test_active_stretch_expires_at_charge_and_checkpoint(svc, clock):
    p = member()
    run = svc.create(p, "ops_agent", "g")
    svc.start(p, run.id)
    clock.advance(seconds=119)
    svc.charge(p, run.id, "step")                           # still inside the window
    clock.advance(seconds=2)
    with pytest.raises(RunExpiredError):
        svc.checkpoint(p, run.id)
    assert run.status == S.EXPIRED and run.steps_used == 1


def test_expire_overdue_sweeps_only_overdue_non_terminal_runs_in_scope(svc, db_session, clock):
    p1, p2 = member(ws="w1"), member(ws="w2")
    old1, old2, fresh, done = (svc.create(p1, "ops_agent", f"g{i}") for i in range(4))
    other_ws = svc.create(p2, "ops_agent", "g")
    svc.start(p1, done.id)
    svc.succeed(p1, done.id)
    clock.advance(seconds=100)
    fresh2 = svc.create(p1, "ops_agent", "late")
    clock.advance(seconds=30)                               # old ones are 130s old, fresh2 is 30s old
    assert svc.expire_overdue("w1") == 3 and other_ws.status == S.QUEUED
    assert {old1.status, old2.status, fresh.status} == {S.EXPIRED} and fresh2.status == S.QUEUED
    assert done.status == S.SUCCEEDED
    assert svc.expire_overdue("w1") == 0                    # idempotent
    assert svc.expire_overdue() == 1 and other_ws.status == S.EXPIRED
    ev = events(db_session, old1, "agent_run.expired")[0]
    assert ev.actor == "system"


# ------------------------------------------------------------------ approvals pause / resume
def _pending_exec(db, agents, tools, uid="u1"):
    c = build_agent_context(member(uid), "task_writer", agents, tools)
    ex = c.execution_service(db).submit(c.principal, "aceden.task.update", {"task_id": 5})
    assert ex.status == ExecutionStatus.AWAITING_APPROVAL
    return c, ex


def test_run_waits_on_a_real_approval_then_resumes(svc, db_session, agents, tools, clock):
    c, ex = _pending_exec(db_session, agents, tools)
    p = c.principal
    run = svc.create(member(), "task_writer", "g")
    svc.start(p, run.id)
    svc.wait_for_approval(p, run.id, ex.id)
    assert run.status == S.WAITING_APPROVAL and run.pending_execution_id == ex.id
    assert run.expires_at.replace(tzinfo=timezone.utc) == T0 + timedelta(seconds=86400)    # approval wait window
    with pytest.raises(RunStateError):
        svc.resume(p, run.id)                               # not decided yet
    approval = db_session.scalar(select(Approval).where(Approval.execution_id == ex.id))
    ApprovalService(db_session).decide(approval.id, member("u2", role=Role.ADMIN), approve=True)
    c.execution_service(db_session).execute_approved(p, ex.id)
    svc.resume(p, run.id)
    assert run.status == S.RUNNING and run.pending_execution_id is None
    assert run.expires_at.replace(tzinfo=timezone.utc) == T0 + timedelta(seconds=120)      # fresh active window
    ev = events(db_session, run, "agent_run.waiting_approval")[0]
    assert ev.execution_id == ex.id and events(db_session, run, "agent_run.resumed")[0].execution_id == ex.id


def test_rejected_approval_also_lets_the_run_continue_to_decide(svc, db_session, agents, tools):
    c, ex = _pending_exec(db_session, agents, tools)
    run = svc.create(member(), "task_writer", "g")
    svc.start(c.principal, run.id)
    svc.wait_for_approval(c.principal, run.id, ex.id)
    approval = db_session.scalar(select(Approval).where(Approval.execution_id == ex.id))
    ApprovalService(db_session).decide(approval.id, member("u2", role=Role.ADMIN), approve=False)
    svc.resume(c.principal, run.id)
    svc.fail(c.principal, run.id, "approval_rejected")
    assert run.status == S.FAILED


def test_waiting_run_can_be_cancelled_and_approval_wait_expires(svc, db_session, agents, tools, clock):
    c, ex = _pending_exec(db_session, agents, tools)
    a = svc.create(member(), "task_writer", "g")
    svc.start(c.principal, a.id)
    svc.wait_for_approval(c.principal, a.id, ex.id)
    assert svc.cancel(member(), a.id).status == S.CANCELLED
    c2, ex2 = _pending_exec(db_session, agents, tools)
    b = svc.create(member(), "task_writer", "g2")
    svc.start(c2.principal, b.id)
    svc.wait_for_approval(c2.principal, b.id, ex2.id)
    clock.advance(seconds=86401)
    assert svc.expire_overdue("w1") >= 1 and b.status == S.EXPIRED


def test_wait_for_approval_rejects_foreign_or_wrong_state_executions(svc, db_session, agents, tools):
    c, ex = _pending_exec(db_session, agents, tools)
    run = svc.create(member(), "task_writer", "g")
    svc.start(c.principal, run.id)
    ok_exec = c.execution_service(db_session).submit(c.principal, "aceden.task.list", {})        # already SUCCEEDED
    other_agent = build_agent_context(member(), "ops_agent", agents, tools)
    ops_exec = other_agent.execution_service(db_session).submit(other_agent.principal, "system.ping", {})
    for bad in (ok_exec.id, ops_exec.id, "no-such-id"):
        with pytest.raises(RunStateError):
            svc.wait_for_approval(c.principal, run.id, bad)
    u2c, u2ex = _pending_exec(db_session, agents, tools, uid="u2")                           # another user's execution
    with pytest.raises(RunStateError):
        svc.wait_for_approval(c.principal, run.id, u2ex.id)
    assert run.status == S.RUNNING


# ------------------------------------------------------------------ authority / visibility
def test_runs_are_private_to_their_user_unless_manager(svc, agents, tools):
    run = svc.create(member("u1"), "ops_agent", "g")
    assert svc.get(member("u1"), run.id).id == run.id
    for outsider in (member("u2"), member("u2", role=Role.VIEWER)):
        with pytest.raises(RunNotFoundError):
            svc.get(outsider, run.id)
        with pytest.raises(RunNotFoundError):
            svc.cancel(outsider, run.id)
    assert svc.get(member("u2", role=Role.ADMIN), run.id).id == run.id                    # admin can see
    assert [r.id for r in svc.list(member("u2"))] == []
    assert [r.id for r in svc.list(member("u2", role=Role.ADMIN))] == [run.id]
    assert svc.cancel(member("u2", role=Role.ADMIN), run.id).status == S.CANCELLED         # and cancel


def test_agent_principals_are_limited_to_their_own_runs_and_cannot_cancel(svc, agents, tools):
    mine = svc.create(member(), "ops_agent", "g")
    other_agents_run = svc.create(member(), "task_writer", "g2")
    p = agent_p(agents, tools, "ops_agent")
    svc.start(p, mine.id)                                                                  # drives own run
    with pytest.raises(RunNotFoundError):
        svc.start(p, other_agents_run.id)                                                  # another agent's run
    with pytest.raises(RunNotFoundError):
        svc.get(p, other_agents_run.id)
    assert [r.id for r in svc.list(p)] == [mine.id]
    with pytest.raises(RunForbiddenError):
        svc.cancel(p, mine.id)
    admin_agent = agent_p(agents, tools, "ops_agent", uid="u2", role=Role.ADMIN)           # admin's agent: still no
    with pytest.raises(RunNotFoundError):
        svc.get(admin_agent, mine.id)
    with pytest.raises(RunNotFoundError):                                                  # another user's agent
        svc.charge(admin_agent, mine.id, "step")


def test_manager_cannot_drive_someone_elses_run(svc):
    run = svc.create(member("u1"), "ops_agent", "g")
    admin = member("u2", role=Role.ADMIN)
    for call in (lambda: svc.start(admin, run.id), lambda: svc.fail(admin, run.id, "x"),
                 lambda: svc.charge(admin, run.id, "step")):
        with pytest.raises(RunNotFoundError):
            call()
    assert run.status == S.QUEUED


def test_workspace_isolation_for_every_operation(svc, db_session):
    run = svc.create(member("u1", "w1"), "ops_agent", "g")
    other = member("u1", "w2", Role.OWNER)                                                 # same user, other workspace
    owner_other = Principal(user_id="u3", workspace_id="w2", permissions=frozenset({"*"}))
    for who in (other, owner_other):
        for call in (lambda: svc.get(who, run.id), lambda: svc.cancel(who, run.id), lambda: svc.start(who, run.id),
                     lambda: svc.charge(who, run.id, "step"), lambda: svc.fail(who, run.id, "x"),
                     lambda: svc.checkpoint(who, run.id), lambda: svc.succeed(who, run.id)):
            with pytest.raises(RunNotFoundError):
                call()
        assert svc.list(who) == []
    assert run.status == S.QUEUED and events(db_session, run) and all(e.workspace_id == "w1" for e in events(db_session, run))


def test_list_filters_status_orders_newest_first_and_caps_limit(svc, clock):
    p = member()
    runs = []
    for i in range(3):
        runs.append(svc.create(p, "ops_agent", f"g{i}"))
        clock.advance(seconds=1)
    svc.start(p, runs[0].id)
    assert {r.id for r in svc.list(p)} == {r.id for r in runs}
    assert [r.id for r in svc.list(p, status=S.RUNNING)] == [runs[0].id]
    assert len(svc.list(p, limit=2)) == 2 and len(svc.list(p, limit=-5)) == 1


def test_missing_run_id_is_not_found(svc):
    with pytest.raises(RunNotFoundError):
        svc.get(member(), "nope")
