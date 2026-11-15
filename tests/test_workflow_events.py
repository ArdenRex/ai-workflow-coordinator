"""Substep 9.4: internal events, trigger matching and idempotent starts."""
import json

import pytest
from sqlalchemy import func, select, update

from app.config import Settings
from app.identity.roles import permissions_for
from app.kernel.permissions import Principal
from app.models import Role, SystemEvent, ToolExecution
from app.models.agents import AgentRun
from app.models.enums import WorkflowRunStatus as R
from app.models.workflows import WorkflowEventRecord, WorkflowRecord, WorkflowRunRecord
from app.workflows.definition import EventTrigger, ManualTrigger, WorkflowDefinition, WorkflowStep
from app.workflows.errors import (InvalidWorkflowRequestError, WorkflowConflictError, WorkflowForbiddenError,
                                  WorkflowNotFoundError)
from app.workflows.events import EventService
from app.workflows.store import WorkflowService
from tests.test_agent_runs import Clock, agents, clock, member, svc, tools, users  # noqa: F401
from tests.test_workflow_engine import PING, World, world  # noqa: F401

pytestmark = pytest.mark.usefixtures("seed_workspaces")
CANARY = "CANARY-event-9902"
LEAD = "lead.created"


def admin(uid="u1", ws="w1"):
    return member(uid, ws, Role.ADMIN)


def settings(**kw):
    return Settings(app_env="test", database_url="sqlite:///:memory:", _env_file=None, **kw)


def mkdef(key, events=(LEAD,), version=1, manual=False):
    trig = tuple(EventTrigger(e) for e in events) + ((ManualTrigger(),) if manual or not events else ())
    return WorkflowDefinition(key, key.title(), (WorkflowStep("a", "ops_agent", f"Check system status {CANARY}"),),
                              version=version, triggers=trig)


@pytest.fixture
def env(db_session, agents, clock):
    def build(**kw):
        s = settings(**kw)
        wf = WorkflowService(db_session, agents, s, clock=clock)
        return SimpleEnv(db_session, wf, EventService(db_session, wf, s))
    return build


class SimpleEnv:
    def __init__(self, db, wf, events):
        self.db, self.wf, self.events = db, wf, events

    def define(self, *defs, who=None):
        for d in defs:
            self.wf.define(who or admin(), d)

    def emit(self, ref="evt-1", type=LEAD, who=None):
        return self.events.emit(who or member(), type, ref)


def n(db, model):
    return db.scalar(select(func.count()).select_from(model))


def wf_events(db, *types):
    return [e for e in db.scalars(select(SystemEvent).order_by(SystemEvent.created_at, SystemEvent.id))
            if e.event_type in types]


# ================================================================== matching and starting
def test_an_event_starts_a_pending_run_for_each_matching_workflow_only(env, db_session):
    e = env()
    e.define(mkdef("alpha"), mkdef("beta"), mkdef("gamma", events=("invoice.paid",)), mkdef("delta", events=(), manual=True))
    res = e.emit()
    runs = [e.wf.get_run(member(), r) for r in res.run_ids]
    assert [r.workflow_key for r in runs] == ["alpha", "beta"] and not res.duplicate
    assert all(r.status == R.PENDING and r.requested_by == "u1" and r.trigger_type == "event"
               and r.trigger_ref == res.event.id for r in runs)
    ev = res.event
    assert (ev.matched_count, ev.started_count, ev.skipped_count, ev.truncated) == (2, 2, 0, False)
    assert ev.dispatched_at is not None and ev.emitted_by == "u1"
    assert n(db_session, AgentRun) == 0 and n(db_session, ToolExecution) == 0       # starting runs executes nothing


def test_an_event_nobody_listens_to_is_recorded_and_starts_nothing(env, db_session):
    e = env()
    e.define(mkdef("alpha"))
    res = e.emit(type="other.thing")
    assert res.run_ids == () and res.event.matched_count == 0 and res.event.dispatched_at is not None
    assert n(db_session, WorkflowRunRecord) == 0


def test_only_the_newest_active_version_decides(env):
    e = env()
    e.define(mkdef("alpha"))
    e.define(mkdef("alpha", events=("invoice.paid",), version=2))                  # v2 no longer listens for leads
    assert e.emit("e1").run_ids == ()
    e.wf.archive(admin(), "alpha", 2)                                               # v1 is the newest ACTIVE one again
    res = e.emit("e2")
    assert [e.wf.get_run(member(), r).version for r in res.run_ids] == [1]


def test_archived_workflows_are_not_started(env):
    e = env()
    e.define(mkdef("alpha"), mkdef("beta"))
    e.wf.archive(admin(), "alpha", 1)
    assert [e.wf.get_run(member(), r).workflow_key for r in e.emit().run_ids] == ["beta"]


def test_workspaces_are_isolated(env):
    e = env()
    e.define(mkdef("alpha"))
    res = e.emit(who=member(ws="w2"))
    assert res.run_ids == () and res.event.workspace_id == "w2"
    assert n(e.db, WorkflowRunRecord) == 0
    e.define(mkdef("alpha"), who=admin(ws="w2"))
    assert len(e.emit("again", who=member(ws="w2")).run_ids) == 1
    assert all(r.workspace_id == "w2" for r in e.db.scalars(select(WorkflowRunRecord)))


def test_an_event_started_run_is_an_ordinary_run_that_only_the_emitter_drives(world, db_session):
    w = world(PING)
    w.wf.define(admin(), mkdef("alpha"))
    events = EventService(db_session, w.wf, w.runs.settings)
    res = events.emit(member(), LEAD, "evt-1")
    run_id = res.run_ids[0]
    from app.workflows.errors import WorkflowForbiddenError as Forbidden
    with pytest.raises(Forbidden):
        w.engine.drive(member("u3", role=Role.ADMIN), run_id)
    out = w.engine.drive(member(), run_id)
    assert out.state == "completed" and out.run.status == R.SUCCEEDED and n(db_session, ToolExecution) == 1


# ================================================================== idempotency
def test_redelivery_returns_the_same_event_and_runs_and_starts_nothing_more(env, db_session):
    e = env()
    e.define(mkdef("alpha"), mkdef("beta"))
    first = e.emit()
    again = e.emit()
    assert again.duplicate and again.event.id == first.event.id and again.run_ids == first.run_ids
    assert n(db_session, WorkflowRunRecord) == 2 and n(db_session, WorkflowEventRecord) == 1
    assert len(wf_events(db_session, "workflow.event_received")) == 1
    assert len(wf_events(db_session, "workflow.event_dispatched")) == 1


def test_redelivery_does_not_retro_start_a_workflow_defined_later(env):
    e = env()
    e.define(mkdef("alpha"))
    first = e.emit()
    e.define(mkdef("beta"))
    again = e.emit()
    assert again.run_ids == first.run_ids and len(again.run_ids) == 1
    assert len(e.emit("evt-2").run_ids) == 2                                        # a NEW event sees both


def test_same_ref_with_another_type_is_a_different_event(env):
    e = env()
    e.define(mkdef("alpha", events=(LEAD, "lead.updated")))
    a, b = e.emit("same", LEAD), e.emit("same", "lead.updated")
    assert a.event.id != b.event.id and a.run_ids != b.run_ids


def test_an_interrupted_dispatch_is_finished_on_redelivery_without_double_starting(env, db_session):
    e = env()
    e.define(mkdef("alpha"), mkdef("beta"))
    first = e.emit()
    db_session.execute(update(WorkflowEventRecord).where(WorkflowEventRecord.id == first.event.id)
                       .values(dispatched_at=None, matched_count=0, started_count=0))   # "crashed" before recording
    db_session.commit()
    again = e.emit()
    assert again.run_ids == first.run_ids and again.event.dispatched_at is not None
    assert again.event.started_count == 2 and n(db_session, WorkflowRunRecord) == 2


def test_a_redelivery_from_another_user_is_a_conflict(env):
    e = env()
    e.define(mkdef("alpha"))
    e.emit()
    with pytest.raises(WorkflowConflictError):
        e.emit(who=member("u2"))


# ================================================================== authority and validation
def test_viewers_and_agents_cannot_emit(env, db_session):
    e = env()
    e.define(mkdef("alpha"))
    with pytest.raises(WorkflowForbiddenError):
        e.emit(who=member(role=Role.VIEWER))
    broad = Principal(user_id="u1", workspace_id="w1", permissions=permissions_for(Role.OWNER), agent="ops_agent",
                      agent_scope=frozenset({"agent:*", "system:read"}))
    assert broad.can("agent:run")                                                   # the scope alone would allow it
    with pytest.raises(WorkflowForbiddenError):
        e.emit(who=broad)
    assert n(db_session, WorkflowEventRecord) == 0 and n(db_session, WorkflowRunRecord) == 0


@pytest.mark.parametrize("bad", ["", "Lead.Created", "lead..created", "1lead", "a.b.c.d.e", "lead created", None, 5])
def test_event_type_is_validated_before_anything_is_stored(env, db_session, bad):
    e = env()
    with pytest.raises(InvalidWorkflowRequestError):
        e.emit(type=bad)
    assert n(db_session, WorkflowEventRecord) == 0


@pytest.mark.parametrize("bad", ["", "bad ref!", "x" * 129, None, 7])
def test_event_ref_is_validated(env, db_session, bad):
    e = env()
    with pytest.raises(InvalidWorkflowRequestError):
        e.emit(ref=bad)
    assert n(db_session, WorkflowEventRecord) == 0


def test_event_visibility(env):
    e = env()
    e.define(mkdef("alpha"))
    res = e.emit()
    ev = res.event
    assert e.events.get_event(member(), ev.id).id == ev.id and e.events.get_event(admin("u3"), ev.id).id == ev.id
    assert [x.id for x in e.events.list_events(member())] == [ev.id] and e.events.list_events(member("u2")) == []
    assert [x.id for x in e.events.list_events(admin("u3"))] == [ev.id]
    assert e.events.run_ids(member(), ev.id) == res.run_ids
    for who in (member("u2"), member(ws="w2"), admin(ws="w2")):
        with pytest.raises(WorkflowNotFoundError):
            e.events.get_event(who, ev.id)


# ================================================================== bounds and failure isolation
def test_fanout_is_capped_and_the_truncation_is_recorded(env, db_session):
    e = env(workflow_max_event_fanout=2)
    e.define(mkdef("alpha"), mkdef("beta"), mkdef("gamma"))
    res = e.emit()
    assert [e.wf.get_run(member(), r).workflow_key for r in res.run_ids] == ["alpha", "beta"]
    ev = res.event
    assert (ev.matched_count, ev.started_count, ev.skipped_count, ev.truncated) == (3, 2, 1, True)
    payload = wf_events(db_session, "workflow.event_dispatched")[0].payload
    assert payload["truncated"] is True and payload["skipped"] == 1


def test_the_active_run_limit_skips_and_counts_instead_of_failing_the_event(env, db_session):
    e = env(workflow_max_active_runs=1)
    e.define(mkdef("alpha"), mkdef("beta"))
    res = e.emit()
    assert len(res.run_ids) == 1 and (res.event.started_count, res.event.skipped_count) == (1, 1)
    assert wf_events(db_session, "workflow.event_dispatched")[0].payload["skip_codes"] == {"workflow_limit": 1}


def test_a_tampered_workflow_is_skipped_and_the_others_still_start(env, db_session):
    e = env()
    e.define(mkdef("alpha"), mkdef("beta"))
    rec = db_session.scalar(select(WorkflowRecord).where(WorkflowRecord.workflow_key == "alpha"))
    db_session.execute(update(WorkflowRecord).where(WorkflowRecord.id == rec.id).values(definition={"junk": 1}))
    db_session.commit()
    res = e.emit()
    assert [e.wf.get_run(member(), r).workflow_key for r in res.run_ids] == ["beta"]
    assert res.event.skipped_count == 1
    assert wf_events(db_session, "workflow.event_dispatched")[0].payload["invalid_definitions"] == 1


def test_fanout_setting_is_bounded():
    assert settings().workflow_max_event_fanout == 10
    for bad in (0, 51):
        with pytest.raises(Exception):
            settings(workflow_max_event_fanout=bad)


# ================================================================== content
def test_audit_and_run_rows_never_hold_instructions_or_the_event_reference(env, db_session):
    e = env()
    e.define(mkdef("alpha"))
    ref = "cust-" + CANARY
    e.emit(ref)
    e.emit(ref)
    blob = json.dumps([x.payload for x in wf_events(db_session, "workflow.event_received", "workflow.event_dispatched",
                                                    "workflow.run_created")])
    runs = json.dumps([{c.name: str(getattr(r, c.name)) for c in r.__table__.columns}
                       for r in db_session.scalars(select(WorkflowRunRecord))])
    assert CANARY not in blob and CANARY not in runs
    stored = db_session.scalar(select(WorkflowEventRecord))
    assert stored.event_ref == ref                              # the only place the emitter's reference lives
    assert not hasattr(stored, "payload")
