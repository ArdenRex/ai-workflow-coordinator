"""Workflow scheduling: armed interval triggers and a bounded, restart-safe tick. Adds no authority.

    arm(admin, workflow, interval)  -> a schedule row; first fire is one interval from now
    tick()                          -> 1. fire every due schedule (bounded)   2. drive scheduled/event runs (bounded)

Safety properties
- Arming needs `agent:manage` (admin+) and the workflow's newest ACTIVE version must declare that exact schedule
  trigger. Runs a schedule starts belong to the user who armed it and are created and driven AS that user, with their
  permissions re-read from the database at every fire and drive. If they lost the role, left the workspace, or were
  deactivated, the schedule disables itself (`owner_unavailable`) instead of running with stale authority. Agents
  can never arm schedules.
- Slots are deterministic: the run's trigger_ref is `<schedule id>:<slot epoch seconds>`, enforced unique in the
  database. The run is created first (idempotent), then the schedule advances with a compare-and-swap on
  `next_fire_at`, so a crash between the two re-fires the same slot into the same run, and two concurrent ticks cannot
  start a slot twice. All state is in the database: a restart resumes exactly where it stopped.
- No backfill and no pile-up: after downtime, ONE run fires for the due slot and the schedule jumps to the next
  boundary after now (missed slots are counted in the audit event). A slot is skipped, not queued, while the previous
  run from the same schedule is still pending or running.
- Fail-closed: a schedule whose trigger was removed, whose workflow is archived or whose stored definition fails its
  integrity check disables itself with a fixed reason. A full active-run limit skips the slot but keeps the schedule.
- Bounded work per tick: at most WORKFLOW_TICK_MAX_SCHEDULES schedules fired and WORKFLOW_TICK_MAX_RUNS runs driven.
  One failing run or schedule never stops the others, and errors are counted by fixed code, never with content.
- The tick drives only runs started by a schedule or an event (manual runs are driven by their creator). Driving is
  the ordinary engine: every step is an agent run under the owner's permissions, with approvals, policy and audit.
  Runs whose owner is no longer eligible are left untouched and counted (an admin can cancel them).
- Content-free: audit payloads (`workflow.schedule_*`) carry ids, slots, counts and fixed codes only.
`tick` does not loop or sleep; something calls it periodically (an HTTP trigger in 9.6, a cron, or a worker later).
"""
import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agents.errors import RunError
from app.config import Settings
from app.identity.roles import permissions_for
from app.kernel.audit import record_event
from app.kernel.permissions import Principal
from app.models.enums import WorkflowRunStatus as R
from app.models.identity import Membership, User, Workspace
from app.models.workflows import WorkflowRunRecord, WorkflowScheduleRecord
from app.workflows.definition import ScheduleTrigger
from app.workflows.engine import WorkflowEngine
from app.workflows.errors import (InvalidWorkflowError, InvalidWorkflowRequestError, WorkflowConflictError,
                                  WorkflowForbiddenError, WorkflowLimitError, WorkflowNotFoundError,
                                  WorkflowRequestError, WorkflowStateError)
from app.workflows.store import WorkflowService

logger = logging.getLogger(__name__)
PrincipalFor = Callable[[str, str], Optional[Principal]]


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    return dt if dt is None or dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def principal_from_membership(db: Session) -> PrincipalFor:
    """Default identity lookup: the user's CURRENT role in the workspace, or None if they are not an active member of
    an active workspace (or are deactivated)."""
    def lookup(workspace_id: str, user_id: str) -> Optional[Principal]:
        row = db.execute(select(Membership).join(Workspace, Workspace.id == Membership.workspace_id)
                         .join(User, User.id == Membership.user_id)
                         .where(Membership.workspace_id == workspace_id, Membership.user_id == user_id,
                                Membership.is_active.is_(True), Workspace.is_active.is_(True),
                                User.is_active.is_(True))).scalars().first()
        if row is None:
            return None
        return Principal(user_id=user_id, workspace_id=workspace_id, permissions=permissions_for(row.role))
    return lookup


@dataclass
class TickResult:
    fired: int = 0
    skipped: int = 0              # slots not started (previous run still live, or the run limit was full)
    disabled: int = 0
    driven: int = 0
    states: Dict[str, int] = field(default_factory=dict)       # drive outcome -> count
    errors: Dict[str, int] = field(default_factory=dict)       # fixed code -> count


# ====================================================================== arming
class ScheduleService:
    def __init__(self, db: Session, workflows: WorkflowService, settings: Settings):
        self.db, self.wf, self.settings = db, workflows, settings

    def arm(self, principal: Principal, workflow_key: str, interval_seconds: int) -> WorkflowScheduleRecord:
        self._require_manager(principal)
        trigger = ScheduleTrigger(interval_seconds)                     # validates the interval (InvalidWorkflowError)
        rec = self.wf._startable(principal, workflow_key, None)         # newest ACTIVE version, or NotFound
        if trigger not in self.wf.definition_of(rec).triggers:
            raise InvalidWorkflowRequestError("The workflow does not declare that schedule trigger")
        now = self.wf.now()
        existing = self._find(principal.workspace_id, workflow_key, interval_seconds)
        if existing is not None:
            if existing.enabled:
                return existing
            self.db.execute(update(WorkflowScheduleRecord).where(
                WorkflowScheduleRecord.id == existing.id, WorkflowScheduleRecord.workspace_id == existing.workspace_id,
                WorkflowScheduleRecord.enabled.is_(False)).values(
                enabled=True, armed_by=principal.user_id, disabled_reason=None, updated_at=now,
                next_fire_at=now + timedelta(seconds=interval_seconds)))
            self.db.refresh(existing)
            self._event(existing, "workflow.schedule_armed", principal.user_id)
            self.db.commit()
            return existing
        if self._count(principal.workspace_id) >= self.settings.workflow_max_schedules:
            raise WorkflowLimitError("Schedule limit reached for this workspace")
        sched = WorkflowScheduleRecord(workspace_id=principal.workspace_id, armed_by=principal.user_id,
                                       workflow_key=workflow_key, interval_seconds=interval_seconds, enabled=True,
                                       next_fire_at=now + timedelta(seconds=interval_seconds), fired_count=0,
                                       skipped_count=0)
        self.db.add(sched)
        try:
            self.db.flush()
            self._event(sched, "workflow.schedule_armed", principal.user_id)
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            raise WorkflowConflictError("Another change to this schedule was saved first; retry") from None
        return sched

    def disarm(self, principal: Principal, workflow_key: str, interval_seconds: int) -> WorkflowScheduleRecord:
        self._require_manager(principal)
        sched = self._find(principal.workspace_id, workflow_key, interval_seconds)
        if sched is None:
            raise WorkflowNotFoundError("Schedule not found")
        if not sched.enabled:
            return sched                                                 # idempotent
        self._disable(sched, "disarmed", principal.user_id)
        self.db.refresh(sched)
        return sched

    def list_schedules(self, principal: Principal) -> List[WorkflowScheduleRecord]:
        if principal.agent is not None or not (principal.can("agent:run") or principal.can("agent:manage")):
            raise WorkflowForbiddenError("Not allowed to read schedules")
        return list(self.db.scalars(select(WorkflowScheduleRecord).where(
            WorkflowScheduleRecord.workspace_id == principal.workspace_id)
            .order_by(WorkflowScheduleRecord.workflow_key, WorkflowScheduleRecord.interval_seconds)))

    # -------------------------------------------------------------- internals (also used by the Scheduler)
    def _require_manager(self, p: Principal) -> None:
        if p.agent is not None or not p.can("agent:manage"):
            raise WorkflowForbiddenError("Not allowed to manage schedules")

    def _find(self, workspace_id: str, key: str, interval: int) -> Optional[WorkflowScheduleRecord]:
        return self.db.scalar(select(WorkflowScheduleRecord).where(
            WorkflowScheduleRecord.workspace_id == workspace_id, WorkflowScheduleRecord.workflow_key == key,
            WorkflowScheduleRecord.interval_seconds == interval))

    def _count(self, workspace_id: str) -> int:
        return self.db.scalar(select(func.count()).select_from(WorkflowScheduleRecord).where(
            WorkflowScheduleRecord.workspace_id == workspace_id)) or 0

    def _event(self, s: WorkflowScheduleRecord, event_type: str, actor: str, **payload) -> None:
        record_event(self.db, workspace_id=s.workspace_id, event_type=event_type, actor=actor,
                     payload={"schedule_id": s.id, "workflow": s.workflow_key, "interval_seconds": s.interval_seconds,
                              **payload})

    def _disable(self, s: WorkflowScheduleRecord, reason: str, actor: str) -> bool:
        res = self.db.execute(update(WorkflowScheduleRecord).where(
            WorkflowScheduleRecord.id == s.id, WorkflowScheduleRecord.workspace_id == s.workspace_id,
            WorkflowScheduleRecord.enabled.is_(True)).values(enabled=False, disabled_reason=reason,
                                                             updated_at=self.wf.now()))
        if res.rowcount != 1:
            self.db.rollback()
            return False
        self.db.refresh(s)
        self._event(s, "workflow.schedule_disabled", actor, reason=reason)
        self.db.commit()
        return True


# ====================================================================== the tick
class Scheduler:
    def __init__(self, db: Session, workflows: WorkflowService, engine: WorkflowEngine, settings: Settings, *,
                 principal_for: Optional[PrincipalFor] = None):
        self.db, self.wf, self.engine, self.settings = db, workflows, engine, settings
        self.schedules = ScheduleService(db, workflows, settings)
        self.principal_for = principal_for or principal_from_membership(db)

    def tick(self, *, drive: bool = True, workspace_id: Optional[str] = None) -> TickResult:
        """`workspace_id` limits the tick to one workspace (the HTTP trigger always sets it, so one tenant can never
        fire or drive another's schedules or runs). None means every workspace (an operator cron)."""
        out = TickResult()
        self._fire_due(out, workspace_id)
        if drive:
            self._drive_runs(out, workspace_id)
        return out

    # -------------------------------------------------------------- phase 1: fire
    def _fire_due(self, out: TickResult, workspace_id: Optional[str] = None) -> None:
        now = self.wf.now()
        q = select(WorkflowScheduleRecord).where(
            WorkflowScheduleRecord.enabled.is_(True), WorkflowScheduleRecord.next_fire_at <= now)
        if workspace_id is not None:
            q = q.where(WorkflowScheduleRecord.workspace_id == workspace_id)
        due = list(self.db.scalars(q
            .order_by(WorkflowScheduleRecord.next_fire_at, WorkflowScheduleRecord.id)
            .limit(self.settings.workflow_tick_max_schedules)))
        for s in due:
            try:
                self._fire(s, now, out)
            except Exception as exc:                                     # one bad schedule must not stop the rest
                self.db.rollback()
                code = getattr(exc, "code", None) or "unexpected"
                out.errors[code] = out.errors.get(code, 0) + 1
                logger.warning("Scheduler could not fire a schedule: %s", exc.__class__.__name__)

    def _fire(self, s: WorkflowScheduleRecord, now: datetime, out: TickResult) -> None:
        slot, seen = _aware(s.next_fire_at), s.next_fire_at
        interval = timedelta(seconds=s.interval_seconds)
        owner = self.principal_for(s.workspace_id, s.armed_by)
        if owner is None or not (owner.can("agent:manage") and owner.can("agent:run")):
            if self.schedules._disable(s, "owner_unavailable", s.armed_by):
                out.disabled += 1
            return
        missed = int((now - slot) / interval)
        run_id: Optional[str] = None
        code: Optional[str] = None
        ref = f"{s.id}:{int(slot.timestamp())}"
        recovered = self.wf._run_by_ref(s.workspace_id, s.workflow_key, "schedule", ref)
        if recovered is not None:                                         # this slot already started (an interrupted tick)
            run_id = recovered.id
        elif self._live_run_exists(s):
            code = "overlap"
        else:
            try:
                run = self.wf.create_run(owner, s.workflow_key, trigger=ScheduleTrigger(s.interval_seconds),
                                         trigger_ref=ref)
                run_id = run.id
            except WorkflowLimitError:
                code = "run_limit"
            except InvalidWorkflowRequestError:
                self._disable_for(s, "trigger_removed", out)
                return
            except WorkflowNotFoundError:
                self._disable_for(s, "workflow_unavailable", out)
                return
            except WorkflowStateError:
                self._disable_for(s, "definition_invalid", out)
                return
        nxt = slot + interval * (missed + 1)                              # next boundary after now; never backfills
        res = self.db.execute(update(WorkflowScheduleRecord).where(
            WorkflowScheduleRecord.id == s.id, WorkflowScheduleRecord.workspace_id == s.workspace_id,
            WorkflowScheduleRecord.enabled.is_(True), WorkflowScheduleRecord.next_fire_at == seen).values(
            next_fire_at=nxt, last_fired_at=now if run_id else s.last_fired_at, updated_at=now,
            fired_count=WorkflowScheduleRecord.fired_count + (1 if run_id else 0),
            skipped_count=WorkflowScheduleRecord.skipped_count + (0 if run_id else 1)))
        if res.rowcount != 1:                                             # another tick advanced it first
            self.db.rollback()
            return
        self.db.refresh(s)
        if run_id:
            out.fired += 1
            self.schedules._event(s, "workflow.schedule_fired", s.armed_by, run_id=run_id, slot=int(slot.timestamp()),
                                  missed_slots=missed)
        else:
            out.skipped += 1
            self.schedules._event(s, "workflow.schedule_skipped", s.armed_by, reason=code, missed_slots=missed)
        self.db.commit()

    def _live_run_exists(self, s: WorkflowScheduleRecord) -> bool:
        return (self.db.scalar(select(func.count()).select_from(WorkflowRunRecord).where(
            WorkflowRunRecord.workspace_id == s.workspace_id, WorkflowRunRecord.workflow_key == s.workflow_key,
            WorkflowRunRecord.trigger_type == "schedule", WorkflowRunRecord.trigger_ref.like(f"{s.id}:%"),
            WorkflowRunRecord.status.in_((R.PENDING, R.RUNNING)))) or 0) > 0

    def _disable_for(self, s: WorkflowScheduleRecord, reason: str, out: TickResult) -> None:
        if self.schedules._disable(s, reason, s.armed_by):
            out.disabled += 1

    # -------------------------------------------------------------- phase 2: drive
    def _drive_runs(self, out: TickResult, workspace_id: Optional[str] = None) -> None:
        q = select(WorkflowRunRecord).where(
            WorkflowRunRecord.trigger_type.in_(("schedule", "event")),
            WorkflowRunRecord.status.in_((R.PENDING, R.RUNNING)))
        if workspace_id is not None:
            q = q.where(WorkflowRunRecord.workspace_id == workspace_id)
        runs = list(self.db.scalars(q
            .order_by(WorkflowRunRecord.created_at, WorkflowRunRecord.id)
            .limit(self.settings.workflow_tick_max_runs)))
        for run in runs:
            owner = self.principal_for(run.workspace_id, run.requested_by)
            if owner is None or not owner.can("agent:run"):
                out.errors["owner_unavailable"] = out.errors.get("owner_unavailable", 0) + 1
                continue
            try:
                result = self.engine.drive(owner, run.id)
                out.driven += 1
                out.states[result.state] = out.states.get(result.state, 0) + 1
            except (WorkflowRequestError, InvalidWorkflowError, RunError) as exc:
                self.db.rollback()
                out.errors[exc.code] = out.errors.get(exc.code, 0) + 1
            except Exception as exc:                                     # one bad run must not stop the rest
                self.db.rollback()
                out.errors["unexpected"] = out.errors.get("unexpected", 0) + 1
                logger.warning("Scheduler could not drive a run: %s", exc.__class__.__name__)
