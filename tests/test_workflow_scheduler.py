"""Substep 9.5: armed schedules and the bounded, restart-safe scheduler tick."""
import json
from datetime import timedelta, timezone

import pytest
from sqlalchemy import func, select, update

from app.config import Settings
from app.models import Membership, Role, SystemEvent, ToolExecution
from app.models.agents import AgentRun
from app.models.enums import WorkflowRunStatus as R
from app.models.identity import User
from app.models.workflows import WorkflowRecord, WorkflowRunRecord, WorkflowScheduleRecord
from app.workflows.definition import (EventTrigger, ManualTrigger, RetryPolicy, ScheduleTrigger, WorkflowDefinition,
                                      WorkflowStep)
from app.workflows.errors import (InvalidWorkflowError, InvalidWorkflowRequestError, WorkflowForbiddenError,
                                  WorkflowLimitError, WorkflowNotFoundError)
from app.workflows.events import EventService
from app.workflows.scheduler import ScheduleService, Scheduler, principal_from_membership
from tests.test_agent_runs import Clock, agents, clock, member, svc, tools, users  # noqa: F401
from tests.test_workflow_engine import PING, flaky, world  # noqa: F401
from tests.test_agent_context import CALLS  # noqa: F401

pytestmark = pytest.mark.usefixtures("seed_workspaces")
CANARY = "CANARY-sched-4417"
HOUR = 3600


def admin(uid="u1", ws="w1"):
    return member(uid, ws, Role.ADMIN)


def mkdef(key="nightly", intervals=(HOUR,), version=1, extra=(), retry=None):
    step = WorkflowStep("a", "ops_agent", f"Check system status {CANARY}", retry=retry or RetryPolicy())
    return WorkflowDefinition(key, key.title(), (step,), version=version,
                              triggers=tuple(ScheduleTrigger(i) for i in intervals) + tuple(extra) or (ManualTrigger(),))


class Env:
    def __init__(self, w, db, pf=None, **settings_kw):
        self.w, self.db = w, db
        s = w.runs.settings
        for k, v in settings_kw.items():
            object.__setattr__(s, k, v) if False else setattr(s, k, v)
        self.sched = ScheduleService(db, w.wf, s)
        self.scheduler = Scheduler(db, w.wf, w.engine, s, principal_for=pf or (lambda ws, uid: admin(uid, ws)))

    def define(self, d=None, who=None):
        return self.w.wf.define(who or admin(), d or mkdef())

    def arm(self, key="nightly", interval=HOUR, who=None):
        return self.sched.arm(who or admin(), key, interval)

    def runs(self):
        return list(self.db.scalars(select(WorkflowRunRecord).order_by(WorkflowRunRecord.created_at)))

    def row(self, s):
        self.db.refresh(s)
        return s


@pytest.fixture
def env(world, db_session):
    def build(*script, **kw):
        pf = kw.pop("pf", None)
        return Env(world(*script), db_session, pf, **kw)
    return build


def n(db, model):
    return db.scalar(select(func.count()).select_from(model))


def sevents(db, *types):
    return [e for e in db.scalars(select(SystemEvent).order_by(SystemEvent.created_at, SystemEvent.id))
            if e.event_type in types]


# ================================================================== arming
def test_arming_creates_a_schedule_whose_first_fire_is_one_interval_away(env, db_session):
    e = env()
    e.define()
    s = e.arm()
    assert s.enabled and s.armed_by == "u1" and s.fired_count == 0
    assert s.next_fire_at.replace(tzinfo=None) == e.w.clock.now.replace(tzinfo=None) + timedelta(hours=1)
    assert e.arm().id == s.id and n(db_session, WorkflowScheduleRecord) == 1            # idempotent
    ev = sevents(db_session, "workflow.schedule_armed")
    assert len(ev) == 1 and CANARY not in json.dumps(ev[0].payload)


def test_only_managers_arm_and_disarm_and_agents_never(env):
    from app.identity.roles import permissions_for
    from app.kernel.permissions import Principal
    e = env()
    e.define()
    e.arm()
    broad = Principal(user_id="u1", workspace_id="w1", permissions=permissions_for(Role.OWNER), agent="ops_agent",
                      agent_scope=frozenset({"agent:*"}))
    assert broad.can("agent:manage")
    for who in (member(), member(role=Role.VIEWER), broad):
        with pytest.raises(WorkflowForbiddenError):
            e.sched.arm(who, "nightly", HOUR)
        with pytest.raises(WorkflowForbiddenError):
            e.sched.disarm(who, "nightly", HOUR)


def test_arming_needs_a_declared_schedule_trigger_on_an_active_workflow(env):
    e = env()
    e.define(mkdef("manualonly", intervals=(), extra=(ManualTrigger(),)))
    e.define(mkdef("evented", intervals=(), extra=(EventTrigger("lead.created"),)))
    e.define()
    for key, interval in (("manualonly", HOUR), ("evented", HOUR), ("nightly", 7200)):
        with pytest.raises(InvalidWorkflowRequestError):
            e.arm(key, interval)
    with pytest.raises(WorkflowNotFoundError):
        e.arm("ghost")
    with pytest.raises(InvalidWorkflowError):
        e.arm("nightly", 59)
    e.w.wf.archive(admin(), "nightly", 1)
    with pytest.raises(WorkflowNotFoundError):
        e.arm()


def test_schedule_count_is_bounded(env):
    e = env(workflow_max_schedules=2)
    for k in ("a", "b", "c"):
        e.define(mkdef(k))
    e.arm("a")
    e.arm("b")
    with pytest.raises(WorkflowLimitError):
        e.arm("c")


def test_disarm_is_idempotent_and_rearming_resets_the_clock_and_owner(env):
    e = env()
    e.define()
    s = e.arm()
    assert not e.sched.disarm(admin(), "nightly", HOUR).enabled
    assert e.sched.disarm(admin(), "nightly", HOUR).disabled_reason == "disarmed"
    assert len(sevents(e.db, "workflow.schedule_disabled")) == 1
    with pytest.raises(WorkflowNotFoundError):
        e.sched.disarm(admin(), "nightly", 7200)
    e.w.clock.advance(hours=5)
    again = e.arm(who=admin("u3"))
    assert again.id == s.id and again.enabled and again.armed_by == "u3" and again.disabled_reason is None
    assert again.next_fire_at.replace(tzinfo=None) == e.w.clock.now.replace(tzinfo=None) + timedelta(hours=1)


def test_listing_and_workspace_isolation(env):
    e = env()
    e.define()
    e.arm()
    assert [s.workflow_key for s in e.sched.list_schedules(member())] == ["nightly"]
    assert e.sched.list_schedules(member(ws="w2")) == []
    with pytest.raises(WorkflowForbiddenError):
        e.sched.list_schedules(member(role=Role.VIEWER))
    with pytest.raises(WorkflowNotFoundError):
        e.sched.disarm(admin(ws="w2"), "nightly", HOUR)


# ================================================================== firing
def test_nothing_fires_before_the_slot_and_one_run_fires_at_it(env, db_session):
    e = env()
    e.define()
    s = e.arm()
    e.w.clock.advance(minutes=59)
    assert e.scheduler.tick(drive=False).fired == 0 and e.runs() == []
    e.w.clock.advance(minutes=1)
    slot = int((e.w.clock.now.replace(tzinfo=None) - timedelta(0)).replace(tzinfo=timezone.utc).timestamp())
    t = e.scheduler.tick(drive=False)
    assert t.fired == 1 and len(e.runs()) == 1
    run = e.runs()[0]
    assert run.status == R.PENDING and run.trigger_type == "schedule" and run.requested_by == "u1"
    assert run.trigger_ref == f"{s.id}:{slot}" and n(db_session, AgentRun) == 0
    s = e.row(s)
    assert s.fired_count == 1 and s.next_fire_at.replace(tzinfo=None) == e.w.clock.now.replace(tzinfo=None) + timedelta(hours=1)
    assert e.scheduler.tick(drive=False).fired == 0 and len(e.runs()) == 1               # same moment: nothing more


def test_downtime_fires_one_run_with_no_backfill(env, db_session):
    e = env()
    e.define()
    s = e.arm()
    e.w.clock.advance(hours=10, minutes=30)
    assert e.scheduler.tick(drive=False).fired == 1
    assert len(e.runs()) == 1
    s = e.row(s)
    assert s.next_fire_at.replace(tzinfo=None) == e.w.clock.now.replace(tzinfo=None) + timedelta(minutes=30)
    assert sevents(db_session, "workflow.schedule_fired")[0].payload["missed_slots"] == 9
    assert e.scheduler.tick(drive=False).fired == 0


def test_a_crash_between_creating_the_run_and_advancing_never_double_starts(env, db_session):
    e = env()
    e.define()
    s = e.arm()
    e.w.clock.advance(hours=1)
    seen = e.row(s).next_fire_at
    e.scheduler.tick(drive=False)
    db_session.execute(update(WorkflowScheduleRecord).where(WorkflowScheduleRecord.id == s.id)
                       .values(next_fire_at=seen, fired_count=0))                 # "crashed" before the advance landed
    db_session.commit()
    t = e.scheduler.tick(drive=False)
    assert t.fired == 1 and len(e.runs()) == 1                                    # same slot -> same run, adopted
    assert e.row(s).fired_count == 1 and e.row(s).next_fire_at.replace(tzinfo=None) > e.w.clock.now.replace(tzinfo=None)


def test_a_tick_that_lost_the_race_for_a_slot_changes_nothing(env, db_session):
    from types import SimpleNamespace
    e = env()
    e.define()
    s = e.arm()
    e.w.clock.advance(hours=1)
    snap = SimpleNamespace(id=s.id, workspace_id=s.workspace_id, armed_by=s.armed_by, workflow_key=s.workflow_key,
                           interval_seconds=s.interval_seconds, next_fire_at=s.next_fire_at, last_fired_at=None)
    assert e.scheduler.tick(drive=False).fired == 1                               # the winner
    from app.workflows.scheduler import TickResult
    loser = TickResult()
    e.scheduler._fire(snap, e.w.clock.now, loser)                                 # the loser still holds the old slot
    assert (loser.fired, loser.skipped) == (0, 0) and len(e.runs()) == 1
    assert e.row(s).fired_count == 1 and len(sevents(db_session, "workflow.schedule_fired")) == 1


def test_a_slot_is_skipped_while_the_previous_run_is_still_live(env):
    e = env()
    e.define()
    s = e.arm()
    e.w.clock.advance(hours=1)
    assert e.scheduler.tick(drive=False).fired == 1
    e.w.clock.advance(hours=1)
    t = e.scheduler.tick(drive=False)
    assert (t.fired, t.skipped) == (0, 1) and len(e.runs()) == 1
    s = e.row(s)
    assert s.skipped_count == 1 and s.enabled and s.next_fire_at.replace(tzinfo=None) > e.w.clock.now.replace(tzinfo=None)
    assert sevents(e.db, "workflow.schedule_skipped")[0].payload["reason"] == "overlap"


def test_a_full_run_limit_skips_the_slot_but_keeps_the_schedule(env):
    e = env(workflow_max_active_runs=1)
    e.define(mkdef("a"))
    e.define(mkdef("b"))
    e.arm("a")
    e.arm("b")
    e.w.clock.advance(hours=1)
    t = e.scheduler.tick(drive=False)
    assert (t.fired, t.skipped) == (1, 1) and all(s.enabled for s in e.db.scalars(select(WorkflowScheduleRecord)))


@pytest.mark.parametrize("how,reason", [("v2_without_trigger", "trigger_removed"), ("archived", "workflow_unavailable"),
                                         ("tampered", "definition_invalid")])
def test_a_schedule_whose_workflow_changed_disables_itself(env, db_session, how, reason):
    e = env()
    rec = e.define()
    s = e.arm()
    if how == "v2_without_trigger":
        e.define(mkdef(version=2, intervals=(), extra=(ManualTrigger(),)))
    elif how == "archived":
        e.w.wf.archive(admin(), "nightly", 1)
    else:
        db_session.execute(update(WorkflowRecord).where(WorkflowRecord.id == rec.id).values(definition={"junk": 1}))
        db_session.commit()
    e.w.clock.advance(hours=1)
    t = e.scheduler.tick(drive=False)
    s = e.row(s)
    assert t.disabled == 1 and t.fired == 0 and not s.enabled and s.disabled_reason == reason and e.runs() == []
    e.w.clock.advance(hours=5)
    assert e.scheduler.tick(drive=False).disabled == 0                            # a disabled schedule never fires


def test_an_owner_who_lost_access_disables_the_schedule_instead_of_running_with_stale_authority(env):
    owners = {"u1": admin()}
    e = env(pf=lambda ws, uid: owners.get(uid))
    e.define()
    s = e.arm()
    owners.clear()                                                                # removed from the workspace
    e.w.clock.advance(hours=1)
    t = e.scheduler.tick(drive=False)
    assert t.disabled == 1 and e.runs() == [] and e.row(s).disabled_reason == "owner_unavailable"


def test_an_owner_who_is_no_longer_an_admin_cannot_keep_a_schedule_running(env):
    owners = {"u1": admin()}
    e = env(pf=lambda ws, uid: owners.get(uid))
    e.define()
    s = e.arm()
    owners["u1"] = member()                                                       # demoted: can run, cannot manage
    e.w.clock.advance(hours=1)
    assert e.scheduler.tick(drive=False).disabled == 1 and e.row(s).disabled_reason == "owner_unavailable"


def test_firing_is_bounded_per_tick(env):
    e = env(workflow_tick_max_schedules=2)
    for k in ("a", "b", "c"):
        e.define(mkdef(k))
        e.arm(k)
    e.w.clock.advance(hours=1)
    assert e.scheduler.tick(drive=False).fired == 2
    assert e.scheduler.tick(drive=False).fired == 1                               # the rest on the next tick


# ================================================================== driving
def test_a_tick_fires_and_drives_a_scheduled_run_to_completion(env, db_session):
    e = env(PING)
    e.define()
    e.arm()
    e.w.clock.advance(hours=1)
    t = e.scheduler.tick()
    assert t.fired == 1 and t.driven == 1 and t.states == {"completed": 1} and t.errors == {}
    run = e.runs()[0]
    assert run.status == R.SUCCEEDED and n(db_session, ToolExecution) == 1
    again = e.scheduler.tick()
    assert (again.fired, again.driven) == (0, 0) and n(db_session, AgentRun) == 1  # nothing re-runs


def test_event_started_runs_are_driven_but_manual_runs_are_not(env, db_session):
    e = env(PING)
    ev_def = mkdef("onlead", intervals=(), extra=(EventTrigger("lead.created"),))
    e.define(ev_def)
    e.define(mkdef("manual", intervals=(), extra=(ManualTrigger(),)))
    manual = e.w.wf.create_run(member(), "manual")
    EventService(db_session, e.w.wf, e.w.runs.settings).emit(member(), "lead.created", "evt-1")
    t = e.scheduler.tick()
    assert t.driven == 1 and t.states == {"completed": 1}
    statuses = {r.workflow_key: r.status for r in e.runs()}
    assert statuses == {"manual": R.PENDING, "onlead": R.SUCCEEDED} and e.w.wf.get_run(member(), manual.id).status == R.PENDING


def test_a_retry_delay_resumes_on_a_later_tick_without_any_in_memory_state(env, db_session):
    e = env(flaky(), PING)
    e.define(mkdef(retry=RetryPolicy(max_attempts=2, delay_seconds=60)))
    e.arm()
    e.w.clock.advance(hours=1)
    assert e.scheduler.tick().states == {"waiting_retry": 1}
    assert e.scheduler.tick().states == {"waiting_retry": 1}                      # not due: nothing new
    assert n(db_session, AgentRun) == 1
    e.w.clock.advance(seconds=60)
    fresh = Scheduler(db_session, e.w.wf, e.w.engine, e.w.runs.settings,           # a "restarted" scheduler
                      principal_for=lambda ws, uid: admin(uid, ws))
    assert fresh.tick().states == {"completed": 1} and e.runs()[0].status == R.SUCCEEDED


def test_one_ineligible_owner_does_not_stop_other_runs(env, db_session):
    owners = {"u1": admin(), "u2": member("u2")}
    e = env(PING, pf=lambda ws, uid: owners.get(uid))
    e.define(mkdef("onlead", intervals=(), extra=(EventTrigger("lead.created"),)))
    events = EventService(db_session, e.w.wf, e.w.runs.settings)
    events.emit(member("u2"), "lead.created", "e-u2")
    events.emit(member("u1"), "lead.created", "e-u1")
    del owners["u2"]                                                              # u2 left the workspace
    t = e.scheduler.tick()
    assert t.driven == 1 and t.errors == {"owner_unavailable": 1}
    done = {r.requested_by: r.status for r in e.runs()}
    assert done == {"u2": R.PENDING, "u1": R.SUCCEEDED}


def test_driving_is_bounded_per_tick(env, db_session):
    e = env(PING, PING, PING, workflow_tick_max_runs=2)
    e.define(mkdef("onlead", intervals=(), extra=(EventTrigger("lead.created"),)))
    events = EventService(db_session, e.w.wf, e.w.runs.settings)
    for i in range(3):
        events.emit(member(), "lead.created", f"e{i}")
    assert e.scheduler.tick().driven == 2
    assert e.scheduler.tick().driven == 1


def test_a_crashing_run_is_counted_by_a_fixed_code_and_does_not_stop_the_tick(env, db_session, caplog):
    e = env(PING)
    e.define(mkdef("onlead", intervals=(), extra=(EventTrigger("lead.created"),)))
    events = EventService(db_session, e.w.wf, e.w.runs.settings)
    events.emit(member(), "lead.created", "e1")
    events.emit(member(), "lead.created", "e2")
    real = e.w.engine.drive
    calls = {"n": 0}

    def flaky_drive(user, run_id):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom " + CANARY)
        return real(user, run_id)
    e.w.engine.drive = flaky_drive
    with caplog.at_level("DEBUG"):
        t = e.scheduler.tick()
    assert t.errors == {"unexpected": 1} and t.driven == 1 and CANARY not in caplog.text


# ================================================================== identity lookup, settings, content
def test_default_principal_comes_from_the_current_membership(db_session):
    from app.models.identity import Workspace
    pf = principal_from_membership(db_session)
    db_session.add(User(id="ux", email="ux@example.com", password_hash="x", is_active=True))
    db_session.commit()
    assert pf("w1", "ux") is None                                                 # no membership
    m = Membership(workspace_id="w1", user_id="ux", role=Role.ADMIN, is_active=True)
    db_session.add(m)
    db_session.commit()
    p = pf("w1", "ux")
    assert p.can("agent:manage") and p.can("agent:run") and p.agent is None and p.workspace_id == "w1"
    m.role = Role.VIEWER
    db_session.commit()
    assert not pf("w1", "ux").can("agent:run")                                    # a role change takes effect at once
    m.is_active = False
    db_session.commit()
    assert pf("w1", "ux") is None
    m.is_active = True
    db_session.commit()
    db_session.get(User, "ux").is_active = False
    db_session.commit()
    assert pf("w1", "ux") is None
    db_session.get(User, "ux").is_active = True
    db_session.get(Workspace, "w1").is_active = False
    db_session.commit()
    assert pf("w1", "ux") is None


def test_scheduler_settings_are_bounded():
    s = Settings(app_env="test", database_url="sqlite:///:memory:", _env_file=None)
    assert (s.workflow_max_schedules, s.workflow_tick_max_schedules, s.workflow_tick_max_runs) == (20, 20, 10)
    for name, bad in (("workflow_max_schedules", 0), ("workflow_max_schedules", 201), ("workflow_tick_max_schedules", 0),
                      ("workflow_tick_max_runs", 0), ("workflow_tick_max_runs", 101)):
        with pytest.raises(Exception):
            Settings(app_env="test", database_url="sqlite:///:memory:", _env_file=None, **{name: bad})


def test_no_instruction_text_reaches_schedule_events_or_rows(env, db_session):
    e = env(PING)
    e.define()
    e.arm()
    e.w.clock.advance(hours=1)
    e.scheduler.tick()
    blob = json.dumps([x.payload for x in db_session.scalars(select(SystemEvent))
                       if x.event_type.startswith("workflow.schedule")])
    rows = json.dumps([{c.name: str(getattr(r, c.name)) for c in r.__table__.columns}
                       for r in db_session.scalars(select(WorkflowScheduleRecord))])
    assert CANARY not in blob and CANARY not in rows
    assert len(sevents(db_session, "workflow.schedule_fired")) == 1
