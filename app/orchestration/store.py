"""Plan store: persistence, lifecycle state machine and content-free audit for execution plans. Executes NOTHING.

    plan:  PENDING --start--> RUNNING --complete--> SUCCEEDED | FAILED        cancel: PENDING/RUNNING -> CANCELLED
    step:  PENDING -> RUNNING <-> WAITING_APPROVAL -> SUCCEEDED | FAILED | CANCELLED;  PENDING -> SKIPPED | CANCELLED

Design rules (same family as agent runs)
- Every status change is a compare-and-swap UPDATE restricted to the workspace and the legal source states, so a
  terminal state is never left and two workers cannot both win.
- Dependency order is enforced HERE, not just in the orchestrator: a step can start only when the plan is RUNNING,
  not cancel-requested, and every dependency is SUCCEEDED in the database. A failed/skipped/cancelled dependency
  never unblocks anything.
- Content-free: the goal and step instructions are never stored (digest + length only), error codes are fixed slugs,
  results are redacted and capped, and audit payloads (`orchestration.*`) carry ids, states and codes only.
- A step is bound to an agent run in the same workspace, started by the same user, for the step's own agent; one run
  can serve at most one step.
- Authority: a plan belongs to the user who created it. Users see their own plans; `agent:manage` (admin+) sees every
  plan in the workspace and may cancel it, but only the owner drives it. Agent principals can do nothing here.
  Invisible and missing plans are indistinguishable (PlanNotFoundError).
- Cancelling a RUNNING plan only flags it; `checkpoint` (driven by the orchestrator) completes the cancellation and
  marks every unfinished step CANCELLED. The orchestrator (7.4) is responsible for cancelling linked agent runs.
"""
import json
import re
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agents.registry import AgentRegistry
from app.agents.runs import MAX_GOAL_CHARS
from app.config import Settings
from app.kernel.audit import input_digest, record_event, redact
from app.kernel.permissions import Principal
from app.models.agents import AgentRun
from app.models.enums import PlanStatus as P
from app.models.enums import StepState as S
from app.models.orchestration import PlanRecord, PlanStepRecord
from app.orchestration.errors import (InvalidPlanRequestError, PlanCancelledError, PlanConflictError,
                                      PlanForbiddenError, PlanNotFoundError, PlanStateError)
from app.orchestration.plan import (ExecutionPlan, PlanStep, is_finished, outcome, steps_to_skip,
                                    validate_for_workspace)

MAX_RESULT_BYTES = 16_000
_CODE_RE = re.compile(r"^[a-z0-9_.]{1,64}$")
_ACTIVE = (S.RUNNING, S.WAITING_APPROVAL)
_FINISH = frozenset({S.SUCCEEDED, S.FAILED, S.CANCELLED})


class PlanService:
    def __init__(self, db: Session, agents: AgentRegistry, settings: Settings, *,
                 clock: Optional[Callable[[], datetime]] = None):
        self.db, self.agents, self.settings = db, agents, settings
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    # ---------------------------------------------------------------- create / read
    def create(self, principal: Principal, goal: str, plan: ExecutionPlan, *,
               idempotency_key: Optional[str] = None) -> PlanRecord:
        if principal.agent is not None or not principal.can("agent:run"):
            raise PlanForbiddenError("Not allowed to create plans")
        if not isinstance(goal, str) or not goal.strip():
            raise InvalidPlanRequestError("A goal is required")
        if len(goal) > MAX_GOAL_CHARS:
            raise InvalidPlanRequestError(f"Goal is too long (max {MAX_GOAL_CHARS} characters)")
        if idempotency_key is not None and not 1 <= len(idempotency_key) <= 128:
            raise InvalidPlanRequestError("idempotency_key must be 1-128 characters")
        validate_for_workspace(plan, self.agents, max_steps=self.settings.plan_max_steps)   # InvalidPlanError
        digest, goal_digest = plan.digest(), input_digest(goal.strip())
        if idempotency_key is not None:
            existing = self._by_idempotency(principal.workspace_id, idempotency_key)
            if existing is not None:
                return self._replay(existing, principal, goal_digest, digest)
        rec = PlanRecord(workspace_id=principal.workspace_id, requested_by=principal.user_id, status=P.PENDING,
                         goal_digest=goal_digest, goal_chars=len(goal.strip()), plan_digest=digest,
                         step_count=len(plan.steps), idempotency_key=idempotency_key, cancel_requested=False)
        self.db.add(rec)
        try:
            self.db.flush()
            for i, s in enumerate(plan.steps):
                self.db.add(PlanStepRecord(plan_id=rec.id, workspace_id=rec.workspace_id, step_key=s.id, position=i,
                                           agent_id=s.agent_id, instruction_digest=input_digest(s.instruction),
                                           instruction_chars=len(s.instruction), depends_on=list(s.depends_on),
                                           status=S.PENDING))
            self.db.flush()
            self._event(rec, "orchestration.created", principal.user_id, plan_sha256=digest, steps=len(plan.steps),
                        goal_chars=rec.goal_chars)
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            existing = self._by_idempotency(principal.workspace_id, idempotency_key) if idempotency_key else None
            if existing is None:
                raise
            return self._replay(existing, principal, goal_digest, digest)
        return rec

    def get(self, principal: Principal, plan_id: str) -> PlanRecord:
        rec = self._load(principal.workspace_id, plan_id)
        if not self._can_see(principal, rec):
            raise PlanNotFoundError("Plan not found")
        return rec

    def steps(self, principal: Principal, plan_id: str) -> List[PlanStepRecord]:
        rec = self.get(principal, plan_id)
        return self._steps(rec)

    def list(self, principal: Principal, *, status: Optional[P] = None, limit: int = 50) -> List[PlanRecord]:
        limit = max(1, min(int(limit), 200))
        q = select(PlanRecord).where(PlanRecord.workspace_id == principal.workspace_id)
        if principal.agent is not None:
            return []
        if not principal.can("agent:manage"):
            q = q.where(PlanRecord.requested_by == principal.user_id)
        if status is not None:
            q = q.where(PlanRecord.status == status)
        return list(self.db.scalars(q.order_by(PlanRecord.created_at.desc(), PlanRecord.id).limit(limit)))

    # ---------------------------------------------------------------- plan lifecycle
    def start(self, principal: Principal, plan_id: str) -> PlanRecord:
        rec = self._load_driven(principal, plan_id)
        return self._plan_cas(rec, P.RUNNING, (P.PENDING,), principal.user_id, "orchestration.started",
                              started_at=self._clock())

    def checkpoint(self, principal: Principal, plan_id: str) -> PlanRecord:
        """Called by the driver between steps: completes a requested cancellation, or confirms the plan is live."""
        rec = self._load_driven(principal, plan_id)
        if rec.status == P.CANCELLED:
            raise PlanCancelledError("Plan was cancelled")
        if rec.status != P.RUNNING:
            raise PlanStateError(f"Plan is {rec.status.value}, not running")
        if rec.cancel_requested:
            self._cancel_now(rec, principal.user_id)
            raise PlanCancelledError("Plan was cancelled")
        return rec

    def cancel(self, principal: Principal, plan_id: str) -> PlanRecord:
        rec = self.get(principal, plan_id)
        if principal.agent is not None:
            raise PlanForbiddenError("Agents cannot cancel plans")
        if rec.status == P.CANCELLED:
            return rec                                                           # idempotent
        if rec.status == P.RUNNING:
            res = self.db.execute(update(PlanRecord).where(
                PlanRecord.id == rec.id, PlanRecord.workspace_id == rec.workspace_id, PlanRecord.status == P.RUNNING)
                .values(cancel_requested=True, updated_at=self._clock()))
            if res.rowcount == 1:
                self._event(rec, "orchestration.cancel_requested", principal.user_id)
                self.db.commit()
                self.db.refresh(rec)
                return rec
            self.db.rollback()
            rec = self._load(rec.workspace_id, rec.id)
            if rec.status == P.CANCELLED:
                return rec
        return self._cancel_now(rec, principal.user_id)

    def verify_inputs(self, principal: Principal, plan_id: str, goal: str, plan: ExecutionPlan) -> PlanRecord:
        """Instructions are never stored, so whoever drives a plan must present the same goal and plan again.
        Both must match the recorded digests, so the plan that executes is the plan that was audited."""
        rec = self._load_driven(principal, plan_id)
        if not isinstance(goal, str) or input_digest(goal.strip()) != rec.goal_digest:
            raise InvalidPlanRequestError("The goal does not match the one this plan was created for")
        if plan.digest() != rec.plan_digest:
            raise InvalidPlanRequestError("The plan does not match the one that was stored")
        return rec

    def settle_cancel(self, principal: Principal, plan_id: str) -> PlanRecord:
        """Finishes a requested cancellation when no step is executing right now (nobody is mid-step to reach a
        checkpoint). The creator or an admin may call it; a step in RUNNING means a driver is in flight, so the
        cancellation is left for that driver's next checkpoint. Safe to repeat."""
        rec = self.get(principal, plan_id)
        if principal.agent is not None:
            raise PlanForbiddenError("Agents cannot cancel plans")
        if rec.status == P.RUNNING and rec.cancel_requested and not any(s.status == S.RUNNING for s in self._steps(rec)):
            return self._cancel_now(rec, principal.user_id)
        return rec

    def complete(self, principal: Principal, plan_id: str) -> PlanRecord:
        """RUNNING -> SUCCEEDED/FAILED once every step is finished. Partial results stay readable per step."""
        rec = self._load_driven(principal, plan_id)
        states = {s.step_key: s.status for s in self._steps(rec)}
        if rec.status != P.RUNNING or not is_finished(self._structure(rec), states):
            raise PlanStateError("Plan is not running or still has unfinished steps")
        result = outcome(self._structure(rec), states)
        summary = {"outcome": result, "steps": {k: v.value for k, v in states.items()}}
        if result == "succeeded":
            return self._plan_cas(rec, P.SUCCEEDED, (P.RUNNING,), principal.user_id, "orchestration.succeeded",
                                  result=summary, finished_at=self._clock())
        return self._plan_cas(rec, P.FAILED, (P.RUNNING,), principal.user_id, "orchestration.failed",
                              result=summary, error_code="steps_failed", finished_at=self._clock())

    # ---------------------------------------------------------------- step lifecycle
    def begin_step(self, principal: Principal, plan_id: str, step_key: str, run_id: str) -> PlanStepRecord:
        rec = self._load_driven(principal, plan_id)
        if rec.status != P.RUNNING or rec.cancel_requested:
            raise PlanStateError("Plan is not accepting new steps")
        step = self._step(rec, step_key)
        states = {s.step_key: s.status for s in self._steps(rec)}
        if any(states.get(d) != S.SUCCEEDED for d in step.depends_on):
            raise PlanStateError("The step's dependencies have not all succeeded")
        run = self.db.scalar(select(AgentRun).where(AgentRun.id == run_id, AgentRun.workspace_id == rec.workspace_id))
        if run is None or run.requested_by != principal.user_id or run.agent_id != step.agent_id:
            raise InvalidPlanRequestError("The run does not belong to this step")
        try:
            return self._step_cas(rec, step, S.RUNNING, (S.PENDING,), principal.user_id, "orchestration.step_started",
                                  run_id=run.id, started_at=self._clock())
        except IntegrityError:                                                   # run already serves another step
            self.db.rollback()
            raise PlanConflictError("The run is already bound to a step") from None

    def mark_step_waiting(self, principal: Principal, plan_id: str, step_key: str) -> PlanStepRecord:
        rec = self._load_driven(principal, plan_id)
        return self._step_cas(rec, self._step(rec, step_key), S.WAITING_APPROVAL, (S.RUNNING,), principal.user_id,
                              "orchestration.step_waiting")

    def resume_step(self, principal: Principal, plan_id: str, step_key: str) -> PlanStepRecord:
        rec = self._load_driven(principal, plan_id)
        return self._step_cas(rec, self._step(rec, step_key), S.RUNNING, (S.WAITING_APPROVAL,), principal.user_id,
                              "orchestration.step_resumed")

    def finish_step(self, principal: Principal, plan_id: str, step_key: str, to: S, *, code: Optional[str] = None,
                    result: Optional[Dict[str, Any]] = None) -> PlanStepRecord:
        if to not in _FINISH:
            raise InvalidPlanRequestError("A step finishes as succeeded, failed or cancelled")
        if to == S.FAILED:
            code = code or "step_failed"
        if code is not None and not _CODE_RE.match(code):
            raise InvalidPlanRequestError("error code must be a short slug")
        rec = self._load_driven(principal, plan_id)
        fields: Dict[str, Any] = {"finished_at": self._clock(), "result": self._bounded(result)}
        if code:
            fields["error_code"] = code
        return self._step_cas(rec, self._step(rec, step_key), to, _ACTIVE, principal.user_id,
                              f"orchestration.step_{to.value}", **fields)

    def skip_blocked(self, principal: Principal, plan_id: str) -> List[str]:
        """Marks PENDING steps SKIPPED when a dependency failed/skipped/cancelled (transitively). Independent
        branches are untouched. Safe to repeat."""
        rec = self._load_driven(principal, plan_id)
        if rec.status != P.RUNNING:
            raise PlanStateError("Plan is not running")
        steps = {s.step_key: s for s in self._steps(rec)}
        out: List[str] = []
        for key in steps_to_skip(self._structure(rec), {k: s.status for k, s in steps.items()}):
            try:
                self._step_cas(rec, steps[key], S.SKIPPED, (S.PENDING,), principal.user_id,
                               "orchestration.step_skipped", error_code="dependency_failed", finished_at=self._clock())
                out.append(key)
            except PlanStateError:
                continue                                                         # someone else moved it: fine
        return out

    # ---------------------------------------------------------------- internals
    def _structure(self, rec: PlanRecord) -> ExecutionPlan:
        """Graph-only view rebuilt from stored structure (instructions are not stored: a placeholder stands in),
        used for scheduling logic. Its digest is NOT the plan digest and must never be used as one."""
        return ExecutionPlan(tuple(PlanStep(s.step_key, s.agent_id, "(not stored)", tuple(s.depends_on))
                                   for s in self._steps(rec)))

    def _steps(self, rec: PlanRecord) -> List[PlanStepRecord]:
        return list(self.db.scalars(select(PlanStepRecord).where(
            PlanStepRecord.plan_id == rec.id, PlanStepRecord.workspace_id == rec.workspace_id)
            .order_by(PlanStepRecord.position)))

    def _step(self, rec: PlanRecord, key: str) -> PlanStepRecord:
        s = self.db.scalar(select(PlanStepRecord).where(
            PlanStepRecord.plan_id == rec.id, PlanStepRecord.workspace_id == rec.workspace_id,
            PlanStepRecord.step_key == key))
        if s is None:
            raise PlanNotFoundError("Step not found")
        self.db.refresh(s)
        return s

    def _load(self, workspace_id: str, plan_id: str) -> PlanRecord:
        rec = self.db.scalar(select(PlanRecord).where(PlanRecord.id == plan_id, PlanRecord.workspace_id == workspace_id))
        if rec is None:
            raise PlanNotFoundError("Plan not found")
        self.db.refresh(rec)
        return rec

    def _can_see(self, principal: Principal, rec: PlanRecord) -> bool:
        if rec.workspace_id != principal.workspace_id or principal.agent is not None:
            return False
        return rec.requested_by == principal.user_id or principal.can("agent:manage")

    def _load_driven(self, principal: Principal, plan_id: str) -> PlanRecord:
        """Driver-facing load: only the user who created the plan, never an agent, never an admin."""
        rec = self._load(principal.workspace_id, plan_id)
        if principal.agent is not None or not self._can_see(principal, rec):
            raise PlanNotFoundError("Plan not found")
        if rec.requested_by != principal.user_id:                                # an admin sees it, cannot drive it
            raise PlanForbiddenError("Only the user who created the plan can drive it")
        return rec

    def _by_idempotency(self, workspace_id: str, key: str) -> Optional[PlanRecord]:
        return self.db.scalar(select(PlanRecord).where(PlanRecord.workspace_id == workspace_id,
                                                       PlanRecord.idempotency_key == key))

    def _replay(self, existing: PlanRecord, principal: Principal, goal_digest: str, plan_digest: str) -> PlanRecord:
        if (existing.requested_by != principal.user_id or existing.goal_digest != goal_digest
                or existing.plan_digest != plan_digest):
            raise PlanConflictError("idempotency_key was already used for a different request")
        return existing

    def _bounded(self, result: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if result is None:
            return None
        if not isinstance(result, dict):
            raise InvalidPlanRequestError("result must be an object")
        safe = redact(result)
        try:
            size = len(json.dumps(safe, default=str).encode())
        except (TypeError, ValueError):
            raise InvalidPlanRequestError("result must be JSON-serialisable")
        if size > MAX_RESULT_BYTES:
            raise InvalidPlanRequestError(f"result is too large (max {MAX_RESULT_BYTES} bytes)")
        return safe

    def _event(self, rec: PlanRecord, event_type: str, actor: str, **payload: Any) -> None:
        record_event(self.db, workspace_id=rec.workspace_id, event_type=event_type, actor=actor,
                     payload={"plan_id": rec.id, "status": rec.status.value, **payload})

    def _plan_cas(self, rec: PlanRecord, to: P, sources, actor: str, event_type: str, **fields: Any) -> PlanRecord:
        frm = rec.status
        res = self.db.execute(update(PlanRecord).where(
            PlanRecord.id == rec.id, PlanRecord.workspace_id == rec.workspace_id, PlanRecord.status.in_(sources))
            .values(status=to, updated_at=self._clock(), **fields))
        if res.rowcount != 1:
            self.db.rollback()
            fresh = self._load(rec.workspace_id, rec.id)
            raise PlanStateError(f"Plan is {fresh.status.value}; cannot move to {to.value}")
        self.db.refresh(rec)
        extra: Dict[str, Any] = {"from": frm.value, "to": to.value}
        if rec.error_code and to == P.FAILED:
            extra["error_code"] = rec.error_code
        self._event(rec, event_type, actor, **extra)
        self.db.commit()
        return rec

    def _step_cas(self, rec: PlanRecord, step: PlanStepRecord, to: S, sources, actor: str, event_type: str,
                  **fields: Any) -> PlanStepRecord:
        frm = step.status
        res = self.db.execute(update(PlanStepRecord).where(
            PlanStepRecord.id == step.id, PlanStepRecord.plan_id == rec.id,
            PlanStepRecord.workspace_id == rec.workspace_id, PlanStepRecord.status.in_(sources))
            .values(status=to, updated_at=self._clock(), **fields))
        if res.rowcount != 1:
            self.db.rollback()
            self.db.refresh(step)
            raise PlanStateError(f"Step is {step.status.value}; cannot move to {to.value}")
        self.db.refresh(step)
        self._event(rec, event_type, actor, step=step.step_key, agent=step.agent_id, **{"from": frm.value, "to": to.value},
                    **({"error_code": step.error_code} if step.error_code else {}))
        self.db.commit()
        return step

    def _cancel_now(self, rec: PlanRecord, actor: str) -> PlanRecord:
        self.db.execute(update(PlanStepRecord).where(
            PlanStepRecord.plan_id == rec.id, PlanStepRecord.workspace_id == rec.workspace_id,
            PlanStepRecord.status.in_((S.PENDING,) + _ACTIVE))
            .values(status=S.CANCELLED, finished_at=self._clock(), updated_at=self._clock()))
        return self._plan_cas(rec, P.CANCELLED, (P.PENDING, P.RUNNING), actor, "orchestration.cancelled",
                              cancel_requested=True, finished_at=self._clock())
