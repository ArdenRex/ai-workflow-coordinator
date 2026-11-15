"""Workflow store: persistence, lifecycle state machines, retry bookkeeping and content-free audit. Executes NOTHING.

    definition:  ACTIVE --archive--> ARCHIVED         (a version's text is never edited: a change is a new version)
    run:         PENDING --start--> RUNNING --complete--> SUCCEEDED | FAILED        cancel: PENDING/RUNNING -> CANCELLED
    step:        PENDING -> RUNNING <-> WAITING_APPROVAL -> SUCCEEDED | FAILED | CANCELLED
                 RUNNING --fail_attempt--> PENDING (+ next_attempt_at) while attempts remain, else FAILED
                 PENDING -> SKIPPED | CANCELLED

Design rules (same family as agent runs and plans)
- Every status change is a compare-and-swap UPDATE restricted to the workspace and the legal source states.
- Dependency order is enforced HERE: a step starts only when the run is RUNNING, not cancel-requested, every
  dependency is SUCCEEDED in the database, and any retry delay has elapsed. A failed/skipped/cancelled dependency
  never unblocks anything.
- Retries are bounded by the definition's policy and stored on the step (attempts, max_attempts); a retry is a
  PENDING step with `next_attempt_at`, so a restarted process resumes from the database alone.
- Runs bind to the exact definition version and digest they started from; the stored definition is re-verified
  against its digest each time it is loaded.
- Content-free: runs and steps hold ids, states, counts and fixed codes; results are redacted and capped; audit
  payloads (`workflow.*`) carry ids, digests, states and codes only, never instructions.
- Authority: defining/archiving needs `agent:manage` (admin+); starting a run needs `agent:run`. Definitions are
  readable by anyone who may run or manage. A run belongs to the user who created it: they see and drive it;
  `agent:manage` sees every run and may cancel, but only the owner drives it. Agent principals can do nothing here.
  Invisible and missing records are indistinguishable (WorkflowNotFoundError).
- A trigger must be one the definition declares, and a non-manual trigger needs a `trigger_ref` (event id or
  schedule slot): the same ref for the same workflow can start at most one run, so redelivery cannot double-start.
"""
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agents.registry import AgentRegistry
from app.config import Settings
from app.kernel.audit import record_event, redact
from app.kernel.permissions import Principal
from app.models.agents import AgentRun
from app.models.enums import StepState as S
from app.models.enums import WorkflowRunStatus as R
from app.models.enums import WorkflowStatus as W
from app.models.workflows import WorkflowRecord, WorkflowRunRecord, WorkflowStepRecord
from app.orchestration.plan import is_finished, outcome, ready_steps, steps_to_skip
from app.workflows.definition import (EventTrigger, ManualTrigger, ScheduleTrigger, Trigger, WorkflowDefinition,
                                      from_dict, validate_for_workspace)
from app.workflows.errors import (InvalidWorkflowRequestError, WorkflowCancelledError, WorkflowConflictError,
                                  WorkflowForbiddenError, WorkflowLimitError, WorkflowNotFoundError,
                                  WorkflowStateError)

MAX_RESULT_BYTES = 16_000
_CODE_RE = re.compile(r"^[a-z0-9_.]{1,64}$")
_REF_RE = re.compile(r"^[A-Za-z0-9_.:\-]{1,128}$")
_ACTIVE = (S.RUNNING, S.WAITING_APPROVAL)
_FINISH = frozenset({S.SUCCEEDED, S.FAILED, S.CANCELLED})
_LIVE_RUN = (R.PENDING, R.RUNNING)


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    """SQLite returns naive datetimes; everything stored here is UTC."""
    return dt if dt is None or dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _trigger_parts(t: Trigger):
    if isinstance(t, ManualTrigger):
        return "manual"
    return "event" if isinstance(t, EventTrigger) else "schedule"


class WorkflowService:
    def __init__(self, db: Session, agents: AgentRegistry, settings: Settings, *,
                 clock: Optional[Callable[[], datetime]] = None):
        self.db, self.agents, self.settings = db, agents, settings
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    # ================================================================ definitions
    def define(self, principal: Principal, definition: WorkflowDefinition) -> WorkflowRecord:
        """Stores one version. A new key must be version 1; an existing key must be latest+1. Re-sending the latest
        version unchanged is a no-op."""
        self._require_manager(principal)
        validate_for_workspace(definition, self.agents, max_steps=self.settings.workflow_max_steps)
        digest = definition.digest()
        latest = self._latest(principal.workspace_id, definition.id)
        if latest is not None and latest.version == definition.version:
            if latest.definition_digest == digest:
                return latest
            raise WorkflowConflictError("This version already exists with different content; use the next version")
        expected = 1 if latest is None else latest.version + 1
        if definition.version != expected:
            raise WorkflowConflictError(f"Next version of this workflow must be {expected}")
        if latest is None and self._count_keys(principal.workspace_id) >= self.settings.workflow_max_definitions:
            raise WorkflowLimitError("Workflow limit reached for this workspace")
        rec = WorkflowRecord(workspace_id=principal.workspace_id, created_by=principal.user_id,
                             workflow_key=definition.id, version=definition.version, status=W.ACTIVE,
                             name=definition.name, definition=definition.to_dict(), definition_digest=digest)
        self.db.add(rec)
        try:
            self.db.flush()
            self._def_event(rec, "workflow.defined", principal.user_id, steps=len(definition.steps),
                            triggers=len(definition.triggers))
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            raise WorkflowConflictError("Another change to this workflow was saved first; retry") from None
        return rec

    def get_definition(self, principal: Principal, key: str, version: Optional[int] = None) -> WorkflowRecord:
        self._require_reader(principal)
        q = select(WorkflowRecord).where(WorkflowRecord.workspace_id == principal.workspace_id,
                                         WorkflowRecord.workflow_key == key)
        if version is not None:
            q = q.where(WorkflowRecord.version == version)
        rec = self.db.scalar(q.order_by(WorkflowRecord.version.desc()).limit(1))
        if rec is None:
            raise WorkflowNotFoundError("Workflow not found")
        return rec

    def list_definitions(self, principal: Principal) -> List[WorkflowRecord]:
        """The latest version of every workflow in the workspace (bounded by the definitions ceiling)."""
        self._require_reader(principal)
        rows = self.db.scalars(select(WorkflowRecord).where(WorkflowRecord.workspace_id == principal.workspace_id)
                               .order_by(WorkflowRecord.workflow_key, WorkflowRecord.version.desc()))
        out: Dict[str, WorkflowRecord] = {}
        for r in rows:
            out.setdefault(r.workflow_key, r)
        return list(out.values())

    def versions(self, principal: Principal, key: str) -> List[WorkflowRecord]:
        self._require_reader(principal)
        rows = list(self.db.scalars(select(WorkflowRecord).where(
            WorkflowRecord.workspace_id == principal.workspace_id, WorkflowRecord.workflow_key == key)
            .order_by(WorkflowRecord.version)))
        if not rows:
            raise WorkflowNotFoundError("Workflow not found")
        return rows

    def archive(self, principal: Principal, key: str, version: int) -> WorkflowRecord:
        self._require_manager(principal)
        rec = self.get_definition(principal, key, version)
        if rec.status == W.ARCHIVED:
            return rec                                                           # idempotent
        res = self.db.execute(update(WorkflowRecord).where(
            WorkflowRecord.id == rec.id, WorkflowRecord.workspace_id == rec.workspace_id,
            WorkflowRecord.status == W.ACTIVE).values(status=W.ARCHIVED, archived_at=self._clock(),
                                                      updated_at=self._clock()))
        if res.rowcount != 1:
            self.db.rollback()
        else:
            self.db.refresh(rec)
            self._def_event(rec, "workflow.archived", principal.user_id)
            self.db.commit()
        self.db.refresh(rec)
        return rec

    def definition_of(self, rec: WorkflowRecord) -> WorkflowDefinition:
        """Rebuilds the definition and re-checks it against its stored digest (fails closed on tampering)."""
        try:
            defn = from_dict(rec.definition)
        except Exception:
            raise WorkflowStateError("The stored workflow definition is invalid") from None
        if defn.digest() != rec.definition_digest or defn.id != rec.workflow_key or defn.version != rec.version:
            raise WorkflowStateError("The stored workflow definition failed its integrity check")
        return defn

    def now(self) -> datetime:
        return self._clock()

    def definition_for_run(self, principal: Principal, run_id: str) -> WorkflowDefinition:
        """The exact definition a run was started from (driver only), re-verified against its digest."""
        return self.definition_of(self._definition_row(self._load_driven(principal, run_id)))

    # ================================================================ runs: create / read
    def create_run(self, principal: Principal, key: str, *, version: Optional[int] = None,
                   trigger: Optional[Trigger] = None, trigger_ref: Optional[str] = None,
                   idempotency_key: Optional[str] = None) -> WorkflowRunRecord:
        self._require_runner(principal)
        trigger = trigger or ManualTrigger()
        kind = _trigger_parts(trigger)
        if kind == "manual" and trigger_ref is not None:
            raise InvalidWorkflowRequestError("A manual start takes no trigger_ref")
        if kind != "manual" and (not isinstance(trigger_ref, str) or not _REF_RE.match(trigger_ref)):
            raise InvalidWorkflowRequestError("trigger_ref must be 1-128 characters: letters, digits, _ . : -")
        if idempotency_key is not None and not (isinstance(idempotency_key, str) and 1 <= len(idempotency_key) <= 128):
            raise InvalidWorkflowRequestError("idempotency_key must be 1-128 characters")
        rec = self._startable(principal, key, version)
        defn = self.definition_of(rec)
        if trigger not in defn.triggers:
            raise InvalidWorkflowRequestError("This workflow does not declare that trigger")
        for existing in (self._run_by_idem(principal.workspace_id, idempotency_key) if idempotency_key else None,
                         self._run_by_ref(principal.workspace_id, key, kind, trigger_ref) if trigger_ref else None):
            if existing is not None:
                return self._replay(existing, principal, key, kind, trigger_ref)
        if self._live_runs(principal.workspace_id) >= self.settings.workflow_max_active_runs:
            raise WorkflowLimitError("Too many workflow runs are active in this workspace")
        run = WorkflowRunRecord(workspace_id=principal.workspace_id, requested_by=principal.user_id,
                                definition_id=rec.id, workflow_key=key, version=rec.version,
                                definition_digest=rec.definition_digest, status=R.PENDING, trigger_type=kind,
                                trigger_ref=trigger_ref, idempotency_key=idempotency_key,
                                step_count=len(defn.steps), cancel_requested=False)
        self.db.add(run)
        try:
            self.db.flush()
            for i, s in enumerate(defn.steps):
                self.db.add(WorkflowStepRecord(run_id=run.id, workspace_id=run.workspace_id, step_key=s.id, position=i,
                                               agent_id=s.agent_id, depends_on=list(s.depends_on), status=S.PENDING,
                                               attempts=0, max_attempts=s.retry.max_attempts,
                                               timeout_seconds=s.timeout_seconds))
            self.db.flush()
            self._event(run, "workflow.run_created", principal.user_id, definition_sha256=run.definition_digest,
                        steps=len(defn.steps), trigger=kind)
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            again = ((self._run_by_idem(principal.workspace_id, idempotency_key) if idempotency_key else None)
                     or (self._run_by_ref(principal.workspace_id, key, kind, trigger_ref) if trigger_ref else None))
            if again is None:
                raise
            return self._replay(again, principal, key, kind, trigger_ref)
        return run

    def get_run(self, principal: Principal, run_id: str) -> WorkflowRunRecord:
        run = self._load(principal.workspace_id, run_id)
        if not self._can_see(principal, run):
            raise WorkflowNotFoundError("Workflow run not found")
        return run

    def steps(self, principal: Principal, run_id: str) -> List[WorkflowStepRecord]:
        return self._steps(self.get_run(principal, run_id))

    def list_runs(self, principal: Principal, *, status: Optional[R] = None, workflow_key: Optional[str] = None,
                  limit: int = 50) -> List[WorkflowRunRecord]:
        limit = max(1, min(int(limit), 200))
        if principal.agent is not None:
            return []
        q = select(WorkflowRunRecord).where(WorkflowRunRecord.workspace_id == principal.workspace_id)
        if not principal.can("agent:manage"):
            q = q.where(WorkflowRunRecord.requested_by == principal.user_id)
        if status is not None:
            q = q.where(WorkflowRunRecord.status == status)
        if workflow_key is not None:
            q = q.where(WorkflowRunRecord.workflow_key == workflow_key)
        return list(self.db.scalars(q.order_by(WorkflowRunRecord.created_at.desc(), WorkflowRunRecord.id).limit(limit)))

    def due_steps(self, principal: Principal, run_id: str) -> List[str]:
        """Step keys that may start now: PENDING, every dependency SUCCEEDED, and any retry delay elapsed.
        Read-only; the engine (9.3) still goes through `begin_step`, which re-checks all of it."""
        run = self._load_driven(principal, run_id)
        if run.status != R.RUNNING or run.cancel_requested:
            return []
        rows = self._steps(run)
        plan = self.definition_of(self._definition_row(run)).to_plan()
        now = self._clock()
        wait = {s.step_key: _aware(s.next_attempt_at) for s in rows}
        return [s.id for s in ready_steps(plan, {s.step_key: s.status for s in rows})
                if wait[s.id] is None or wait[s.id] <= now]

    # ================================================================ run lifecycle
    def start(self, principal: Principal, run_id: str) -> WorkflowRunRecord:
        run = self._load_driven(principal, run_id)
        return self._run_cas(run, R.RUNNING, (R.PENDING,), principal.user_id, "workflow.run_started",
                             started_at=self._clock())

    def checkpoint(self, principal: Principal, run_id: str) -> WorkflowRunRecord:
        """Called by the driver between steps: completes a requested cancellation, or confirms the run is live."""
        run = self._load_driven(principal, run_id)
        if run.status == R.CANCELLED:
            raise WorkflowCancelledError("Workflow run was cancelled")
        if run.status != R.RUNNING:
            raise WorkflowStateError(f"Workflow run is {run.status.value}, not running")
        if run.cancel_requested:
            self._cancel_now(run, principal.user_id)
            raise WorkflowCancelledError("Workflow run was cancelled")
        return run

    def cancel(self, principal: Principal, run_id: str) -> WorkflowRunRecord:
        run = self.get_run(principal, run_id)
        if principal.agent is not None:
            raise WorkflowForbiddenError("Agents cannot cancel workflow runs")
        if run.status == R.CANCELLED:
            return run                                                           # idempotent
        if run.status == R.RUNNING:
            res = self.db.execute(update(WorkflowRunRecord).where(
                WorkflowRunRecord.id == run.id, WorkflowRunRecord.workspace_id == run.workspace_id,
                WorkflowRunRecord.status == R.RUNNING).values(cancel_requested=True, updated_at=self._clock()))
            if res.rowcount == 1:
                self._event(run, "workflow.cancel_requested", principal.user_id)
                self.db.commit()
                self.db.refresh(run)
                return run
            self.db.rollback()
            run = self._load(run.workspace_id, run.id)
            if run.status == R.CANCELLED:
                return run
        return self._cancel_now(run, principal.user_id)

    def settle_cancel(self, principal: Principal, run_id: str) -> WorkflowRunRecord:
        """Finishes a requested cancellation when no step is executing (nobody is mid-step to reach a checkpoint)."""
        run = self.get_run(principal, run_id)
        if principal.agent is not None:
            raise WorkflowForbiddenError("Agents cannot cancel workflow runs")
        if run.status == R.RUNNING and run.cancel_requested and not any(s.status == S.RUNNING for s in self._steps(run)):
            return self._cancel_now(run, principal.user_id)
        return run

    def complete(self, principal: Principal, run_id: str) -> WorkflowRunRecord:
        """RUNNING -> SUCCEEDED/FAILED once every step is finished. Partial results stay readable per step."""
        run = self._load_driven(principal, run_id)
        rows = self._steps(run)
        states = {s.step_key: s.status for s in rows}
        plan = self.definition_of(self._definition_row(run)).to_plan()
        if run.status != R.RUNNING or not is_finished(plan, states):
            raise WorkflowStateError("Workflow run is not running or still has unfinished steps")
        result = outcome(plan, states)
        summary = {"outcome": result, "steps": {k: v.value for k, v in states.items()},
                   "attempts": {s.step_key: s.attempts for s in rows}}
        if result == "succeeded":
            return self._run_cas(run, R.SUCCEEDED, (R.RUNNING,), principal.user_id, "workflow.run_succeeded",
                                 result=summary, finished_at=self._clock())
        return self._run_cas(run, R.FAILED, (R.RUNNING,), principal.user_id, "workflow.run_failed", result=summary,
                             error_code="steps_failed", finished_at=self._clock())

    # ================================================================ step lifecycle
    def begin_step(self, principal: Principal, run_id: str, step_key: str, agent_run_id: str) -> WorkflowStepRecord:
        run = self._load_driven(principal, run_id)
        if run.status != R.RUNNING or run.cancel_requested:
            raise WorkflowStateError("Workflow run is not accepting new steps")
        step = self._step(run, step_key)
        states = {s.step_key: s.status for s in self._steps(run)}
        if any(states.get(d) != S.SUCCEEDED for d in step.depends_on):
            raise WorkflowStateError("The step's dependencies have not all succeeded")
        if step.attempts >= step.max_attempts:
            raise WorkflowStateError("The step has no attempts left")
        due = _aware(step.next_attempt_at)
        if due is not None and due > self._clock():
            raise WorkflowStateError("The step's retry delay has not elapsed")
        ar = self.db.scalar(select(AgentRun).where(AgentRun.id == agent_run_id,
                                                   AgentRun.workspace_id == run.workspace_id))
        if ar is None or ar.requested_by != principal.user_id or ar.agent_id != step.agent_id:
            raise InvalidWorkflowRequestError("The agent run does not belong to this step")
        now = self._clock()
        try:
            return self._step_cas(run, step, S.RUNNING, (S.PENDING,), principal.user_id, "workflow.step_started",
                                  attempts=WorkflowStepRecord.attempts + 1, agent_run_id=ar.id, started_at=now,
                                  deadline_at=now + timedelta(seconds=step.timeout_seconds), next_attempt_at=None,
                                  error_code=None, _extra={"agent_run_id": ar.id})
        except IntegrityError:                                                   # agent run already serves a step
            self.db.rollback()
            raise WorkflowConflictError("The agent run is already bound to a step") from None

    def mark_step_waiting(self, principal: Principal, run_id: str, step_key: str) -> WorkflowStepRecord:
        run = self._load_driven(principal, run_id)
        return self._step_cas(run, self._step(run, step_key), S.WAITING_APPROVAL, (S.RUNNING,), principal.user_id,
                              "workflow.step_waiting", deadline_at=None)      # the approval wait has its own limit

    def resume_step(self, principal: Principal, run_id: str, step_key: str) -> WorkflowStepRecord:
        run = self._load_driven(principal, run_id)
        step = self._step(run, step_key)
        return self._step_cas(run, step, S.RUNNING, (S.WAITING_APPROVAL,), principal.user_id, "workflow.step_resumed",
                              deadline_at=self._clock() + timedelta(seconds=step.timeout_seconds))

    def finish_step(self, principal: Principal, run_id: str, step_key: str, to: S, *, code: Optional[str] = None,
                    result: Optional[Dict[str, Any]] = None) -> WorkflowStepRecord:
        """Final outcome of a step (no retry). Use `fail_attempt` for a failure that may be retried."""
        if to not in _FINISH:
            raise InvalidWorkflowRequestError("A step finishes as succeeded, failed or cancelled")
        if to == S.FAILED:
            code = code or "step_failed"
        self._check_code(code)
        run = self._load_driven(principal, run_id)
        fields: Dict[str, Any] = {"finished_at": self._clock(), "result": self._bounded(result), "deadline_at": None}
        if code:
            fields["error_code"] = code
        return self._step_cas(run, self._step(run, step_key), to, _ACTIVE, principal.user_id,
                              f"workflow.step_{to.value}", **fields)

    def fail_attempt(self, principal: Principal, run_id: str, step_key: str, code: str, *,
                     result: Optional[Dict[str, Any]] = None) -> WorkflowStepRecord:
        """An attempt failed. While the step's retry policy allows another attempt (and the run is not being
        cancelled) the step returns to PENDING with `next_attempt_at`; otherwise it FAILS for good."""
        self._check_code(code)
        run = self._load_driven(principal, run_id)
        step = self._step(run, step_key)
        policy = self.definition_of(self._definition_row(run)).step(step_key).retry
        if (step.status in _ACTIVE and not run.cancel_requested and run.status == R.RUNNING
                and policy.should_retry(step.attempts) and step.attempts < step.max_attempts):
            delay = policy.delay_after(step.attempts)
            return self._step_cas(run, step, S.PENDING, _ACTIVE, principal.user_id, "workflow.step_retry_scheduled",
                                  error_code=code, result=self._bounded(result), deadline_at=None,
                                  next_attempt_at=self._clock() + timedelta(seconds=delay),
                                  _extra={"attempt": step.attempts, "delay_seconds": delay})
        return self.finish_step(principal, run_id, step_key, S.FAILED, code=code, result=result)

    def skip_blocked(self, principal: Principal, run_id: str) -> List[str]:
        """Marks PENDING steps SKIPPED when a dependency failed/skipped/cancelled (transitively)."""
        run = self._load_driven(principal, run_id)
        if run.status != R.RUNNING:
            raise WorkflowStateError("Workflow run is not running")
        rows = {s.step_key: s for s in self._steps(run)}
        plan = self.definition_of(self._definition_row(run)).to_plan()
        out: List[str] = []
        for key in steps_to_skip(plan, {k: s.status for k, s in rows.items()}):
            try:
                self._step_cas(run, rows[key], S.SKIPPED, (S.PENDING,), principal.user_id, "workflow.step_skipped",
                               error_code="dependency_failed", finished_at=self._clock(), next_attempt_at=None)
                out.append(key)
            except WorkflowStateError:
                continue
        return out

    # ================================================================ internals
    def _require_manager(self, p: Principal) -> None:
        if p.agent is not None or not p.can("agent:manage"):
            raise WorkflowForbiddenError("Not allowed to manage workflows")

    def _require_runner(self, p: Principal) -> None:
        if p.agent is not None or not p.can("agent:run"):
            raise WorkflowForbiddenError("Not allowed to run workflows")

    def _require_reader(self, p: Principal) -> None:
        if p.agent is not None or not (p.can("agent:run") or p.can("agent:manage")):
            raise WorkflowForbiddenError("Not allowed to read workflows")

    def _latest(self, workspace_id: str, key: str) -> Optional[WorkflowRecord]:
        return self.db.scalar(select(WorkflowRecord).where(
            WorkflowRecord.workspace_id == workspace_id, WorkflowRecord.workflow_key == key)
            .order_by(WorkflowRecord.version.desc()).limit(1))

    def _count_keys(self, workspace_id: str) -> int:
        return self.db.scalar(select(func.count(func.distinct(WorkflowRecord.workflow_key))).where(
            WorkflowRecord.workspace_id == workspace_id)) or 0

    def _live_runs(self, workspace_id: str) -> int:
        return self.db.scalar(select(func.count()).select_from(WorkflowRunRecord).where(
            WorkflowRunRecord.workspace_id == workspace_id, WorkflowRunRecord.status.in_(_LIVE_RUN))) or 0

    def _startable(self, principal: Principal, key: str, version: Optional[int]) -> WorkflowRecord:
        q = select(WorkflowRecord).where(WorkflowRecord.workspace_id == principal.workspace_id,
                                         WorkflowRecord.workflow_key == key)
        if version is not None:
            rec = self.db.scalar(q.where(WorkflowRecord.version == version))
            if rec is not None and rec.status == W.ARCHIVED:
                raise WorkflowStateError("That workflow version is archived")
        else:
            rec = self.db.scalar(q.where(WorkflowRecord.status == W.ACTIVE).order_by(WorkflowRecord.version.desc()).limit(1))
        if rec is None:
            raise WorkflowNotFoundError("Workflow not found")
        return rec

    def _definition_row(self, run: WorkflowRunRecord) -> WorkflowRecord:
        rec = self.db.scalar(select(WorkflowRecord).where(WorkflowRecord.id == run.definition_id,
                                                          WorkflowRecord.workspace_id == run.workspace_id))
        if rec is None or rec.definition_digest != run.definition_digest:
            raise WorkflowStateError("The run's workflow definition is unavailable")
        return rec

    def _steps(self, run: WorkflowRunRecord) -> List[WorkflowStepRecord]:
        return list(self.db.scalars(select(WorkflowStepRecord).where(
            WorkflowStepRecord.run_id == run.id, WorkflowStepRecord.workspace_id == run.workspace_id)
            .order_by(WorkflowStepRecord.position)))

    def _step(self, run: WorkflowRunRecord, key: str) -> WorkflowStepRecord:
        s = self.db.scalar(select(WorkflowStepRecord).where(
            WorkflowStepRecord.run_id == run.id, WorkflowStepRecord.workspace_id == run.workspace_id,
            WorkflowStepRecord.step_key == key))
        if s is None:
            raise WorkflowNotFoundError("Step not found")
        self.db.refresh(s)
        return s

    def _load(self, workspace_id: str, run_id: str) -> WorkflowRunRecord:
        run = self.db.scalar(select(WorkflowRunRecord).where(WorkflowRunRecord.id == run_id,
                                                             WorkflowRunRecord.workspace_id == workspace_id))
        if run is None:
            raise WorkflowNotFoundError("Workflow run not found")
        self.db.refresh(run)
        return run

    def _can_see(self, p: Principal, run: WorkflowRunRecord) -> bool:
        if run.workspace_id != p.workspace_id or p.agent is not None:
            return False
        return run.requested_by == p.user_id or p.can("agent:manage")

    def _load_driven(self, p: Principal, run_id: str) -> WorkflowRunRecord:
        """Driver-facing load: only the user who created the run, never an agent, never an admin."""
        run = self._load(p.workspace_id, run_id)
        if p.agent is not None or not self._can_see(p, run):
            raise WorkflowNotFoundError("Workflow run not found")
        if run.requested_by != p.user_id:
            raise WorkflowForbiddenError("Only the user who created the run can drive it")
        return run

    def _run_by_idem(self, workspace_id: str, key: str) -> Optional[WorkflowRunRecord]:
        return self.db.scalar(select(WorkflowRunRecord).where(WorkflowRunRecord.workspace_id == workspace_id,
                                                              WorkflowRunRecord.idempotency_key == key))

    def _run_by_ref(self, workspace_id: str, key: str, kind: str, ref: Optional[str]) -> Optional[WorkflowRunRecord]:
        return self.db.scalar(select(WorkflowRunRecord).where(
            WorkflowRunRecord.workspace_id == workspace_id, WorkflowRunRecord.workflow_key == key,
            WorkflowRunRecord.trigger_type == kind, WorkflowRunRecord.trigger_ref == ref))

    def _replay(self, existing: WorkflowRunRecord, p: Principal, key: str, kind: str,
                ref: Optional[str]) -> WorkflowRunRecord:
        if (existing.requested_by != p.user_id or existing.workflow_key != key or existing.trigger_type != kind
                or existing.trigger_ref != ref):
            raise WorkflowConflictError("That idempotency_key or trigger_ref was already used for a different request")
        return existing

    @staticmethod
    def _check_code(code: Optional[str]) -> None:
        if code is not None and not _CODE_RE.match(code):
            raise InvalidWorkflowRequestError("error code must be a short slug")

    def _bounded(self, result: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if result is None:
            return None
        if not isinstance(result, dict):
            raise InvalidWorkflowRequestError("result must be an object")
        safe = redact(result)
        try:
            size = len(json.dumps(safe, default=str).encode())
        except (TypeError, ValueError):
            raise InvalidWorkflowRequestError("result must be JSON-serialisable")
        if size > MAX_RESULT_BYTES:
            raise InvalidWorkflowRequestError(f"result is too large (max {MAX_RESULT_BYTES} bytes)")
        return safe

    def _def_event(self, rec: WorkflowRecord, event_type: str, actor: str, **payload: Any) -> None:
        record_event(self.db, workspace_id=rec.workspace_id, event_type=event_type, actor=actor,
                     payload={"workflow_id": rec.id, "workflow": rec.workflow_key, "version": rec.version,
                              "definition_sha256": rec.definition_digest, **payload})

    def _event(self, run: WorkflowRunRecord, event_type: str, actor: str, **payload: Any) -> None:
        record_event(self.db, workspace_id=run.workspace_id, event_type=event_type, actor=actor,
                     payload={"run_id": run.id, "workflow": run.workflow_key, "version": run.version,
                              "status": run.status.value, **payload})

    def _run_cas(self, run: WorkflowRunRecord, to: R, sources, actor: str, event_type: str,
                 **fields: Any) -> WorkflowRunRecord:
        frm = run.status
        res = self.db.execute(update(WorkflowRunRecord).where(
            WorkflowRunRecord.id == run.id, WorkflowRunRecord.workspace_id == run.workspace_id,
            WorkflowRunRecord.status.in_(sources)).values(status=to, updated_at=self._clock(), **fields))
        if res.rowcount != 1:
            self.db.rollback()
            fresh = self._load(run.workspace_id, run.id)
            raise WorkflowStateError(f"Workflow run is {fresh.status.value}; cannot move to {to.value}")
        self.db.refresh(run)
        extra: Dict[str, Any] = {"from": frm.value, "to": to.value}
        if run.error_code and to == R.FAILED:
            extra["error_code"] = run.error_code
        self._event(run, event_type, actor, **extra)
        self.db.commit()
        return run

    def _step_cas(self, run: WorkflowRunRecord, step: WorkflowStepRecord, to: S, sources, actor: str,
                  event_type: str, _extra: Optional[Dict[str, Any]] = None, **fields: Any) -> WorkflowStepRecord:
        frm = step.status
        res = self.db.execute(update(WorkflowStepRecord).where(
            WorkflowStepRecord.id == step.id, WorkflowStepRecord.run_id == run.id,
            WorkflowStepRecord.workspace_id == run.workspace_id, WorkflowStepRecord.status.in_(sources))
            .values(status=to, updated_at=self._clock(), **fields))
        if res.rowcount != 1:
            self.db.rollback()
            self.db.refresh(step)
            raise WorkflowStateError(f"Step is {step.status.value}; cannot move to {to.value}")
        self.db.refresh(step)
        self._event(run, event_type, actor, step=step.step_key, agent=step.agent_id, attempts=step.attempts,
                    **{"from": frm.value, "to": to.value}, **(_extra or {}),
                    **({"error_code": step.error_code} if step.error_code else {}))
        self.db.commit()
        return step

    def _cancel_now(self, run: WorkflowRunRecord, actor: str) -> WorkflowRunRecord:
        self.db.execute(update(WorkflowStepRecord).where(
            WorkflowStepRecord.run_id == run.id, WorkflowStepRecord.workspace_id == run.workspace_id,
            WorkflowStepRecord.status.in_((S.PENDING,) + _ACTIVE))
            .values(status=S.CANCELLED, finished_at=self._clock(), updated_at=self._clock(),
                    next_attempt_at=None, deadline_at=None))
        return self._run_cas(run, R.CANCELLED, (R.PENDING, R.RUNNING), actor, "workflow.run_cancelled",
                             cancel_requested=True, finished_at=self._clock())
