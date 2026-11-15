"""Orchestration plan endpoints. Thin: authority, digests, ordering, approvals and audit live in the services.

POST /plans         decompose a goal into a plan, store it, optionally run it now (execute=true).
POST /plans/{id}/run  run or continue a stored plan. Instructions are never stored, so the caller sends the goal and
                      the steps again; both must match the stored digests. Call it again after approvals are decided.
GET  /plans[/{id}]  read plans: users see their own, admins (agent:manage) see all in the workspace.
POST /plans/{id}/cancel  cancels the plan and every linked run (creator or admin).
Responses carry ids, states, fixed codes and counters only. The one exception is the proposed plan returned by
POST /plans to the user who asked for it (so they can review and run it): it contains the model's step instructions.
A plan the caller cannot see is a plain 404. Runs are synchronous (background execution arrives in Step 9).
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import errors as ae
from app.agents.executor import AgentExecutor
from app.agents.registry import AgentRegistry
from app.agents.runs import MAX_GOAL_CHARS, AgentRunService
from app.api.agent_runs import _http as run_http
from app.api.agent_runs import get_agent_registry
from app.api.ai import _http as llm_http
from app.api.ai import get_tool_registry
from app.config import Settings, get_settings
from app.database import get_db
from app.kernel.policy_store import session_policy_provider
from app.identity.context import WorkspaceContext, require_permission
from app.llm import errors as llm_errors
from app.llm.credentials import workspace_llm
from app.memory.context import memory_provider
from app.models.agents import AgentRun
from app.models.enums import PlanStatus, StepState
from app.models.orchestration import PlanRecord, PlanStepRecord
from app.orchestration import errors as oe
from app.orchestration.aggregate import summarize
from app.orchestration.decompose import DecomposeStatus, GoalDecomposer
from app.orchestration.orchestrator import PlanOrchestrator
from app.orchestration.plan import (HARD_MAX_STEPS, MAX_DEPENDENCIES, MAX_INSTRUCTION_CHARS, ExecutionPlan,
                                    PlanStep)
from app.orchestration.store import PlanService

router = APIRouter(prefix="/workspaces/{workspace_id}/plans", tags=["plans"])


class StepIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=32)
    agent_id: str = Field(min_length=2, max_length=32)
    instruction: str = Field(min_length=1, max_length=MAX_INSTRUCTION_CHARS)
    depends_on: List[str] = Field(default_factory=list, max_length=MAX_DEPENDENCIES)


def _goal_not_blank(v: str) -> str:
    if not v.strip():
        raise ValueError("goal must not be blank")
    return v


class CreatePlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    goal: str = Field(min_length=1, max_length=MAX_GOAL_CHARS)
    idempotency_key: Optional[str] = Field(default=None, min_length=1, max_length=128)
    execute: bool = False
    _goal = field_validator("goal")(_goal_not_blank)


class RunPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    goal: str = Field(min_length=1, max_length=MAX_GOAL_CHARS)
    steps: List[StepIn] = Field(min_length=1, max_length=HARD_MAX_STEPS)
    _goal = field_validator("goal")(_goal_not_blank)


class StepView(BaseModel):
    key: str
    agent_id: str
    status: StepState
    depends_on: List[str]
    run_id: Optional[str]
    instruction_chars: int
    result: Optional[Dict[str, Any]]
    error_code: Optional[str]
    started_at: Optional[datetime]
    finished_at: Optional[datetime]

    @classmethod
    def of(cls, s: PlanStepRecord) -> "StepView":
        return cls(key=s.step_key, **{k: getattr(s, k) for k in cls.model_fields if k != "key"})


class PlanView(BaseModel):
    """Content-free: no goal, no instructions, no digests, no tool output."""
    id: str
    status: PlanStatus
    requested_by: str
    goal_chars: int
    step_count: int
    cancel_requested: bool
    error_code: Optional[str]
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    created_at: datetime
    steps: List[StepView] = []
    summary: Optional[Dict[str, Any]] = None

    @classmethod
    def of(cls, p: PlanRecord, steps: Optional[List[PlanStepRecord]] = None, pending: Optional[Dict[str, str]] = None):
        v = cls(**{k: getattr(p, k) for k in cls.model_fields if k not in ("steps", "summary")})
        if steps is not None:
            v.steps = [StepView.of(s) for s in steps]
            v.summary = summarize(p.status, steps, pending)
        return v


class ProposedStep(BaseModel):
    id: str
    agent_id: str
    instruction: str
    depends_on: List[str]


class CreatePlanResponse(BaseModel):
    decomposition: str                     # planned | needs_information | no_action | rejected
    reason: Optional[str] = None
    message: str
    missing_information: List[str] = []
    attempts: int = 0
    plan: Optional[PlanView] = None
    proposed_steps: Optional[List[ProposedStep]] = None    # for the requester to review and send back to /run
    drive_state: Optional[str] = None


class RunPlanResponse(BaseModel):
    drive_state: str                       # completed | cancelled | paused_approval | in_flight
    plan: PlanView


def _http(exc: oe.OrchestrationError) -> HTTPException:
    """Fixed client-facing messages; the plan record and audit trail hold the detail."""
    if isinstance(exc, oe.PlanNotFoundError):
        return HTTPException(404, "Plan not found")
    if isinstance(exc, oe.PlanForbiddenError):
        return HTTPException(403, "Insufficient permissions")
    if isinstance(exc, oe.InvalidPlanError):
        return HTTPException(422, f"The plan is not valid ({exc.code})")
    if isinstance(exc, oe.InvalidPlanRequestError):
        return HTTPException(422, "The plan request is not valid")
    if isinstance(exc, (oe.PlanConflictError, oe.PlanStateError, oe.PlanCancelledError)):
        return HTTPException(409, "The plan is not in a state that allows this")
    return HTTPException(400, "The plan request could not be processed")


def _plans(db: Session, settings: Settings, agents: AgentRegistry) -> PlanService:
    return PlanService(db, agents, settings)


def _orch(db, settings, agents, tools, llm) -> PlanOrchestrator:
    runs = AgentRunService(db, agents, settings)
    return PlanOrchestrator(_plans(db, settings, agents), runs, AgentExecutor(db, runs, agents, tools, llm,
                                                                        context_provider=memory_provider(db, settings),
                                                                        base_policy_provider=session_policy_provider(db)))


def _view(db: Session, plans: PlanService, principal, rec: PlanRecord) -> PlanView:
    steps = plans.steps(principal, rec.id)
    run_ids = [s.run_id for s in steps if s.run_id]
    pending: Dict[str, str] = {}
    if run_ids:
        for r in db.scalars(select(AgentRun).where(AgentRun.id.in_(run_ids), AgentRun.workspace_id == rec.workspace_id)):
            if r.pending_execution_id:
                pending[r.id] = r.pending_execution_id
    return PlanView.of(rec, steps, pending)


@router.post("", response_model=CreatePlanResponse)
def create_plan(body: CreatePlanRequest, ctx: WorkspaceContext = Depends(require_permission("agent:run")),
                db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
                agents: AgentRegistry = Depends(get_agent_registry), tools=Depends(get_tool_registry)):
    user = ctx.principal()
    plans = _plans(db, settings, agents)
    try:
        with workspace_llm(db, settings, ctx.workspace.id) as llm:     # resolve the model first: no orphan plans
            result = GoalDecomposer(llm, agents, tools, context_provider=memory_provider(db, settings)).decompose(user, body.goal)
            if result.status != DecomposeStatus.PLANNED:
                return CreatePlanResponse(decomposition=result.status.value, reason=result.reason, message=result.message,
                                          missing_information=result.missing_information, attempts=result.attempts)
            rec = plans.create(user, body.goal, result.plan, idempotency_key=body.idempotency_key)
            drive_state = None
            if body.execute:
                out = _orch(db, settings, agents, tools, llm).drive(user, rec.id, body.goal, result.plan)
                drive_state, rec = out.state, out.plan
            return CreatePlanResponse(
                decomposition="planned", message=result.message, attempts=result.attempts, plan=_view(db, plans, user, rec),
                proposed_steps=[ProposedStep(id=s.id, agent_id=s.agent_id, instruction=s.instruction,
                                             depends_on=list(s.depends_on)) for s in result.plan.steps],
                drive_state=drive_state)
    except llm_errors.LLMError as exc:
        raise llm_http(exc)
    except oe.OrchestrationError as exc:
        raise _http(exc)
    except ae.AgentError as exc:
        raise run_http(exc)


@router.post("/{plan_id}/run", response_model=RunPlanResponse)
def run_plan(plan_id: str, body: RunPlanRequest, ctx: WorkspaceContext = Depends(require_permission("agent:run")),
             db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
             agents: AgentRegistry = Depends(get_agent_registry), tools=Depends(get_tool_registry)):
    user = ctx.principal()
    try:
        plan = ExecutionPlan(tuple(PlanStep(s.id, s.agent_id, s.instruction, tuple(s.depends_on)) for s in body.steps))
    except oe.InvalidPlanError as exc:
        raise _http(exc)
    plans = _plans(db, settings, agents)
    try:
        plans.get(user, plan_id)                                       # 404 for anything the caller cannot see, before the model
        with workspace_llm(db, settings, ctx.workspace.id) as llm:
            out = _orch(db, settings, agents, tools, llm).drive(user, plan_id, body.goal, plan)
        return RunPlanResponse(drive_state=out.state, plan=_view(db, plans, user, out.plan))
    except llm_errors.LLMError as exc:
        raise llm_http(exc)
    except oe.OrchestrationError as exc:
        raise _http(exc)
    except ae.AgentError as exc:
        raise run_http(exc)


@router.get("", response_model=List[PlanView])
def list_plans(status: Optional[PlanStatus] = None, limit: int = Query(50, ge=1, le=200),
               ctx: WorkspaceContext = Depends(require_permission("agent:run")),
               db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
               agents: AgentRegistry = Depends(get_agent_registry)):
    return [PlanView.of(p) for p in _plans(db, settings, agents).list(ctx.principal(), status=status, limit=limit)]


@router.get("/{plan_id}", response_model=PlanView)
def get_plan(plan_id: str, ctx: WorkspaceContext = Depends(require_permission("agent:run")),
             db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
             agents: AgentRegistry = Depends(get_agent_registry)):
    user, plans = ctx.principal(), _plans(db, settings, agents)
    try:
        return _view(db, plans, user, plans.get(user, plan_id))
    except oe.OrchestrationError as exc:
        raise _http(exc)


@router.post("/{plan_id}/cancel", response_model=PlanView)
def cancel_plan(plan_id: str, ctx: WorkspaceContext = Depends(require_permission("agent:run")),
                db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
                agents: AgentRegistry = Depends(get_agent_registry), tools=Depends(get_tool_registry)):
    """Needs no model call, so it does not resolve an LLM."""
    user, plans = ctx.principal(), _plans(db, settings, agents)
    try:
        rec = _orch(db, settings, agents, tools, None).cancel(user, plan_id)
        return _view(db, plans, user, rec)
    except oe.OrchestrationError as exc:
        raise _http(exc)
    except ae.AgentError as exc:
        raise run_http(exc)
