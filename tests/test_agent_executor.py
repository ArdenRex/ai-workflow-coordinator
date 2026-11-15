"""Step 6.4: the bounded agent executor on the Step 5 chain."""
import json
import logging

import pytest
from sqlalchemy import func, select

from app.agents.errors import (InvalidRunRequestError, RunForbiddenError, RunNotFoundError, RunStateError)
from app.agents.executor import AgentExecutor
from app.intelligence.understanding import RequestUnderstandingService
from app.kernel.approvals import ApprovalService
from app.kernel.errors import ApprovalStateError
from app.llm.errors import LLMAuthError
from app.llm.fake import FakeProvider
from app.llm.service import LLMService
from app.models import Approval, ApprovalStatus, ExecutionStatus, RiskLevel, Role, SystemEvent, ToolExecution
from app.models.enums import AgentRunStatus as S
from tests.test_agent_context import CALLS
from tests.test_agent_runs import (Clock, agent_p, agents, clock, events, member, svc, svc_for, tools,  # noqa: F401
                                   users)

pytestmark = pytest.mark.usefixtures("seed_workspaces")
GOAL = "Check the status of my business system"


def intent_json(tool="system.ping", **o):
    return json.dumps({**dict(kind="tool_request", summary="status", candidate_tools=[tool], confidence=0.95), **o})


def plan_json(tool="system.ping", args=None, **o):
    return json.dumps({**dict(tool_id=tool, arguments=args or {}, rationale="because", confidence=0.9,
                              missing_information=[]), **o})


class World:
    def __init__(self, db, svc, agents, tools, settings, script):
        self.db, self.svc, self.tools = db, svc, tools
        self.provider = FakeProvider(script)
        llm = LLMService(db, self.provider, settings, sleep=lambda s: None)
        self.exec = AgentExecutor(db, svc, agents, tools, llm)

    def run(self, agent="ops_agent", goal=GOAL, user=None, **limits):
        return self.svc.create(user or member(), agent, goal, **limits)

    def go(self, run, goal=GOAL, user=None):
        return self.exec.execute(user or member(), run.id, goal)


@pytest.fixture
def make_world(db_session, svc, agents, tools):
    def build(*script):
        return World(db_session, svc, agents, tools, svc.settings, list(script))
    return build


def n_exec(db):
    return db.scalar(select(func.count()).select_from(ToolExecution))


# ------------------------------------------------------------------ happy path
def test_low_risk_run_executes_through_the_kernel_and_records_truthfully(make_world, db_session):
    w = make_world(intent_json(), plan_json())
    run = w.go(w.run())
    assert run.status == S.SUCCEEDED and run.result["outcome"] == "executed" and run.result["tool_id"] == "system.ping"
    ex = db_session.get(ToolExecution, run.result["execution_id"])
    assert ex.status == ExecutionStatus.SUCCEEDED and ex.agent == "ops_agent" and ex.requested_by == "u1"
    assert ex.idempotency_key == f"run:{run.id}"
    assert (run.steps_used, run.llm_calls_used, run.tool_calls_used) == (3, 2, 1)
    types = {e.event_type for e in events(db_session, run)}
    assert {"agent_run.created", "agent_run.started", "agent_run.succeeded"} <= types
    blob = json.dumps([e.payload for e in events(db_session, run)]) + json.dumps(run.result)
    assert "business system" not in blob and "because" not in blob       # no goal text, no model text


def test_tool_output_is_not_copied_into_the_run_record(make_world, tools):
    w = make_world(intent_json("aceden.task.list"), plan_json("aceden.task.list"))
    run = w.go(w.run())
    assert run.status == S.SUCCEEDED and set(run.result) == {"outcome", "tool_id", "execution_id"}


def test_goal_must_match_the_recorded_digest_and_nothing_runs_otherwise(make_world, db_session):
    w = make_world(intent_json(), plan_json())
    run = w.run()
    for bad in ("Delete all customers", "", None):
        with pytest.raises(InvalidRunRequestError):
            w.go(run, goal=bad)
    assert run.status == S.QUEUED and w.provider.requests == [] and n_exec(db_session) == 0
    assert w.go(run, goal=f"  {GOAL}  ").status == S.SUCCEEDED          # whitespace-insensitive like create()


def test_a_run_can_only_be_executed_once(make_world, db_session):
    w = make_world(intent_json(), plan_json())
    run = w.go(w.run())
    with pytest.raises(RunStateError):
        w.go(run)
    assert n_exec(db_session) == 1 and len(w.provider.requests) == 2


# ------------------------------------------------------------------ approvals
def test_medium_risk_run_waits_then_executes_only_after_a_human_approves(make_world, db_session, tools):
    w = make_world(intent_json("aceden.task.update"), plan_json("aceden.task.update", {"task_id": 5}))
    run = w.go(w.run("task_writer"))
    assert run.status == S.WAITING_APPROVAL and CALLS == [] and run.pending_execution_id
    with pytest.raises(RunStateError):
        w.exec.resume(member(), run.id)                                    # not decided yet
    assert run.status == S.WAITING_APPROVAL
    approval = db_session.scalar(select(Approval).where(Approval.execution_id == run.pending_execution_id))
    ApprovalService(db_session).decide(approval.id, member("u2", role=Role.ADMIN), approve=True)
    assert CALLS == []                                                     # approving alone runs nothing
    done = w.exec.resume(member(), run.id)
    assert done.status == S.SUCCEEDED and done.result["outcome"] == "executed" and [c[0] for c in CALLS] == ["update"]
    assert CALLS[0][2] == "task_writer"                                    # the handler saw the agent identity
    assert db_session.get(Approval, approval.id).status == ApprovalStatus.EXECUTED


@pytest.mark.parametrize("approve,code", [(False, "approval_rejected")])
def test_rejected_approval_fails_the_run_and_runs_nothing(make_world, db_session, approve, code):
    w = make_world(intent_json("aceden.task.update"), plan_json("aceden.task.update", {"task_id": 5}))
    run = w.go(w.run("task_writer"))
    approval = db_session.scalar(select(Approval).where(Approval.execution_id == run.pending_execution_id))
    ApprovalService(db_session).decide(approval.id, member("u2", role=Role.ADMIN), approve=approve)
    done = w.exec.resume(member(), run.id)
    assert done.status == S.FAILED and done.error_code == code and CALLS == []


def test_approving_after_the_approval_wait_expired_never_executes(make_world, db_session, clock):
    w = make_world(intent_json("aceden.task.update"), plan_json("aceden.task.update", {"task_id": 5}))
    run = w.go(w.run("task_writer"))
    approval = db_session.scalar(select(Approval).where(Approval.execution_id == run.pending_execution_id))
    ApprovalService(db_session).decide(approval.id, member("u2", role=Role.ADMIN), approve=True)
    clock.advance(seconds=w.svc.settings.agent_run_approval_wait_seconds + 1)       # no sweeper ran: resume must still refuse
    done = w.exec.resume(member(), run.id)
    assert done.status == S.EXPIRED and CALLS == []
    with pytest.raises(RunStateError):                                              # and it stays dead
        w.exec.resume(member(), run.id)
    assert CALLS == []


def test_cancelling_a_waiting_run_withdraws_its_approval_so_it_can_never_execute(make_world, db_session):
    w = make_world(intent_json("aceden.task.update"), plan_json("aceden.task.update", {"task_id": 5}))
    run = w.go(w.run("task_writer"))
    ex_id = run.pending_execution_id
    w.svc.cancel(member(), run.id)
    approval = db_session.scalar(select(Approval).where(Approval.execution_id == ex_id))
    assert run.status == S.CANCELLED and approval.status == ApprovalStatus.REJECTED
    assert db_session.get(ToolExecution, ex_id).status == ExecutionStatus.REJECTED
    with pytest.raises(ApprovalStateError):                                # a human can no longer approve it
        ApprovalService(db_session).decide(approval.id, member("u2", role=Role.ADMIN), approve=True)
    ev = [e for e in db_session.scalars(select(SystemEvent)) if e.event_type == "approval.withdrawn"]
    assert len(ev) == 1 and ev[0].payload["reason"] == "run_cancelled" and ev[0].actor == "system"
    assert CALLS == []


def test_expiring_a_waiting_run_withdraws_its_approval(make_world, db_session, clock):
    w = make_world(intent_json("aceden.task.update"), plan_json("aceden.task.update", {"task_id": 5}))
    run = w.go(w.run("task_writer"))
    clock.advance(seconds=86401)
    assert w.svc.expire_overdue("w1") == 1
    approval = db_session.scalar(select(Approval).where(Approval.execution_id == run.pending_execution_id))
    assert run.status == S.EXPIRED and approval.status == ApprovalStatus.REJECTED


def test_withdraw_never_touches_a_decided_approval(make_world, db_session):
    w = make_world(intent_json("aceden.task.update"), plan_json("aceden.task.update", {"task_id": 5}))
    run = w.go(w.run("task_writer"))
    approval = db_session.scalar(select(Approval).where(Approval.execution_id == run.pending_execution_id))
    ApprovalService(db_session).decide(approval.id, member("u2", role=Role.ADMIN), approve=True)
    assert ApprovalService(db_session).withdraw(approval.id, "w1", reason="x") is False
    assert ApprovalService(db_session).withdraw(approval.id, "w2", reason="x") is False      # other workspace
    assert db_session.get(Approval, approval.id).status == ApprovalStatus.APPROVED


# ------------------------------------------------------------------ budgets
def test_llm_budget_is_charged_before_each_call_and_stops_the_chain(make_world, db_session):
    w = make_world(intent_json(), plan_json())
    run = w.go(w.run(max_llm_calls=1))
    assert run.status == S.FAILED and run.error_code == "limit_llm_calls"
    assert len(w.provider.requests) == 1 and n_exec(db_session) == 0        # the 2nd model call never happened


def test_structured_output_repairs_spend_budget_too(make_world, db_session):
    w = make_world("not json at all", intent_json(), plan_json())           # 1 repair (default) + plan = 3 calls
    ok = w.go(w.run())
    assert ok.status == S.SUCCEEDED and ok.llm_calls_used == 3
    w2 = make_world("not json at all", intent_json(), plan_json())
    tight = w2.go(w2.run(max_llm_calls=2))
    assert tight.status == S.FAILED and tight.error_code == "limit_llm_calls" and len(w2.provider.requests) == 2


def test_zero_tool_budget_blocks_execution_before_the_kernel_is_called(make_world, db_session):
    w = make_world(intent_json(), plan_json())
    run = w.go(w.run(max_tool_calls=0))
    assert run.status == S.FAILED and run.error_code == "limit_tool_calls" and n_exec(db_session) == 0


def test_step_budget_is_enforced(make_world, db_session):
    w = make_world(intent_json(), plan_json())
    run = w.go(w.run(max_steps=2))
    assert run.status == S.FAILED and run.error_code == "limit_steps" and n_exec(db_session) == 0


# ------------------------------------------------------------------ cancel / deadline mid-run
def test_cancel_during_the_run_stops_before_any_further_model_call_or_tool(make_world, db_session):
    state = {}

    def cancel_during_first_call(request):
        w.svc.cancel(member(), state["run"].id)                              # user hits cancel while the model thinks
        return intent_json()
    w = make_world(cancel_during_first_call, plan_json())
    state["run"] = w.run()
    run = w.go(state["run"])
    assert run.status == S.CANCELLED and len(w.provider.requests) == 1 and n_exec(db_session) == 0


def test_deadline_passing_during_the_run_expires_it_before_the_tool_runs(make_world, db_session, clock):
    def slow_model(request):
        clock.advance(seconds=500)
        return intent_json()
    w = make_world(slow_model, plan_json())
    run = w.go(w.run())
    assert run.status == S.EXPIRED and n_exec(db_session) == 0 and len(w.provider.requests) == 1


# ------------------------------------------------------------------ no action / hostile model
@pytest.mark.parametrize("script,outcome,reason", [
    ([intent_json(kind="goal")], "no_action", "goal_needs_orchestration"),
    ([intent_json(kind="smalltalk", candidate_tools=[])], "no_action", "intent_not_actionable"),
    ([intent_json(needs_clarification=True, clarifying_question="Which?")], "no_action", "needs_clarification"),
    ([intent_json(), plan_json(missing_information=["customer email, sk-leak"])], "needs_information",
     "missing_information"),
    ([intent_json(), plan_json(tool=None)], "no_action", "model_chose_no_tool"),
])
def test_nothing_to_do_succeeds_with_a_fixed_outcome_and_no_model_text(make_world, db_session, script, outcome, reason):
    w = make_world(*script)
    run = w.go(w.run())
    assert run.status == S.SUCCEEDED and run.result["outcome"] == outcome and run.result["reason"] == reason
    assert n_exec(db_session) == 0 and "leak" not in json.dumps(run.result) and "Which" not in json.dumps(run.result)


def test_agent_tool_rules_hide_tools_the_agent_may_not_use(make_world, db_session):
    w = make_world(intent_json("aceden.task.update"), plan_json("aceden.task.update", {"task_id": 5}))
    run = w.go(w.run("ops_agent"))                                           # ops_agent has no task.update access
    assert run.status == S.SUCCEEDED and run.result["reason"] in ("no_tools_available", "intent_not_actionable")
    assert n_exec(db_session) == 0 and CALLS == []


@pytest.mark.parametrize("tool", ["aceden.customer.delete", "aceden.task.update", "ghost.tool"])
def test_hostile_plan_naming_a_forbidden_tool_fails_without_executing(make_world, db_session, tool):
    w = make_world(intent_json(), plan_json(tool, {"task_id": 1}))
    run = w.go(w.run("ops_agent"))
    assert run.status == S.FAILED and run.error_code == "plan_tool_not_allowed"
    assert n_exec(db_session) == 0 and CALLS == []


def test_invalid_model_output_fails_the_run_with_a_fixed_code(make_world, db_session):
    w = make_world("garbage", "garbage again")
    run = w.go(w.run())
    assert run.status == S.SUCCEEDED and run.result["reason"] == "intent_not_actionable"   # understanding degrades safely
    w2 = make_world(intent_json(), "garbage", "garbage")
    bad = w2.go(w2.run())
    assert bad.status == S.FAILED and bad.error_code == "plan_model_output_invalid" and n_exec(db_session) == 0


# ------------------------------------------------------------------ failures
def test_llm_failure_fails_the_run_with_its_code_only(make_world, db_session):
    w = make_world(LLMAuthError("bad key sk-secret-123"))
    run = w.go(w.run())
    assert run.status == S.FAILED and run.error_code == "llm_auth_failed" and n_exec(db_session) == 0
    assert "sk-secret" not in json.dumps([e.payload for e in events(db_session, run)])


def test_tool_failure_is_recorded_as_a_fixed_code(make_world, db_session, agents, tools):
    from app.agents.definition import AgentDefinition
    from app.kernel.registry import ToolDefinition
    from tests.test_agent_context import ListIn, Out

    def boom(ctx, data):
        raise RuntimeError("connection string postgres://u:pw@h/db")
    tools.register(ToolDefinition(id="aceden.boom.run", description="Always fails", input_schema=ListIn,
                                  output_schema=Out, required_permission="task:read", risk_level=RiskLevel.LOW,
                                  handler=boom))
    agents.register(AgentDefinition(id="boomer", name="Boom", description="Fails.", capabilities={"x.y"},
                                    tool_patterns=["aceden.boom.run"], scope_permissions={"task:read"}))
    w = make_world(intent_json("aceden.boom.run"), plan_json("aceden.boom.run"))
    run = w.go(w.run("boomer"))
    assert run.status == S.FAILED and run.error_code == "tool_failed"
    assert "postgres" not in json.dumps([e.payload for e in events(db_session, run)])


def test_unexpected_executor_error_fails_closed_without_leaking(make_world, db_session, monkeypatch, caplog):
    def explode(self, principal, message):
        raise RuntimeError("secret sk-internal-xyz")
    monkeypatch.setattr(RequestUnderstandingService, "understand", explode)
    w = make_world(intent_json(), plan_json())
    with caplog.at_level(logging.ERROR):
        run = w.go(w.run())
    assert run.status == S.FAILED and run.error_code == "executor_error" and n_exec(db_session) == 0
    assert "sk-internal" not in json.dumps([e.payload for e in events(db_session, run)])


def test_kernel_denial_fails_the_run_with_a_kernel_code(make_world, db_session):
    from app.kernel.policy import WorkspacePolicy
    flag = {"disabled": False}
    w = make_world(intent_json(), plan_json())
    w.exec.base_policy_provider = lambda ws: WorkspacePolicy(
        disabled_tools=frozenset({"system.ping"}) if flag["disabled"] else frozenset())

    def admin_disables_tool_while_model_plans(request):
        flag["disabled"] = True                                              # policy changes before submission
        return plan_json()
    w.provider._script[1] = admin_disables_tool_while_model_plans
    run = w.go(w.run())
    assert run.status == S.FAILED and run.error_code.startswith("kernel_") and CALLS == []
    assert n_exec(db_session) == 0                                            # denied before any execution row
    assert any(e.event_type.startswith("execution.denied") or "denied" in e.event_type
               for e in db_session.scalars(select(SystemEvent)))


# ------------------------------------------------------------------ authority
def test_only_the_runs_own_user_may_execute_it(make_world, db_session, agents, tools):
    w = make_world(intent_json(), plan_json())
    run = w.run()
    with pytest.raises(RunForbiddenError):
        w.exec.execute(agent_p(agents, tools), run.id, GOAL)                 # an agent principal can't
    with pytest.raises(RunNotFoundError):
        w.exec.execute(member("u2"), run.id, GOAL)                           # another user can't even see it
    with pytest.raises(RunForbiddenError):
        w.exec.execute(member("u2", role=Role.ADMIN), run.id, GOAL)          # a manager can see it, not drive it
    with pytest.raises(RunNotFoundError):
        w.exec.execute(member("u1", ws="w2"), run.id, GOAL)                  # other workspace
    assert run.status == S.QUEUED and w.provider.requests == [] and n_exec(db_session) == 0


def test_resume_has_the_same_authority_rules(make_world, db_session, agents, tools):
    w = make_world(intent_json("aceden.task.update"), plan_json("aceden.task.update", {"task_id": 5}))
    run = w.go(w.run("task_writer"))
    with pytest.raises(RunForbiddenError):
        w.exec.resume(agent_p(agents, tools, "task_writer"), run.id)
    with pytest.raises(RunNotFoundError):
        w.exec.resume(member("u2"), run.id)
    with pytest.raises(RunForbiddenError):
        w.exec.resume(member("u2", role=Role.ADMIN), run.id)
    assert run.status == S.WAITING_APPROVAL


def test_a_runs_events_stay_in_its_workspace_and_executions_are_bound_to_it(make_world, db_session):
    w = make_world(intent_json(), plan_json())
    run = w.go(w.run())
    ex = db_session.get(ToolExecution, run.result["execution_id"])
    assert ex.workspace_id == "w1" == run.workspace_id
    assert all(e.workspace_id == "w1" for e in db_session.scalars(select(SystemEvent)))
