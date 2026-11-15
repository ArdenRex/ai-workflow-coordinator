"""Workflow engine: drives a stored workflow run to completion through ordinary agent runs. It has NO authority.

    for each due step (dependencies all SUCCEEDED, retry delay elapsed, declaration order):
        create a run for the step's agent (goal = the step's stored instruction) -> bind it -> execute it via the
        Step 6 executor -> record the outcome (success, waiting, retry scheduled, or final failure).

Safety properties
- Every action is an agent run, so the user's permissions, the agent's scope and tool rules, workspace policy,
  approvals and audit all still apply. The engine only sequences runs; it never calls a tool or the kernel.
- Only the user who created the run can drive it (the store enforces this on every call; admins cannot). The
  instructions come from the stored definition the run is bound to, re-verified against its digest, so the
  caller cannot substitute different instructions.
- Dependency order is enforced twice: here (`due_steps`) and in the store (`begin_step`). A failed, skipped or
  cancelled dependency never unblocks anything; its dependents are SKIPPED and independent branches carry on.
- Retries are bounded by the definition (<= 5 attempts per step) and only ever happen for transient causes
  (model rate limit/timeout/unavailable, run expiry, step timeout) AND only when the failed attempt made NO tool
  call. A step whose attempt already touched a tool is never retried automatically, so a retry cannot repeat a
  side effect. Approval rejection, policy denial, auth errors and cancellations are never retried.
- Timeouts: an attempt that is still running past its deadline has its agent run cancelled (withdrawing any pending
  approval) and counts as a failed attempt with code `step_timeout`. Time spent waiting for an approval does not
  count against the step; the approval wait has its own limit in the agent run.
- Approvals: a step that needs a human goes to WAITING_APPROVAL and the run carries on with independent steps.
  When nothing else can run the drive returns. Calling `drive` again resumes any step whose approval has been
  decided; an undecided approval leaves it waiting. Nothing here can approve anything.
- Cancel: cancelling the run cancels every linked non-terminal agent run (withdrawing pending approvals) and settles
  the run. A cancel requested mid-drive is honoured at the next checkpoint, before any further step starts.
- Crash safety: agent-run creation is idempotent per (run, step, attempt), binding is a compare-and-swap, and
  `drive` reconciles steps whose agent run already finished, so repeating it never executes anything twice.
- Content-free: step results hold only fixed outcome words and ids; errors are fixed slugs.
`drive` never sleeps. When the only thing left is a retry delay it returns `waiting_retry` with the time the next
attempt is due; the scheduler (9.5) or any caller drives again later. State lives in the database alone.
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from app.agents.errors import RunError, RunStateError
from app.agents.executor import AgentExecutor
from app.agents.runs import AgentRunService, is_terminal
from app.kernel.permissions import Principal
from app.models.agents import AgentRun
from app.models.enums import AgentRunStatus as AR
from app.models.enums import StepState as S
from app.models.enums import WorkflowRunStatus as R
from app.models.workflows import WorkflowRunRecord
from app.workflows.errors import WorkflowCancelledError
from app.workflows.store import WorkflowService

logger = logging.getLogger(__name__)
_KEEP = ("outcome", "reason", "tool_id", "execution_id", "missing_count")
_DONE = (S.SUCCEEDED, S.FAILED, S.SKIPPED, S.CANCELLED)
# Transient causes only. Never: approval_*, kernel_*, plan_*, llm_auth_failed, executor_error, run_cancelled.
RETRYABLE_CODES = frozenset({"llm_rate_limited", "llm_timeout", "llm_unavailable", "run_expired", "step_timeout"})


def is_retryable(code: str, agent_run: Optional[AgentRun]) -> bool:
    """A failure may be retried only if its cause is transient AND the attempt made no tool call."""
    return code in RETRYABLE_CODES and agent_run is not None and (agent_run.tool_calls_used or 0) == 0


@dataclass(frozen=True)
class DriveResult:
    run: WorkflowRunRecord
    state: str                          # completed | cancelled | paused_approval | in_flight | waiting_retry
    retry_at: Optional[datetime] = None  # when state == waiting_retry: the earliest time the next attempt is due


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    return dt if dt is None or dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


class WorkflowEngine:
    def __init__(self, workflows: WorkflowService, runs: AgentRunService, executor: AgentExecutor):
        self.wf, self.runs, self.executor = workflows, runs, executor

    # ------------------------------------------------------------------ drive
    def drive(self, user: Principal, run_id: str) -> DriveResult:
        defn = self.wf.definition_for_run(user, run_id)                  # authority + digest, before anything moves
        rec = self.wf.get_run(user, run_id)
        if rec.status == R.PENDING:
            self.wf.start(user, run_id)
        bound = sum(s.retry.max_attempts for s in defn.steps) * 4 + len(defn.steps) * 3 + 3
        for _ in range(bound):                                           # every pass finishes, skips, waits or runs
            try:
                self.wf.checkpoint(user, run_id)
            except WorkflowCancelledError:
                self._cancel_linked_runs(user, run_id)
                return DriveResult(self.wf.get_run(user, run_id), "cancelled")
            self._reconcile(user, run_id)
            self._enforce_timeouts(user, run_id)
            self.wf.skip_blocked(user, run_id)
            steps = self.wf.steps(user, run_id)
            states = {s.step_key: s.status for s in steps}
            if all(st in _DONE for st in states.values()):
                return DriveResult(self.wf.complete(user, run_id), "completed")
            due = self.wf.due_steps(user, run_id)
            if due:
                self._run_step(user, run_id, defn, due[0])
                continue
            if S.RUNNING in states.values():
                return DriveResult(self.wf.get_run(user, run_id), "in_flight")
            waits = [_aware(s.next_attempt_at) for s in steps if s.status == S.PENDING and s.next_attempt_at]
            if waits:
                return DriveResult(self.wf.get_run(user, run_id), "waiting_retry", min(waits))
            return DriveResult(self.wf.get_run(user, run_id), "paused_approval")
        raise RuntimeError("workflow engine did not converge")           # pragma: no cover (bounded loop guard)

    # ------------------------------------------------------------------ cancel
    def cancel(self, principal: Principal, run_id: str) -> WorkflowRunRecord:
        """Cancels the run and every linked agent run still alive. The creator or an admin may call it."""
        self.wf.cancel(principal, run_id)
        self._cancel_linked_runs(principal, run_id)
        return self.wf.settle_cancel(principal, run_id)

    # ------------------------------------------------------------------ internals
    def _run_step(self, user: Principal, run_id: str, defn, key: str) -> None:
        step = defn.step(key)
        row = next(s for s in self.wf.steps(user, run_id) if s.step_key == key)
        timeout = max(5, min(step.timeout_seconds, self.runs.settings.agent_run_timeout_seconds))
        agent_run = self.runs.create(user, step.agent_id, step.instruction, timeout_seconds=timeout,
                                     idempotency_key=f"workflow:{run_id}:{key}:{row.attempts + 1}")
        self.wf.begin_step(user, run_id, key, agent_run.id)
        try:
            done = self.executor.execute(user, agent_run.id, step.instruction)
        except RunError as exc:                                          # the run never started (caller-level problem)
            logger.warning("Workflow step run could not execute: %s", exc.__class__.__name__)
            self._cancel_run(user, agent_run.id)
            self.wf.finish_step(user, run_id, key, S.FAILED, code="run_not_executed")
            return
        self._record(user, run_id, key, done)

    def _record(self, user: Principal, run_id: str, key: str, agent_run: AgentRun) -> None:
        """Maps an agent run's state onto its step. Only fixed words and ids are copied across."""
        if agent_run.status == AR.SUCCEEDED:
            result = {k: v for k, v in (agent_run.result or {}).items() if k in _KEEP}
            self.wf.finish_step(user, run_id, key, S.SUCCEEDED, result={**result, "run_id": agent_run.id})
        elif agent_run.status == AR.WAITING_APPROVAL:
            if self._step(user, run_id, key).status == S.RUNNING:
                self.wf.mark_step_waiting(user, run_id, key)
        elif agent_run.status == AR.CANCELLED:
            self.wf.finish_step(user, run_id, key, S.CANCELLED, code="run_cancelled", result={"run_id": agent_run.id})
        elif agent_run.status in (AR.FAILED, AR.EXPIRED):
            code = agent_run.error_code or f"run_{agent_run.status.value}"
            self._fail(user, run_id, key, code, agent_run)
        # QUEUED / RUNNING: still in flight somewhere else; leave the step as it is

    def _fail(self, user: Principal, run_id: str, key: str, code: str, agent_run: AgentRun) -> None:
        result = {"run_id": agent_run.id}
        if is_retryable(code, agent_run):
            self.wf.fail_attempt(user, run_id, key, code, result=result)     # retries only while the policy allows
        else:
            self.wf.finish_step(user, run_id, key, S.FAILED, code=code, result=result)

    def _reconcile(self, user: Principal, run_id: str) -> None:
        """Brings steps that already have an agent run in line with it (crash recovery and approval resumption)."""
        for step in self.wf.steps(user, run_id):
            if step.status not in (S.RUNNING, S.WAITING_APPROVAL) or step.agent_run_id is None:
                continue
            agent_run = self.runs.get(user, step.agent_run_id)
            if agent_run.status == AR.WAITING_APPROVAL and step.status == S.WAITING_APPROVAL:
                try:
                    agent_run = self.executor.resume(user, agent_run.id)    # refuses until the approval is decided
                except RunStateError:
                    continue                                                # still waiting for a human
                if agent_run.status == AR.WAITING_APPROVAL:
                    continue
                self.wf.resume_step(user, run_id, step.step_key)
            elif agent_run.status == AR.WAITING_APPROVAL and step.status == S.RUNNING:
                self.wf.mark_step_waiting(user, run_id, step.step_key)
                continue
            elif not is_terminal(agent_run.status):
                continue                                                    # genuinely in flight
            elif step.status == S.WAITING_APPROVAL:
                self.wf.resume_step(user, run_id, step.step_key)
            self._record(user, run_id, step.step_key, agent_run)

    def _enforce_timeouts(self, user: Principal, run_id: str) -> None:
        """A RUNNING attempt past its deadline is cancelled and counted as a failed attempt (`step_timeout`)."""
        now = self.wf.now()
        for step in self.wf.steps(user, run_id):
            deadline = _aware(step.deadline_at)
            if step.status != S.RUNNING or deadline is None or deadline > now or step.agent_run_id is None:
                continue
            self._cancel_run(user, step.agent_run_id)
            self._fail(user, run_id, step.step_key, "step_timeout", self.runs.get(user, step.agent_run_id))

    def _cancel_linked_runs(self, principal: Principal, run_id: str) -> int:
        n = 0
        for step in self.wf.steps(principal, run_id):
            if step.agent_run_id is not None and self._cancel_run(principal, step.agent_run_id):
                n += 1
        return n

    def _cancel_run(self, principal: Principal, agent_run_id: str) -> bool:
        try:
            run = self.runs.get(principal, agent_run_id)
            if is_terminal(run.status):
                return False
            self.runs.cancel(principal, agent_run_id)
            return True
        except RunError:
            return False

    def _step(self, user: Principal, run_id: str, key: str):
        return next(s for s in self.wf.steps(user, run_id) if s.step_key == key)
