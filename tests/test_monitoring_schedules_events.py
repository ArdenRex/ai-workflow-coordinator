"""Step 13.6: schedule and event health. Read-only, workspace-scoped, content-free."""
from datetime import timedelta

from sqlalchemy import func, select

from app.kernel.service import _now
from app.models.workflows import WorkflowEventRecord, WorkflowScheduleRecord
from tests.test_monitoring_health import get, uid
from tests.test_workspace_connectors import mkws, team  # noqa: F401


def sched(db, ws, *, enabled=True, due_in=3600, reason=None, skipped=0, key="daily"):
    s = WorkflowScheduleRecord(workspace_id=ws, armed_by=uid(db), workflow_key=key, interval_seconds=3600, enabled=enabled,
                               next_fire_at=_now() + timedelta(seconds=due_in), disabled_reason=reason, skipped_count=skipped)
    db.add(s)
    db.commit()
    return s


def event(db, ws, *, age=0, dispatched=True, truncated=False, ref="r"):
    e = WorkflowEventRecord(workspace_id=ws, emitted_by=uid(db), event_type="lead.created", event_ref=f"{ref}{age}{dispatched}{truncated}",
                            truncated=truncated, created_at=_now() - timedelta(seconds=age), dispatched_at=_now() if dispatched else None)
    db.add(e)
    db.commit()
    return e


def test_empty_workspace_is_all_zero_and_needs_no_attention(client, team):
    hs, ws = team
    j = get(client, hs["admin"], ws)
    assert j["schedules"] == {"total": 0, "enabled": 0, "disabled": 0, "auto_disabled": 0, "disabled_reasons": [], "overdue": 0,
                              "overdue_schedules": [], "skipped_slots_total": 0}
    assert j["events"] == {"received_in_window": 0, "dispatched_in_window": 0, "truncated_in_window": 0, "stuck_undispatched": 0}
    assert j["needs_attention"] is False


def test_healthy_schedules_and_manually_disabled_ones_need_no_attention(client, team, db_session):
    hs, ws = team
    sched(db_session, ws["id"], due_in=600)
    sched(db_session, ws["id"], enabled=False, reason=None, key="off")      # switched off by a person
    j = get(client, hs["admin"], ws)
    assert (j["schedules"]["total"], j["schedules"]["enabled"], j["schedules"]["disabled"], j["schedules"]["overdue"]) == (2, 1, 1, 0)
    assert j["schedules"]["auto_disabled"] == 0 and j["needs_attention"] is False


def test_overdue_needs_more_than_the_grace_period(client, team, db_session):
    hs, ws = team
    sched(db_session, ws["id"], due_in=-60)                                   # one minute late: within grace
    assert get(client, hs["admin"], ws)["schedules"]["overdue"] == 0
    sched(db_session, ws["id"], due_in=-3600, key="late")
    sched(db_session, ws["id"], due_in=-3600, enabled=False, key="off")     # disabled ones are never 'overdue'
    j = get(client, hs["admin"], ws)
    assert j["schedules"]["overdue"] == 1 and j["schedules"]["overdue_schedules"][0]["workflow_key"] == "late" and j["needs_attention"] is True


def test_auto_disabled_schedules_are_reported_with_the_fixed_reason(client, team, db_session):
    hs, ws = team
    sched(db_session, ws["id"], enabled=False, reason="definition_missing", skipped=3)
    sched(db_session, ws["id"], enabled=False, reason="definition_missing", key="b")
    j = get(client, hs["admin"], ws)
    assert j["schedules"]["auto_disabled"] == 2 and j["schedules"]["disabled_reasons"] == [{"name": "definition_missing", "count": 2}]
    assert j["schedules"]["skipped_slots_total"] == 3 and j["needs_attention"] is True


def test_event_counts_are_windowed_and_stuck_is_a_snapshot(client, team, db_session):
    hs, ws = team
    event(db_session, ws["id"], age=100)
    event(db_session, ws["id"], age=200, truncated=True)
    event(db_session, ws["id"], age=100, dispatched=False)                    # recent and undispatched: within grace
    event(db_session, ws["id"], age=3 * 86400)                                # outside a one-day window
    j = get(client, hs["admin"], ws, 86400)["events"]
    assert j == {"received_in_window": 3, "dispatched_in_window": 2, "truncated_in_window": 1, "stuck_undispatched": 0}
    assert get(client, hs["admin"], ws, 86400)["needs_attention"] is False
    event(db_session, ws["id"], age=3600, dispatched=False)
    j = get(client, hs["admin"], ws, 86400)
    assert j["events"]["stuck_undispatched"] == 1 and j["needs_attention"] is True
    event(db_session, ws["id"], age=5 * 86400, dispatched=False)              # stuck beyond the window still counts: it is a snapshot
    assert get(client, hs["admin"], ws, 3600)["events"]["stuck_undispatched"] == 2


def test_other_workspaces_never_leak_into_schedules_or_events(client, team, db_session):
    hs, ws = team
    other = mkws(client, hs["outsider"])
    sched(db_session, other["id"], due_in=-9999, key="theirs")
    sched(db_session, other["id"], enabled=False, reason="theirs_reason", skipped=9)
    event(db_session, other["id"], age=9999, dispatched=False, truncated=True)
    j = get(client, hs["admin"], ws)
    assert j["schedules"]["total"] == 0 and j["schedules"]["overdue"] == 0 and j["schedules"]["skipped_slots_total"] == 0
    assert j["events"]["received_in_window"] == 0 and j["events"]["stuck_undispatched"] == 0 and j["needs_attention"] is False
    assert "theirs" not in client.get(f"/workspaces/{ws['id']}/monitoring/health", headers=hs["admin"]).text


def test_content_free_and_read_only(client, team, db_session):
    hs, ws = team
    sched(db_session, ws["id"], due_in=-9999)
    event(db_session, ws["id"], age=9999, dispatched=False)
    text = client.get(f"/workspaces/{ws['id']}/monitoring/health", headers=hs["admin"]).text
    assert "lead.created" not in text and "event_ref" not in text and "armed_by" not in text
    n = lambda m: db_session.scalar(select(func.count()).select_from(m))   # noqa: E731
    before = (n(WorkflowScheduleRecord), n(WorkflowEventRecord))
    snap = db_session.scalar(select(WorkflowScheduleRecord.next_fire_at))
    get(client, hs["admin"], ws)
    db_session.expire_all()
    assert (n(WorkflowScheduleRecord), n(WorkflowEventRecord)) == before and db_session.scalar(select(WorkflowScheduleRecord.next_fire_at)) == snap
