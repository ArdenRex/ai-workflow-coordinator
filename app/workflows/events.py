"""Workflow events: internal event intake, trigger matching and idempotent starts. Executes NOTHING.

    emit(principal, event_type, event_ref)
        -> records the event (deduped on workspace + type + ref)
        -> finds every workflow whose NEWEST ACTIVE version declares an event trigger of that type
        -> creates one PENDING run per match, requested by the emitter, with trigger_ref = the event's id
        -> records counts and marks the event dispatched

Safety properties
- No new authority: a run started by an event is an ordinary workflow run owned by the user who emitted the event,
  so that user needs `agent:run`, and only they can drive it (viewers, agents and outsiders cannot emit). An agent can
  never start workflows by emitting events, which would let an agent widen its own reach.
- Content-free: an event carries a type, an emitter-chosen reference and counts. There is no payload: event data would
  be untrusted input to prompts, and carrying it is a separate later decision. Audit payloads hold ids and counts only
  (never the reference, which may embed customer identifiers).
- Idempotent: the same (type, ref) is one event. Redelivery of a dispatched event returns the recorded outcome and does
  not match again, so a workflow defined later is not retro-started. An event whose dispatch was interrupted is
  finished on redelivery; run creation dedupes on (workflow, trigger_ref = event id), so nothing starts twice. A
  redelivery from a different user is a conflict.
- Bounded: at most `WORKFLOW_MAX_EVENT_FANOUT` runs per event (alphabetical by workflow key; `truncated` is recorded),
  the per-workspace active-run limit still applies (a skipped workflow is counted, not lost silently), and the type and
  reference formats are strict.
- Fail-closed per workflow: a workflow whose stored definition fails its integrity check, or that cannot start
  (limit, archived mid-flight), is skipped and counted; the others still start.
- Matching uses the same rule as a manual start: the newest ACTIVE version of each workflow, and the trigger must be
  declared by that version.
Events only create PENDING runs. Driving them (and time-based triggers) is the scheduler's job in 9.5.
"""
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, List, Optional, Tuple

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings
from app.kernel.audit import record_event
from app.kernel.permissions import Principal
from app.models.enums import WorkflowStatus as W
from app.models.workflows import WorkflowEventRecord, WorkflowRecord, WorkflowRunRecord
from app.workflows.definition import EVENT_TYPE_RE, EventTrigger
from app.workflows.errors import (InvalidWorkflowRequestError, WorkflowConflictError, WorkflowForbiddenError,
                                  WorkflowNotFoundError, WorkflowRequestError)
from app.workflows.store import WorkflowService

_REF_RE = re.compile(r"^[A-Za-z0-9_.:\-]{1,128}$")


@dataclass(frozen=True)
class EmitResult:
    event: WorkflowEventRecord
    run_ids: Tuple[str, ...]
    duplicate: bool = False        # True when this exact event had already been received


class EventService:
    def __init__(self, db: Session, workflows: WorkflowService, settings: Settings):
        self.db, self.wf, self.settings = db, workflows, settings

    # ------------------------------------------------------------------ intake
    def emit(self, principal: Principal, event_type: str, event_ref: str) -> EmitResult:
        if principal.agent is not None or not principal.can("agent:run"):
            raise WorkflowForbiddenError("Not allowed to emit workflow events")
        if not isinstance(event_type, str) or not EVENT_TYPE_RE.match(event_type):
            raise InvalidWorkflowRequestError("event_type must be dotted lowercase slugs, e.g. lead.created")
        if not isinstance(event_ref, str) or not _REF_RE.match(event_ref):
            raise InvalidWorkflowRequestError("event_ref must be 1-128 characters: letters, digits, _ . : -")
        existing = self._find(principal.workspace_id, event_type, event_ref)
        duplicate = existing is not None
        if existing is None:
            event = WorkflowEventRecord(workspace_id=principal.workspace_id, emitted_by=principal.user_id,
                                        event_type=event_type, event_ref=event_ref)
            self.db.add(event)
            try:
                self.db.flush()
                record_event(self.db, workspace_id=event.workspace_id, event_type="workflow.event_received",
                             actor=principal.user_id, payload={"event_id": event.id, "event_type": event_type})
                self.db.commit()
            except IntegrityError:                                    # a concurrent delivery of the same event won
                self.db.rollback()
                existing = self._find(principal.workspace_id, event_type, event_ref)
                if existing is None:
                    raise
                duplicate = True
        if existing is not None:
            event = existing
            if event.emitted_by != principal.user_id:
                raise WorkflowConflictError("That event was already received from a different user")
        if event.dispatched_at is not None:
            return EmitResult(event, self._run_ids(event), duplicate=True)
        return self._finish(principal, event, duplicate)

    # ------------------------------------------------------------------ read
    def get_event(self, principal: Principal, event_id: str) -> WorkflowEventRecord:
        event = self.db.scalar(select(WorkflowEventRecord).where(WorkflowEventRecord.id == event_id,
                                                                 WorkflowEventRecord.workspace_id == principal.workspace_id))
        if event is None or principal.agent is not None or not (
                event.emitted_by == principal.user_id or principal.can("agent:manage")):
            raise WorkflowNotFoundError("Event not found")
        return event

    def list_events(self, principal: Principal, *, limit: int = 50) -> List[WorkflowEventRecord]:
        limit = max(1, min(int(limit), 200))
        if principal.agent is not None:
            return []
        q = select(WorkflowEventRecord).where(WorkflowEventRecord.workspace_id == principal.workspace_id)
        if not principal.can("agent:manage"):
            q = q.where(WorkflowEventRecord.emitted_by == principal.user_id)
        return list(self.db.scalars(q.order_by(WorkflowEventRecord.created_at.desc(), WorkflowEventRecord.id).limit(limit)))

    def run_ids(self, principal: Principal, event_id: str) -> Tuple[str, ...]:
        return self._run_ids(self.get_event(principal, event_id))

    # ------------------------------------------------------------------ internals
    def _find(self, workspace_id: str, event_type: str, ref: str) -> Optional[WorkflowEventRecord]:
        return self.db.scalar(select(WorkflowEventRecord).where(
            WorkflowEventRecord.workspace_id == workspace_id, WorkflowEventRecord.event_type == event_type,
            WorkflowEventRecord.event_ref == ref))

    def _run_ids(self, event: WorkflowEventRecord) -> Tuple[str, ...]:
        return tuple(self.db.scalars(select(WorkflowRunRecord.id).where(
            WorkflowRunRecord.workspace_id == event.workspace_id, WorkflowRunRecord.trigger_type == "event",
            WorkflowRunRecord.trigger_ref == event.id).order_by(WorkflowRunRecord.workflow_key)))

    def _listeners(self, principal: Principal, event_type: str) -> Tuple[List[WorkflowRecord], int]:
        """Newest ACTIVE version of each workflow that declares this event type. Returns (matches, skipped_invalid)."""
        newest = (select(WorkflowRecord.workflow_key.label("k"), func.max(WorkflowRecord.version).label("v"))
                  .where(WorkflowRecord.workspace_id == principal.workspace_id, WorkflowRecord.status == W.ACTIVE)
                  .group_by(WorkflowRecord.workflow_key).subquery())
        rows = self.db.scalars(select(WorkflowRecord).join(
            newest, (WorkflowRecord.workflow_key == newest.c.k) & (WorkflowRecord.version == newest.c.v))
            .where(WorkflowRecord.workspace_id == principal.workspace_id, WorkflowRecord.status == W.ACTIVE)
            .order_by(WorkflowRecord.workflow_key))
        matches: List[WorkflowRecord] = []
        invalid = 0
        for rec in rows:
            try:
                defn = self.wf.definition_of(rec)                      # integrity-checked
            except WorkflowRequestError:
                invalid += 1
                continue
            if EventTrigger(event_type) in defn.triggers:
                matches.append(rec)
        return matches, invalid

    def _finish(self, principal: Principal, event: WorkflowEventRecord, duplicate: bool) -> EmitResult:
        matches, invalid = self._listeners(principal, event.event_type)
        cap = self.settings.workflow_max_event_fanout
        started, skipped = 0, invalid
        reasons: dict = {}
        for rec in matches[:cap]:
            try:
                self.wf.create_run(principal, rec.workflow_key, version=rec.version,
                                   trigger=EventTrigger(event.event_type), trigger_ref=event.id)
                started += 1
            except WorkflowRequestError as exc:
                skipped += 1
                reasons[exc.code] = reasons.get(exc.code, 0) + 1
        truncated = len(matches) > cap
        skipped += max(0, len(matches) - cap)
        now = self.wf.now()
        res = self.db.execute(update(WorkflowEventRecord).where(
            WorkflowEventRecord.id == event.id, WorkflowEventRecord.workspace_id == event.workspace_id,
            WorkflowEventRecord.dispatched_at.is_(None)).values(
            matched_count=len(matches), started_count=started, skipped_count=skipped, truncated=truncated,
            dispatched_at=now, updated_at=now))
        if res.rowcount == 1:
            self.db.refresh(event)
            record_event(self.db, workspace_id=event.workspace_id, event_type="workflow.event_dispatched",
                         actor=principal.user_id,
                         payload={"event_id": event.id, "event_type": event.event_type, "matched": len(matches),
                                  "started": started, "skipped": skipped, "truncated": truncated,
                                  "invalid_definitions": invalid, "skip_codes": reasons})
            self.db.commit()
        else:                                                           # another delivery finished it first
            self.db.rollback()
            self.db.refresh(event)
        return EmitResult(event, self._run_ids(event), duplicate=duplicate)
