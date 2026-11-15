"""Plan orchestrator: drives a stored plan to completion through ordinary agent runs. It has NO authority of its own.

    for each ready step (dependencies all SUCCEEDED, declaration order):
        create a run for the step's agent (goal = the step's instruction) -> bind it -> execute it via the Step 6
        executor -> record the step outcome in the plan store.

Safety properties
- Every action is an agent run, so the user's permissions, the agent's scope and tool rules, workspace policy,
  approvals and audit all still apply. The orchestrator only sequences runs; it never calls a tool or the kernel.
- Only the user who created the plan can drive it (the store enforces this on every call; admins cannot). The caller
  must present the goal and plan again; both must match the stored digests (instructions are never stored).
- Dependency order is enforced twice: here (`ready_steps`) and in the store (`begin_step` refuses unless every
  dependency SUCCEEDED in the database). A failed, skipped or cancelled dependency never unblocks anything; its
  dependents are SKIPPED and independent branches carry on.
- Approvals: a step that needs a human goes to WAITING_APPROVAL and the plan carries on with independent steps.
  When nothing else can run the drive returns `paused_approval`. Calling `drive` again resumes any step whose approval
  has been decided; an undecided approval simply leaves the step waiting. Nothing here can approve anything.
- Cancel: cancelling the plan cancels every linked non-terminal run (withdrawing pending approvals) and settles the
  plan. A cancel requested mid-drive is honoured at the next checkpoint, before any further step starts.
- Crash safety: run creation is idempotent per (plan, step), binding is a compare-and-swap, and `drive` reconciles
  steps whose run already finished, so repeating it never executes anything twice.
- Content-free: step results hold only fixed outcome words and ids; errors are fixed slugs.
Execution is synchronous and sequential here (background workers arrive in Step 9). Results of earlier steps are NOT
passed into later instructions (aggregation is 7.5), so dependencies currently mean ordering and gating only.
"""
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

from app.agents.errors import RunError, RunStateError
from app.agents.executor import AgentExecutor
from app.agents.runs import AgentRunService, is_terminal
from app.kernel.permissions import Principal
from app.models.agents import AgentRun
from app.models.enums import AgentRunStatus as R
from app.models.enums import PlanStatus as P
from app.models.enums import StepState as S
from app.models.orchestration import PlanRecord, PlanStepRecord
from app.orchestration.errors import PlanCancelledError
from app.orchestration.plan import ExecutionPlan, ready_steps
from app.orchestration.store import PlanService

logger = logging.getLogger(__name__)
_KEEP = ("outcome", "reason", "tool_id", "execution_id", "missing_count")


@dataclass(frozen=True)
class DriveResult:
    plan: PlanRecord
    state: str            # completed | cancelled | paused_approval | in_flight


class PlanOrchestrator:
    def __init__(self, plans: PlanService, runs: AgentRunService, executor: AgentExecutor):
        self.plans, self.runs, self.executor = plans, runs, executor

    # ------------------------------------------------------------------ drive
    def drive(self, user: Principal, plan_id: str, goal: str, plan: ExecutionPlan) -> DriveResult:
        rec = self.plans.verify_inputs(user, plan_id, goal, plan)         # authority + digests, before anything moves
        if rec.status == P.PENDING:
            rec = self.plans.start(user, plan_id)
        bound = len(plan.steps) * 3 + 3                                    # every pass finishes, skips or waits a step
        for _ in range(bound):
            try:
                self.plans.checkpoint(user, plan_id)
            except PlanCancelledError:
                self._cancel_linked_runs(user, plan_id)
                return DriveResult(self.plans.get(user, plan_id), "cancelled")
            self._reconcile(user, plan_id)
            self.plans.skip_blocked(user, plan_id)
            steps = {s.step_key: s for s in self.plans.steps(user, plan_id)}
            states = {k: s.status for k, s in steps.items()}
            if all(st in (S.SUCCEEDED, S.FAILED, S.SKIPPED, S.CANCELLED) for st in states.values()):
                return DriveResult(self.plans.complete(user, plan_id), "completed")
            ready = ready_steps(plan, states)
            if not ready:
                busy = {S.RUNNING: "in_flight", S.WAITING_APPROVAL: "paused_approval"}
                kinds = [busy[st] for st in states.values() if st in busy]
                return DriveResult(self.plans.get(user, plan_id),
                                   "in_flight" if "in_flight" in kinds else "paused_approval")
            self._run_step(user, plan_id, plan, ready[0].id)
        raise RuntimeError("orchestrator did not converge")                # pragma: no cover (bounded loop guard)

    # ------------------------------------------------------------------ cancel
    def cancel(self, principal: Principal, plan_id: str) -> PlanRecord:
        """Cancels the plan and every linked run still alive. The creator or an admin may call it."""
        self.plans.cancel(principal, plan_id)
        self._cancel_linked_runs(principal, plan_id)
        return self.plans.settle_cancel(principal, plan_id)

    # ------------------------------------------------------------------ internals
    def _run_step(self, user: Principal, plan_id: str, plan: ExecutionPlan, key: str) -> None:
        step = plan.get(key)
        run = self.runs.create(user, step.agent_id, step.instruction, idempotency_key=f"plan:{plan_id}:{key}")
        self.plans.begin_step(user, plan_id, key, run.id)
        try:
            done = self.executor.execute(user, run.id, step.instruction)
        except RunError as exc:                                            # run never started (caller-level problem)
            logger.warning("Step run could not execute: %s", exc.__class__.__name__)
            self._cancel_run(user, run.id)
            self.plans.finish_step(user, plan_id, key, S.FAILED, code="run_not_executed")
            return
        self._record(user, plan_id, key, done)

    def _record(self, user: Principal, plan_id: str, key: str, run: AgentRun) -> None:
        """Maps a run's state onto its step. Only fixed words and ids are copied across."""
        if run.status == R.SUCCEEDED:
            result = {k: v for k, v in (run.result or {}).items() if k in _KEEP}
            self.plans.finish_step(user, plan_id, key, S.SUCCEEDED, result={**result, "run_id": run.id})
        elif run.status == R.WAITING_APPROVAL:
            step = self._step(user, plan_id, key)
            if step.status == S.RUNNING:
                self.plans.mark_step_waiting(user, plan_id, key)
        elif run.status == R.CANCELLED:
            self.plans.finish_step(user, plan_id, key, S.CANCELLED, code="run_cancelled", result={"run_id": run.id})
        elif run.status in (R.FAILED, R.EXPIRED):
            code = run.error_code or f"run_{run.status.value}"
            self.plans.finish_step(user, plan_id, key, S.FAILED, code=code, result={"run_id": run.id})
        # QUEUED / RUNNING: still in flight somewhere else; leave the step as it is

    def _reconcile(self, user: Principal, plan_id: str) -> None:
        """Brings steps that already have a run in line with that run (crash recovery and approval resumption)."""
        for step in self.plans.steps(user, plan_id):
            if step.status not in (S.RUNNING, S.WAITING_APPROVAL) or step.run_id is None:
                continue
            run = self.runs.get(user, step.run_id)
            if run.status == R.WAITING_APPROVAL and step.status == S.WAITING_APPROVAL:
                try:
                    run = self.executor.resume(user, run.id)          # refuses until the approval is decided
                except RunStateError:
                    continue                                          # still waiting for a human
                if run.status == R.WAITING_APPROVAL:
                    continue
                self.plans.resume_step(user, plan_id, step.step_key)
            elif run.status == R.WAITING_APPROVAL and step.status == S.RUNNING:
                self.plans.mark_step_waiting(user, plan_id, step.step_key)
                continue
            elif not is_terminal(run.status):
                continue                                              # genuinely in flight
            elif step.status == S.WAITING_APPROVAL:
                self.plans.resume_step(user, plan_id, step.step_key)
            self._record(user, plan_id, step.step_key, run)

    def _cancel_linked_runs(self, principal: Principal, plan_id: str) -> int:
        n = 0
        for step in self.plans.steps(principal, plan_id):
            if step.run_id is not None and self._cancel_run(principal, step.run_id):
                n += 1
        return n

    def _cancel_run(self, principal: Principal, run_id: str) -> bool:
        try:
            run = self.runs.get(principal, run_id)
            if is_terminal(run.status):
                return False
            self.runs.cancel(principal, run_id)
            return True
        except RunError:
            return False

    def _step(self, user: Principal, plan_id: str, key: str) -> PlanStepRecord:
        return next(s for s in self.plans.steps(user, plan_id) if s.step_key == key)
