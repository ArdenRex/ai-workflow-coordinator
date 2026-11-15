"""Bounded agent executor: drives ONE run through the Step 5 chain, inside the run's limits.

    execute():  start -> [step] understand -> [step] plan -> [step + tool call] submit to the kernel
                  - executed          -> SUCCEEDED   (result = outcome + execution id, never tool output)
                  - needs approval    -> WAITING_APPROVAL (returns; a human decides in the kernel)
                  - nothing to do     -> SUCCEEDED with outcome no_action / needs_information
                  - denied / invalid  -> FAILED with a fixed error code
    resume():   after the approval is decided: execute the approved execution (or fail), then finish.

Why this is safe
- The executor has NO authority of its own. It acts as the agent principal (user intersect agent scope) and every
  real action goes through `submit_proposal` -> the kernel, which re-validates input, permission, policy and
  approval. The agent's tool-access rules are enforced by the kernel policy (6.2), not by this module.
- Every LLM call is charged to the run's budget BEFORE it is made (`_BudgetedLLM`), including structured-output
  repairs, so the budget cannot be bypassed by a retry loop. Steps and tool calls are charged before their stage.
  Cancellation and deadlines are checked at every charge.
- One tool call per run in 6.4 (multi-step plans belong to Step 7). The kernel idempotency key `run:<id>` means a
  repeated submit can never create a second execution.
- Content-free: the goal is passed in memory and must match the run's recorded digest; it is never stored. Results
  hold fixed outcome words, tool ids and execution ids only. Failure codes are fixed slugs.
- Any unexpected error fails the run with `executor_error` (details go to logs only).
"""
import logging
import re
from typing import Callable, Optional

from sqlalchemy.orm import Session

from app.agents.context import AgentContext, build_agent_context
from app.agents.errors import (InvalidRunRequestError, RunCancelledError, RunError, RunExpiredError,
                               RunForbiddenError, RunLimitError, RunStateError)
from app.agents.registry import AgentRegistry
from app.agents.runs import AgentRunService
from app.intelligence.planning import PlanStatus, ProposalMismatchError, ToolCallPlanner, submit_proposal
from app.intelligence.understanding import RequestUnderstandingService
from app.kernel.audit import input_digest
from app.kernel.errors import KernelError
from app.kernel.permissions import Principal
from app.kernel.policy import WorkspacePolicy
from app.kernel.registry import ToolRegistry
from app.llm.errors import LLMError
from app.llm.service import LLMService
from app.models.agents import AgentRun
from app.models.enums import AgentRunStatus as S
from app.models.enums import ExecutionStatus

logger = logging.getLogger(__name__)
_SLUG = re.compile(r"[^a-z0-9_.]")


def _kernel_code(exc: KernelError) -> str:
    return ("kernel_" + _SLUG.sub("_", str(getattr(exc, "code", "error")).lower()))[:64]


class _BudgetedLLM(LLMService):
    """An LLMService that spends one unit of the run's LLM budget before every provider call."""

    def __init__(self, base: LLMService, charge: Callable[[], object]):
        super().__init__(base.db, base.provider, base.settings, sleep=base._sleep, clock=base._clock)
        self._charge = charge

    def complete(self, **kwargs):                       # noqa: D401  (same signature as LLMService.complete)
        self._charge()                                  # raises RunLimitError / RunCancelledError / RunExpiredError
        return super().complete(**kwargs)


class AgentExecutor:
    def __init__(self, db: Session, runs: AgentRunService, agents: AgentRegistry, tools: ToolRegistry,
                 llm: Optional[LLMService], *, base_policy_provider: Optional[Callable[[str], WorkspacePolicy]] = None,
                 context_provider=None):
        self.db, self.runs, self.agents, self.tools, self.llm = db, runs, agents, tools, llm
        self.base_policy_provider = base_policy_provider
        self.context_provider = context_provider            # business memory as untrusted data (8.5); None = no memory

    # ------------------------------------------------------------------ execute
    def execute(self, user: Principal, run_id: str, goal: str) -> AgentRun:
        if self.llm is None:                             # resume-only executors carry no model
            raise InvalidRunRequestError("This executor has no model and cannot execute a run")
        run, ctx = self._open(user, run_id)
        if not isinstance(goal, str) or input_digest(goal.strip()) != run.goal_digest:
            raise InvalidRunRequestError("The goal does not match the one this run was created for")
        p = ctx.principal
        self.runs.start(p, run_id)                       # RunStateError if not QUEUED: caller error, no state change
        try:
            llm = _BudgetedLLM(self.llm, lambda: self.runs.charge(p, run_id, "llm_call"))
            self.runs.charge(p, run_id, "step")
            intent = RequestUnderstandingService(llm, self.tools, policy_provider=ctx.policy,
                                                 context_provider=self.context_provider).understand(p, goal)
            self.runs.charge(p, run_id, "step")
            plan = ToolCallPlanner(llm, self.tools, policy_provider=ctx.policy,
                                   context_provider=self.context_provider).plan(p, goal, intent)

            if plan.status == PlanStatus.NO_ACTION:
                return self.runs.succeed(p, run_id, {"outcome": "no_action", "reason": plan.reason})
            if plan.status == PlanStatus.NEEDS_INFORMATION:
                return self.runs.succeed(p, run_id, {"outcome": "needs_information", "reason": plan.reason,
                                                     "missing_count": len(plan.missing_information)})
            if plan.status != PlanStatus.PROPOSED or plan.proposal is None:
                return self.runs.fail(p, run_id, ("plan_" + _SLUG.sub("_", str(plan.reason or "rejected")))[:64])

            self.runs.charge(p, run_id, "step")
            self.runs.charge(p, run_id, "tool_call")
            try:
                ex = submit_proposal(ctx.execution_service(self.db), p, plan.proposal,
                                     idempotency_key=f"run:{run_id}")
            except ProposalMismatchError:
                return self.runs.fail(p, run_id, "proposal_mismatch")
            except KernelError as exc:                   # denied by policy/permission, or invalid input
                return self.runs.fail(p, run_id, _kernel_code(exc))
            return self._after_submit(p, run_id, ex, plan.proposal.tool_id)
        except (RunCancelledError, RunExpiredError, RunLimitError):
            return self.runs.get(user, run_id)           # already terminal; the record says why
        except LLMError as exc:
            return self._safe_fail(p, user, run_id, exc.code)
        except Exception:                                # never leak internals; the run records a fixed code
            logger.exception("Agent executor failure")
            return self._safe_fail(p, user, run_id, "executor_error")

    # ------------------------------------------------------------------ resume after approval
    def resume(self, user: Principal, run_id: str) -> AgentRun:
        run, ctx = self._open(user, run_id)
        p = ctx.principal
        pending = run.pending_execution_id
        try:
            self.runs.resume(p, run_id)                  # RunStateError unless waiting AND the approval is decided
        except RunExpiredError:                          # the approval wait ran out: the run is now EXPIRED, nothing runs
            return self.runs.get(user, run_id)
        try:
            svc = ctx.execution_service(self.db)
            ex = svc.get(pending, p.workspace_id)
            tool_id = ex.tool_id
            if ex.status == ExecutionStatus.APPROVED:
                self.runs.charge(p, run_id, "step")
                try:
                    ex = svc.execute_approved(p, ex.id)  # kernel re-checks approval, input binding, policy
                except KernelError as exc:
                    return self.runs.fail(p, run_id, _kernel_code(exc))
            elif ex.status == ExecutionStatus.REJECTED:
                return self.runs.fail(p, run_id, "approval_rejected")
            elif ex.status == ExecutionStatus.EXPIRED:
                return self.runs.fail(p, run_id, "approval_expired")
            return self._after_submit(p, run_id, ex, tool_id)
        except (RunCancelledError, RunExpiredError, RunLimitError):
            return self.runs.get(user, run_id)
        except Exception:
            logger.exception("Agent executor failure")
            return self._safe_fail(p, user, run_id, "executor_error")

    # ------------------------------------------------------------------ internals
    def _open(self, user: Principal, run_id: str):
        if user.agent is not None:
            raise RunForbiddenError("Runs are executed on behalf of a user, not by an agent principal")
        run = self.runs.get(user, run_id)
        if run.requested_by != user.user_id:             # an admin may see another user's run, never drive it
            raise RunForbiddenError("Only the user who started the run can execute it")
        ctx: AgentContext = build_agent_context(user, run.agent_id, self.agents, self.tools,
                                                base_policy_provider=self.base_policy_provider)
        return run, ctx

    def _after_submit(self, p: Principal, run_id: str, ex, tool_id: str) -> AgentRun:
        if ex.status == ExecutionStatus.SUCCEEDED:
            return self.runs.succeed(p, run_id, {"outcome": "executed", "tool_id": tool_id, "execution_id": ex.id})
        if ex.status == ExecutionStatus.AWAITING_APPROVAL:
            return self.runs.wait_for_approval(p, run_id, ex.id)
        if ex.status == ExecutionStatus.FAILED:
            return self.runs.fail(p, run_id, "tool_failed")
        return self.runs.fail(p, run_id, "unexpected_execution_state")

    def _safe_fail(self, p: Principal, user: Principal, run_id: str, code: str) -> AgentRun:
        try:
            return self.runs.fail(p, run_id, code)
        except RunError:                                  # already finished by someone else
            return self.runs.get(user, run_id)
