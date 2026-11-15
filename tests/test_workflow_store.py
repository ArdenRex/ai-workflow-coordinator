"""Substep 9.2: workflow persistence, versioning, run/step state machines, retry bookkeeping, authority, audit."""
import json
from datetime import timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.config import Settings
from app.models import Role, SystemEvent
from app.models.enums import StepState as S
from app.models.enums import WorkflowRunStatus as R
from app.models.enums import WorkflowStatus as W
from app.models.workflows import WorkflowRecord, WorkflowRunRecord, WorkflowStepRecord
from app.workflows.definition import (EventTrigger, ManualTrigger, RetryPolicy, ScheduleTrigger, WorkflowDefinition,
                                      WorkflowStep)
from app.workflows.errors import (InvalidWorkflowError, InvalidWorkflowRequestError, WorkflowCancelledError,
                                  WorkflowConflictError, WorkflowForbiddenError, WorkflowLimitError,
                                  WorkflowNotFoundError, WorkflowStateError)
from app.workflows.store import WorkflowService
from tests.test_agent_runs import (Clock, agents, clock, member, svc, tools, users)  # noqa: F401

pytestmark = pytest.mark.usefixtures("seed_workspaces")
CANARY = "CANARY-instr-55"


def admin(uid="u1", ws="w1"):
    return member(uid, ws, Role.ADMIN)


def settings(**kw):
    return Settings(app_env="test", database_url="sqlite:///:memory:", _env_file=None, **kw)


def step(id, deps=(), agent="ops_agent", text=f"do the thing {CANARY}", **kw):
    return WorkflowStep(id, agent, text, tuple(deps), **kw)


def mkdef(key="daily", version=1, steps=None, triggers=(ManualTrigger(),), name="Daily"):
    steps = steps if steps is not None else [step("a"), step("b", "a", agent="task_writer"), step("c", "a"),
                                             step("d", ("b", "c")), step("e")]
    return WorkflowDefinition(key, name, tuple(steps), version=version, triggers=tuple(triggers))


@pytest.fixture
def ws(db_session, agents, clock):
    return WorkflowService(db_session, agents, settings(), clock=clock)


def ev(db, run=None):
    rows = [e for e in db.scalars(select(SystemEvent).order_by(SystemEvent.created_at, SystemEvent.id))
            if e.event_type.startswith("workflow.")]
    return [e for e in rows if run is None or e.payload.get("run_id") == run.id]


def agent_run(svc, agent="ops_agent", user=None):
    return svc.create(user or member(), agent, "a goal for this step")


def defined(ws, d=None, who=None):
    return ws.define(who or admin(), d or mkdef())


def started(ws, d=None, **kw):
    defined(ws, d)
    run = ws.create_run(member(), (d or mkdef()).id, **kw)
    return ws.start(member(), run.id)


def do(ws, svc, run, key, agent="ops_agent", to=S.SUCCEEDED, **kw):
    ws.begin_step(member(), run.id, key, agent_run(svc, agent).id)
    return ws.finish_step(member(), run.id, key, to, **kw)


# ================================================================== definitions
def test_define_stores_the_definition_and_audits_without_content(ws, db_session):
    rec = defined(ws)
    assert rec.version == 1 and rec.status == W.ACTIVE and rec.workflow_key == "daily"
    assert rec.definition_digest == mkdef().digest() and ws.definition_of(rec) == mkdef()
    events = ev(db_session)
    assert [e.event_type for e in events] == ["workflow.defined"]
    assert CANARY not in json.dumps([e.payload for e in events])
    assert events[0].payload["steps"] == 5 and events[0].payload["definition_sha256"] == rec.definition_digest


@pytest.mark.parametrize("who", [member(role=Role.MEMBER), member(role=Role.VIEWER)])
def test_only_managers_define_and_archive(ws, who):
    with pytest.raises(WorkflowForbiddenError):
        ws.define(who, mkdef())
    defined(ws)
    with pytest.raises(WorkflowForbiddenError):
        ws.archive(who, "daily", 1)


def test_agents_can_do_nothing_here(ws):
    from tests.test_orchestration_store import Principal_with_agent
    defined(ws)
    a = Principal_with_agent()
    run = ws.create_run(member(), "daily")
    for fn in (lambda: ws.define(a, mkdef("other")), lambda: ws.get_definition(a, "daily"),
               lambda: ws.list_definitions(a), lambda: ws.create_run(a, "daily")):
        with pytest.raises(WorkflowForbiddenError):
            fn()
    with pytest.raises(WorkflowNotFoundError):
        ws.get_run(a, run.id)
    assert ws.list_runs(a) == []


def test_an_agent_with_broad_scope_still_cannot_use_workflows(ws):
    from app.identity.roles import permissions_for
    from app.kernel.permissions import Principal
    defined(ws)
    run = ws.create_run(member(), "daily")
    a = Principal(user_id="u1", workspace_id="w1", permissions=permissions_for(Role.OWNER), agent="ops_agent",
                  agent_scope=frozenset({"agent:*", "system:read"}))
    assert a.can("agent:manage") and a.can("agent:run")                           # the scope alone would allow it
    for fn in (lambda: ws.define(a, mkdef("other")), lambda: ws.archive(a, "daily", 1),
               lambda: ws.get_definition(a, "daily"), lambda: ws.create_run(a, "daily")):
        with pytest.raises(WorkflowForbiddenError):
            fn()
    for fn in (lambda: ws.get_run(a, run.id), lambda: ws.start(a, run.id), lambda: ws.cancel(a, run.id)):
        with pytest.raises((WorkflowNotFoundError, WorkflowForbiddenError)):
            fn()
    assert ws.list_runs(a) == []


def test_versions_are_sequential_immutable_and_idempotent(ws, db_session):
    with pytest.raises(WorkflowConflictError):
        ws.define(admin(), mkdef(version=2))                                     # a new key starts at 1
    v1 = defined(ws)
    assert ws.define(admin(), mkdef()).id == v1.id                               # identical resend is a no-op
    with pytest.raises(WorkflowConflictError):
        ws.define(admin(), mkdef(steps=[step("a")]))                             # same version, different content
    with pytest.raises(WorkflowConflictError):
        ws.define(admin(), mkdef(version=3))                                     # cannot skip
    v2 = ws.define(admin(), mkdef(version=2, steps=[step("a")]))
    assert v2.id != v1.id and v1.definition == mkdef().to_dict()                 # v1 untouched
    assert [r.version for r in ws.versions(member(), "daily")] == [1, 2]
    assert ws.get_definition(member(), "daily").version == 2
    assert ws.get_definition(member(), "daily", 1).id == v1.id
    assert len([e for e in ev(db_session) if e.event_type == "workflow.defined"]) == 2


def test_define_validates_against_the_running_system(ws, db_session, agents, clock):
    with pytest.raises(InvalidWorkflowError) as e:
        ws.define(admin(), mkdef(steps=[step("a", agent="ghost_agent")]))
    assert e.value.code == "unknown_agent"
    small = WorkflowService(db_session, agents, settings(workflow_max_steps=2), clock=clock)
    with pytest.raises(InvalidWorkflowError) as e:
        small.define(admin(), mkdef())
    assert e.value.code == "plan_too_large"


def test_definition_count_is_bounded(db_session, agents, clock):
    s = WorkflowService(db_session, agents, settings(workflow_max_definitions=2), clock=clock)
    s.define(admin(), mkdef("one"))
    s.define(admin(), mkdef("two"))
    with pytest.raises(WorkflowLimitError):
        s.define(admin(), mkdef("three"))
    s.define(admin(), mkdef("two", version=2))                                   # new VERSIONS are not new workflows


def test_reading_and_workspace_isolation(ws):
    defined(ws)
    defined(ws, mkdef("weekly"))
    assert sorted(r.workflow_key for r in ws.list_definitions(member())) == ["daily", "weekly"]
    with pytest.raises(WorkflowForbiddenError):
        ws.get_definition(member(role=Role.VIEWER), "daily")
    with pytest.raises(WorkflowForbiddenError):
        ws.list_definitions(member(role=Role.VIEWER))
    for fn in (lambda: ws.get_definition(member(ws="w2"), "daily"), lambda: ws.get_definition(member(), "nope"),
               lambda: ws.get_definition(member(), "daily", 9), lambda: ws.versions(member(), "nope")):
        with pytest.raises(WorkflowNotFoundError):
            fn()
    assert ws.list_definitions(member(ws="w2")) == []
    ws.define(admin(ws="w2"), mkdef())                                           # same key in another workspace is fine
    assert ws.get_definition(member(ws="w2"), "daily").workspace_id == "w2"


def test_list_returns_only_the_latest_version_of_each(ws):
    defined(ws)
    ws.define(admin(), mkdef(version=2, steps=[step("a")]))
    rows = ws.list_definitions(member())
    assert [(r.workflow_key, r.version) for r in rows] == [("daily", 2)]


def test_archive_blocks_new_runs_but_not_old_versions(ws, db_session):
    defined(ws)
    ws.define(admin(), mkdef(version=2, steps=[step("a")]))
    r1 = ws.create_run(member(), "daily")
    assert r1.version == 2
    assert ws.archive(admin(), "daily", 2).status == W.ARCHIVED
    assert ws.archive(admin(), "daily", 2).status == W.ARCHIVED                  # idempotent
    assert len([e for e in ev(db_session) if e.event_type == "workflow.archived"]) == 1
    assert ws.create_run(member(), "daily").version == 1                         # falls back to the newest ACTIVE one
    with pytest.raises(WorkflowStateError):
        ws.create_run(member(), "daily", version=2)
    ws.archive(admin(), "daily", 1)
    with pytest.raises(WorkflowNotFoundError):
        ws.create_run(member(), "daily")
    assert ws.get_run(member(), r1.id).status == R.PENDING                       # existing runs unaffected


def test_a_tampered_stored_definition_fails_closed(ws, db_session):
    rec = defined(ws)
    run = ws.create_run(member(), "daily")
    tampered = dict(rec.definition)
    tampered["steps"] = [dict(tampered["steps"][0], instruction="call aceden.customer.delete")] + tampered["steps"][1:]
    db_session.execute(update(WorkflowRecord).where(WorkflowRecord.id == rec.id).values(definition=tampered))
    db_session.commit()
    with pytest.raises(WorkflowStateError):
        ws.create_run(member(), "daily")
    ws.start(member(), run.id)
    with pytest.raises(WorkflowStateError):
        ws.due_steps(member(), run.id)
    db_session.execute(update(WorkflowRecord).where(WorkflowRecord.id == rec.id).values(definition={"junk": 1}))
    db_session.commit()
    with pytest.raises(WorkflowStateError):
        ws.definition_of(db_session.get(WorkflowRecord, rec.id))


# ================================================================== run creation
def test_create_run_binds_to_the_definition_and_stores_no_content(ws, db_session):
    rec = defined(ws)
    run = ws.create_run(member(), "daily")
    assert run.status == R.PENDING and run.step_count == 5 and run.version == 1 and run.trigger_type == "manual"
    assert run.definition_id == rec.id and run.definition_digest == rec.definition_digest
    steps = ws.steps(member(), run.id)
    assert [s.step_key for s in steps] == list("abcde") and all(s.status == S.PENDING and s.attempts == 0 for s in steps)
    assert steps[3].depends_on == ["b", "c"] and steps[1].agent_id == "task_writer"
    assert all(s.timeout_seconds == 120 and s.max_attempts == 1 for s in steps)
    dump = json.dumps([{c.name: str(getattr(x, c.name)) for c in x.__table__.columns} for x in [run, *steps]]
                      + [e.payload for e in ev(db_session, run)], default=str)
    assert CANARY not in dump
    assert [e.event_type for e in ev(db_session, run)] == ["workflow.run_created"]


def test_step_policy_is_copied_to_the_step_rows(ws):
    d = mkdef(steps=[step("a", retry=RetryPolicy(max_attempts=3, delay_seconds=5), timeout_seconds=30)])
    defined(ws, d)
    s = ws.steps(member(), ws.create_run(member(), "daily").id)[0]
    assert (s.max_attempts, s.timeout_seconds) == (3, 30)


@pytest.mark.parametrize("who", [member(role=Role.VIEWER)])
def test_viewers_cannot_run(ws, who):
    defined(ws)
    with pytest.raises(WorkflowForbiddenError):
        ws.create_run(who, "daily")


def test_runs_are_workspace_isolated(ws):
    defined(ws)
    run = ws.create_run(member(), "daily")
    with pytest.raises(WorkflowNotFoundError):
        ws.create_run(member(ws="w2"), "daily")
    with pytest.raises(WorkflowNotFoundError):
        ws.get_run(member(ws="w2"), run.id)
    with pytest.raises(WorkflowNotFoundError):
        ws.get_run(admin(ws="w2"), run.id)


def test_trigger_rules(ws):
    d = mkdef(triggers=(ManualTrigger(), EventTrigger("lead.created"), ScheduleTrigger(3600)))
    defined(ws, d)
    bad = [dict(trigger=EventTrigger("other.event"), trigger_ref="e1"),       # not declared
           dict(trigger=ScheduleTrigger(60), trigger_ref="slot1"),            # not declared
           dict(trigger=EventTrigger("lead.created")),                        # needs a ref
           dict(trigger=EventTrigger("lead.created"), trigger_ref="bad ref!"),
           dict(trigger=EventTrigger("lead.created"), trigger_ref="x" * 129),
           dict(trigger=ScheduleTrigger(3600)),
           dict(trigger_ref="e1")]                                            # manual takes none
    for kw in bad:
        with pytest.raises(InvalidWorkflowRequestError):
            ws.create_run(member(), "daily", **kw)
    run = ws.create_run(member(), "daily", trigger=EventTrigger("lead.created"), trigger_ref="evt-1")
    assert (run.trigger_type, run.trigger_ref) == ("event", "evt-1")
    assert ws.create_run(member(), "daily", trigger=ScheduleTrigger(3600), trigger_ref="2026-01-01T00:00").trigger_type == "schedule"


def test_a_trigger_ref_starts_at_most_one_run(ws, db_session):
    defined(ws, mkdef(triggers=(EventTrigger("lead.created"),)))
    t = EventTrigger("lead.created")
    first = ws.create_run(member(), "daily", trigger=t, trigger_ref="evt-1")
    assert ws.create_run(member(), "daily", trigger=t, trigger_ref="evt-1").id == first.id      # redelivery
    assert ws.create_run(member(), "daily", trigger=t, trigger_ref="evt-2").id != first.id
    with pytest.raises(WorkflowConflictError):
        ws.create_run(member("u2"), "daily", trigger=t, trigger_ref="evt-1")                     # someone else's
    assert len([e for e in ev(db_session) if e.event_type == "workflow.run_created"]) == 2


def test_idempotency_replays_and_conflicts(ws):
    defined(ws)
    defined(ws, mkdef("other"))
    a = ws.create_run(member(), "daily", idempotency_key="k1")
    assert ws.create_run(member(), "daily", idempotency_key="k1").id == a.id
    with pytest.raises(WorkflowConflictError):
        ws.create_run(member(), "other", idempotency_key="k1")
    with pytest.raises(WorkflowConflictError):
        ws.create_run(member("u2"), "daily", idempotency_key="k1")
    for bad in ("", "x" * 129):
        with pytest.raises(InvalidWorkflowRequestError):
            ws.create_run(member(), "daily", idempotency_key=bad)
    assert ws.create_run(member(), "daily").id != a.id                           # no key: always a new run


def test_active_runs_are_bounded(db_session, agents, clock):
    s = WorkflowService(db_session, agents, settings(workflow_max_active_runs=2), clock=clock)
    s.define(admin(), mkdef())
    r1, r2 = s.create_run(member(), "daily"), s.create_run(member(), "daily")
    with pytest.raises(WorkflowLimitError):
        s.create_run(member(), "daily")
    s.cancel(member(), r1.id)                                                    # finishing frees a slot
    assert s.create_run(member(), "daily").status == R.PENDING


def test_visibility_and_driving(ws):
    defined(ws)
    run = ws.create_run(member(), "daily")
    assert ws.get_run(admin("u3"), run.id).id == run.id and [r.id for r in ws.list_runs(admin("u3"))] == [run.id]
    assert ws.list_runs(member("u2")) == []
    with pytest.raises(WorkflowNotFoundError):
        ws.get_run(member("u2"), run.id)
    with pytest.raises(WorkflowForbiddenError):
        ws.start(admin("u3"), run.id)                                            # an admin sees it, cannot drive it
    with pytest.raises(WorkflowNotFoundError):
        ws.start(member("u2"), run.id)
    assert [r.id for r in ws.list_runs(member(), status=R.PENDING, workflow_key="daily")] == [run.id]
    assert ws.list_runs(member(), status=R.RUNNING) == []


# ================================================================== step ordering and binding
def test_dependency_order_is_enforced_in_the_store(ws, svc):
    run = started(ws)
    with pytest.raises(WorkflowStateError):
        ws.begin_step(member(), run.id, "d", agent_run(svc).id)
    with pytest.raises(WorkflowStateError):
        ws.begin_step(member(), run.id, "b", agent_run(svc, "task_writer").id)
    do(ws, svc, run, "a")
    assert ws.due_steps(member(), run.id) == ["b", "c", "e"]
    do(ws, svc, run, "b", "task_writer")
    with pytest.raises(WorkflowStateError):
        ws.begin_step(member(), run.id, "d", agent_run(svc).id)                  # c has not succeeded


@pytest.mark.parametrize("dead", [S.FAILED, S.CANCELLED])
def test_a_dead_dependency_never_unblocks(ws, svc, dead):
    run = started(ws)
    do(ws, svc, run, "a", to=dead)
    assert ws.due_steps(member(), run.id) == ["e"]
    with pytest.raises(WorkflowStateError):
        ws.begin_step(member(), run.id, "b", agent_run(svc, "task_writer").id)


def test_steps_do_not_start_before_the_run_or_after_cancel_request(ws, svc):
    defined(ws)
    run = ws.create_run(member(), "daily")
    with pytest.raises(WorkflowStateError):
        ws.begin_step(member(), run.id, "a", agent_run(svc).id)
    assert ws.due_steps(member(), run.id) == []
    ws.start(member(), run.id)
    ws.cancel(member(), run.id)
    assert ws.due_steps(member(), run.id) == []
    with pytest.raises(WorkflowStateError):
        ws.begin_step(member(), run.id, "a", agent_run(svc).id)


def test_a_step_binds_to_a_matching_agent_run_used_once(ws, svc):
    d = mkdef(steps=[step("x"), step("y"), step("w", agent="task_writer")])
    run = started(ws, d)
    with pytest.raises(InvalidWorkflowRequestError):
        ws.begin_step(member(), run.id, "w", agent_run(svc, "ops_agent").id)     # wrong agent
    with pytest.raises(InvalidWorkflowRequestError):
        ws.begin_step(member(), run.id, "x", agent_run(svc, user=member("u2")).id)   # someone else's run
    with pytest.raises(InvalidWorkflowRequestError):
        ws.begin_step(member(), run.id, "x", "no-such-run")
    shared = agent_run(svc)
    s = ws.begin_step(member(), run.id, "x", shared.id)
    assert s.status == S.RUNNING and s.attempts == 1 and s.agent_run_id == shared.id and s.deadline_at is not None
    with pytest.raises(WorkflowConflictError):
        ws.begin_step(member(), run.id, "y", shared.id)
    assert ws.steps(member(), run.id)[1].status == S.PENDING


def test_step_state_machine_and_terminal_states_are_final(ws, svc):
    run = started(ws, mkdef(steps=[step("x")]))
    ar = agent_run(svc)
    ws.begin_step(member(), run.id, "x", ar.id)
    assert ws.mark_step_waiting(member(), run.id, "x").status == S.WAITING_APPROVAL
    with pytest.raises(WorkflowStateError):
        ws.mark_step_waiting(member(), run.id, "x")
    assert ws.resume_step(member(), run.id, "x").status == S.RUNNING
    with pytest.raises(WorkflowStateError):
        ws.resume_step(member(), run.id, "x")
    done = ws.finish_step(member(), run.id, "x", S.SUCCEEDED, result={"ok": True})
    assert done.status == S.SUCCEEDED and done.finished_at is not None and done.deadline_at is None
    for fn in (lambda: ws.finish_step(member(), run.id, "x", S.FAILED), lambda: ws.resume_step(member(), run.id, "x"),
               lambda: ws.begin_step(member(), run.id, "x", agent_run(svc).id),
               lambda: ws.fail_attempt(member(), run.id, "x", "boom")):
        with pytest.raises(WorkflowStateError):
            fn()
    with pytest.raises(WorkflowNotFoundError):
        ws.finish_step(member(), run.id, "nope", S.SUCCEEDED)


def test_finish_validation(ws, svc):
    run = started(ws, mkdef(steps=[step("x")]))
    ws.begin_step(member(), run.id, "x", agent_run(svc).id)
    for to in (S.PENDING, S.RUNNING, S.SKIPPED, S.WAITING_APPROVAL):
        with pytest.raises(InvalidWorkflowRequestError):
            ws.finish_step(member(), run.id, "x", to)
    for code in ("Bad Code", "x" * 65):
        with pytest.raises(InvalidWorkflowRequestError):
            ws.finish_step(member(), run.id, "x", S.FAILED, code=code)
    with pytest.raises(InvalidWorkflowRequestError):
        ws.finish_step(member(), run.id, "x", S.SUCCEEDED, result={"blob": "x" * 20_000})
    done = ws.finish_step(member(), run.id, "x", S.FAILED, result={"api_key": "sk-live-abcdefghijklmnop", "n": 1})
    assert done.error_code == "step_failed" and "sk-live" not in json.dumps(done.result) and done.result["n"] == 1


# ================================================================== retries
def retry_def(**policy):
    return mkdef(steps=[step("x", retry=RetryPolicy(**policy)), step("y", "x")])


def test_a_failed_attempt_is_retried_after_the_delay(ws, svc, clock, db_session):
    run = started(ws, retry_def(max_attempts=3, delay_seconds=30))
    ws.begin_step(member(), run.id, "x", agent_run(svc).id)
    s = ws.fail_attempt(member(), run.id, "x", "tool_error")
    assert s.status == S.PENDING and s.attempts == 1 and s.error_code == "tool_error"
    assert s.finished_at is None and s.deadline_at is None
    assert (ws.steps(member(), run.id)[0].next_attempt_at.replace(tzinfo=None) - clock.now.replace(tzinfo=None)
            ) == timedelta(seconds=30)
    assert ws.due_steps(member(), run.id) == []
    clock.advance(seconds=29)
    assert ws.due_steps(member(), run.id) == []
    with pytest.raises(WorkflowStateError):
        ws.begin_step(member(), run.id, "x", agent_run(svc).id)
    clock.advance(seconds=1)
    assert ws.due_steps(member(), run.id) == ["x"]
    s = ws.begin_step(member(), run.id, "x", agent_run(svc).id)
    assert s.attempts == 2 and s.status == S.RUNNING and s.next_attempt_at is None and s.error_code is None
    types = [e.event_type for e in ev(db_session, run)]
    assert types.count("workflow.step_retry_scheduled") == 1 and types.count("workflow.step_started") == 2
    retry_ev = [e for e in ev(db_session, run) if e.event_type == "workflow.step_retry_scheduled"][0]
    assert retry_ev.payload["delay_seconds"] == 30 and retry_ev.payload["attempt"] == 1
    assert CANARY not in json.dumps([e.payload for e in ev(db_session, run)])


def test_attempts_are_bounded_and_the_last_failure_is_final(ws, svc, clock):
    run = started(ws, retry_def(max_attempts=2, delay_seconds=1))
    ws.begin_step(member(), run.id, "x", agent_run(svc).id)
    assert ws.fail_attempt(member(), run.id, "x", "e1").status == S.PENDING
    clock.advance(seconds=1)
    ws.begin_step(member(), run.id, "x", agent_run(svc).id)
    final = ws.fail_attempt(member(), run.id, "x", "e2")
    assert final.status == S.FAILED and final.attempts == 2 and final.error_code == "e2" and final.finished_at
    assert ws.skip_blocked(member(), run.id) == ["y"]
    done = ws.complete(member(), run.id)
    assert done.status == R.FAILED and done.result["attempts"] == {"x": 2, "y": 0}


def test_exponential_backoff_is_capped(ws, svc, clock):
    run = started(ws, retry_def(max_attempts=4, backoff="exponential", delay_seconds=10, max_delay_seconds=25))
    seen = []
    for _ in range(3):
        ws.begin_step(member(), run.id, "x", agent_run(svc).id)
        s = ws.fail_attempt(member(), run.id, "x", "e")
        seen.append(int((s.next_attempt_at.replace(tzinfo=None) - clock.now.replace(tzinfo=None)).total_seconds()))
        clock.advance(seconds=seen[-1])
    assert seen == [10, 20, 25]


def test_no_policy_means_no_retry(ws, svc):
    run = started(ws, mkdef(steps=[step("x")]))
    ws.begin_step(member(), run.id, "x", agent_run(svc).id)
    assert ws.fail_attempt(member(), run.id, "x", "boom").status == S.FAILED


def test_no_retry_once_cancellation_is_requested(ws, svc):
    run = started(ws, retry_def(max_attempts=3, delay_seconds=1))
    ws.begin_step(member(), run.id, "x", agent_run(svc).id)
    ws.cancel(member(), run.id)
    assert ws.fail_attempt(member(), run.id, "x", "boom").status == S.FAILED


def test_exhausted_attempts_cannot_be_restarted_even_if_forced(ws, svc, db_session):
    run = started(ws, retry_def(max_attempts=2))
    db_session.execute(update(WorkflowStepRecord).where(WorkflowStepRecord.run_id == run.id,
                                                        WorkflowStepRecord.step_key == "x").values(attempts=2))
    db_session.commit()
    with pytest.raises(WorkflowStateError):
        ws.begin_step(member(), run.id, "x", agent_run(svc).id)


def test_a_restarted_process_resumes_from_the_database(db_session, agents, clock, svc):
    first = WorkflowService(db_session, agents, settings(), clock=clock)
    run = started(first, retry_def(max_attempts=3, delay_seconds=60))
    first.begin_step(member(), run.id, "x", agent_run(svc).id)
    first.fail_attempt(member(), run.id, "x", "tool_error")
    second = WorkflowService(db_session, agents, settings(), clock=clock)         # "new process"
    assert second.due_steps(member(), run.id) == []
    clock.advance(seconds=60)
    assert second.due_steps(member(), run.id) == ["x"]
    second.begin_step(member(), run.id, "x", agent_run(svc).id)
    second.finish_step(member(), run.id, "x", S.SUCCEEDED)
    do(second, svc, run, "y")
    assert second.complete(member(), run.id).status == R.SUCCEEDED


# ================================================================== run lifecycle
def test_failure_skips_dependents_not_independent_branches_and_fails_the_run(ws, svc, db_session):
    run = started(ws)
    do(ws, svc, run, "a")
    do(ws, svc, run, "b", "task_writer", to=S.FAILED, code="tool_error")
    assert sorted(ws.skip_blocked(member(), run.id)) == ["d"]
    assert ws.skip_blocked(member(), run.id) == []                               # safe to repeat
    do(ws, svc, run, "c")
    do(ws, svc, run, "e")
    done = ws.complete(member(), run.id)
    assert done.status == R.FAILED and done.error_code == "steps_failed" and done.finished_at
    assert done.result["steps"] == {"a": "succeeded", "b": "failed", "c": "succeeded", "d": "skipped", "e": "succeeded"}
    skipped = [s for s in ws.steps(member(), run.id) if s.status == S.SKIPPED]
    assert [s.error_code for s in skipped] == ["dependency_failed"]


def test_complete_needs_every_step_finished(ws, svc):
    run = started(ws)
    with pytest.raises(WorkflowStateError):
        ws.complete(member(), run.id)
    with pytest.raises(WorkflowStateError):
        ws.complete(member(), ws.create_run(member(), "daily").id)               # still pending


def test_full_success_has_a_full_content_free_audit_trail(ws, svc, db_session):
    run = started(ws, mkdef(steps=[step("a"), step("b", "a")]))
    do(ws, svc, run, "a")
    do(ws, svc, run, "b")
    done = ws.complete(member(), run.id)
    assert done.status == R.SUCCEEDED and done.result["outcome"] == "succeeded"
    types = [e.event_type for e in ev(db_session, run)]
    assert types == ["workflow.run_created", "workflow.run_started", "workflow.step_started", "workflow.step_succeeded",
                     "workflow.step_started", "workflow.step_succeeded", "workflow.run_succeeded"]
    assert CANARY not in json.dumps([e.payload for e in ev(db_session)])
    with pytest.raises(WorkflowStateError):
        ws.start(member(), run.id)
    with pytest.raises(WorkflowStateError):
        ws.cancel(member(), run.id)


def test_cancelling_a_pending_run_cancels_everything_at_once(ws):
    defined(ws)
    run = ws.create_run(member(), "daily")
    assert ws.cancel(member(), run.id).status == R.CANCELLED
    assert ws.cancel(member(), run.id).status == R.CANCELLED                     # idempotent
    assert all(s.status == S.CANCELLED for s in ws.steps(member(), run.id))
    with pytest.raises(WorkflowStateError):
        ws.start(member(), run.id)


def test_cancelling_a_running_run_flags_it_and_checkpoint_finishes_it(ws, svc):
    run = started(ws)
    do(ws, svc, run, "a")
    assert ws.checkpoint(member(), run.id).status == R.RUNNING
    ws.begin_step(member(), run.id, "b", agent_run(svc, "task_writer").id)
    flagged = ws.cancel(member(), run.id)
    assert flagged.status == R.RUNNING and flagged.cancel_requested
    assert ws.settle_cancel(member(), run.id).status == R.RUNNING                # a step is mid-flight
    with pytest.raises(WorkflowCancelledError):
        ws.checkpoint(member(), run.id)
    states = {s.step_key: s.status for s in ws.steps(member(), run.id)}
    assert states["a"] == S.SUCCEEDED and states["b"] == S.CANCELLED and states["d"] == S.CANCELLED
    assert ws.get_run(member(), run.id).status == R.CANCELLED
    with pytest.raises(WorkflowCancelledError):
        ws.checkpoint(member(), run.id)


def test_settle_cancel_when_nothing_is_mid_step(ws, svc):
    run = started(ws)
    do(ws, svc, run, "a")
    ws.cancel(member(), run.id)
    assert ws.settle_cancel(admin("u3"), run.id).status == R.CANCELLED


def test_cancel_authority(ws):
    from tests.test_orchestration_store import Principal_with_agent
    defined(ws)
    run = ws.create_run(member(), "daily")
    with pytest.raises(WorkflowNotFoundError):
        ws.cancel(member("u2"), run.id)
    with pytest.raises(WorkflowNotFoundError):
        ws.cancel(Principal_with_agent(), run.id)
    assert ws.cancel(admin("u3"), run.id).status == R.CANCELLED                  # an admin may cancel


def test_stale_objects_cannot_win_a_race(ws, db_session):
    defined(ws)
    run = ws.create_run(member(), "daily")
    stale = db_session.get(WorkflowRunRecord, run.id)
    ws.cancel(member(), run.id)
    with pytest.raises(WorkflowStateError):
        ws._run_cas(stale, R.RUNNING, (R.PENDING,), "u1", "workflow.run_started")
    assert ws.get_run(member(), run.id).status == R.CANCELLED


def test_database_constraints_back_the_service(ws, db_session):
    rec = defined(ws)
    run = ws.create_run(member(), "daily")
    bad = [WorkflowRecord(workspace_id="w1", created_by="u1", workflow_key="daily", version=1, name="x",
                          definition={}, definition_digest="d"),                  # duplicate version
           WorkflowRecord(workspace_id="w1", created_by="u1", workflow_key="zero", version=0, name="x",
                          definition={}, definition_digest="d"),
           WorkflowStepRecord(run_id=run.id, workspace_id="w1", step_key="a", position=9, agent_id="ops_agent",
                              depends_on=[], timeout_seconds=1),                  # duplicate step key
           WorkflowStepRecord(run_id=run.id, workspace_id="w1", step_key="zz", position=-1, agent_id="ops_agent",
                              depends_on=[], timeout_seconds=1),
           WorkflowStepRecord(run_id=run.id, workspace_id="w1", step_key="zz", position=1, agent_id="ops_agent",
                              depends_on=[], timeout_seconds=1, attempts=-1)]
    for row in bad:
        db_session.add(row)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()
    def ref_row():
        return WorkflowRunRecord(workspace_id="w1", requested_by="u1", definition_id=rec.id, workflow_key="daily",
                                 version=1, definition_digest="d", trigger_type="event", trigger_ref="r1", step_count=1)

    db_session.add(ref_row())
    db_session.commit()
    db_session.add(ref_row())                                                    # the same ref cannot start twice
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_workflow_limit_settings_are_bounded():
    s = settings()
    assert (s.workflow_max_definitions, s.workflow_max_active_runs) == (100, 20)
    for name, bad in (("workflow_max_definitions", 0), ("workflow_max_definitions", 1001),
                      ("workflow_max_active_runs", 0), ("workflow_max_active_runs", 201)):
        with pytest.raises(Exception):
            settings(**{name: bad})
