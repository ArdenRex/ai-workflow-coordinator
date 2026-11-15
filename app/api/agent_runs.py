"""Agent run endpoints. Thin: authority, limits, approvals and audit all live in AgentRunService / the kernel.

POST /runs creates a run AND executes it synchronously (the goal is never stored, so it cannot be executed
later). Runs are visible to the user who started them; admins (agent:manage) see and cancel all runs in the
workspace but can never drive someone else's run. A run the caller cannot see is a plain 404.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.agents import errors as ae
from app.agents.executor import AgentExecutor
from app.agents.registry import AgentRegistry
from app.agents.runs import MAX_GOAL_CHARS, AgentRunService
from app.api.ai import get_tool_registry
from app.config import Settings, get_settings
from app.database import get_db
from app.kernel.policy_store import session_policy_provider
from app.identity.context import WorkspaceContext, require_permission
from app.llm import errors as llm_errors
from app.llm.credentials import workspace_llm
from app.memory.context import memory_provider
from app.models.agents import AgentRun
from app.models.enums import AgentRunStatus
from app.api.ai import _http as llm_http

router = APIRouter(prefix="/workspaces/{workspace_id}/agents", tags=["agents"])


def get_agent_registry(request: Request) -> AgentRegistry:
    return request.app.state.agent_registry


class AgentView(BaseModel):
    id: str
    name: str
    description: str
    capabilities: List[str]
    max_risk: str


class StartRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: str = Field(min_length=2, max_length=32)
    goal: str = Field(min_length=1, max_length=MAX_GOAL_CHARS)
    idempotency_key: Optional[str] = Field(default=None, min_length=1, max_length=128)
    max_steps: Optional[int] = Field(default=None, ge=1, le=50)
    max_tool_calls: Optional[int] = Field(default=None, ge=0, le=25)
    max_llm_calls: Optional[int] = Field(default=None, ge=0, le=50)
    timeout_seconds: Optional[int] = Field(default=None, ge=5, le=3600)


class RunView(BaseModel):
    """Content-free by construction: no goal, no goal digest, no tool output."""
    id: str
    agent_id: str
    status: AgentRunStatus
    requested_by: str
    goal_chars: int
    max_steps: int
    max_tool_calls: int
    max_llm_calls: int
    steps_used: int
    tool_calls_used: int
    llm_calls_used: int
    cancel_requested: bool
    pending_execution_id: Optional[str]
    result: Optional[Dict[str, Any]]
    error_code: Optional[str]
    expires_at: Optional[datetime]
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    created_at: datetime

    @classmethod
    def of(cls, r: AgentRun) -> "RunView":
        return cls(**{k: getattr(r, k) for k in cls.model_fields})


def _http(exc: ae.AgentError) -> HTTPException:
    """Fixed client-facing messages; the run record and audit trail hold the detail."""
    if isinstance(exc, ae.RunNotFoundError):
        return HTTPException(404, "Run not found")
    if isinstance(exc, ae.RunForbiddenError):
        return HTTPException(403, "Insufficient permissions")
    if isinstance(exc, ae.InvalidRunRequestError):
        return HTTPException(422, "The run request is not valid")
    if isinstance(exc, ae.AgentNotFoundError):
        return HTTPException(422, "Unknown agent")
    if isinstance(exc, (ae.RunConflictError, ae.RunStateError, ae.RunCancelledError, ae.RunExpiredError)):
        return HTTPException(409, "The run is not in a state that allows this")
    return HTTPException(400, "The run request could not be processed")


def _services(db: Session, settings: Settings, agents: AgentRegistry):
    return AgentRunService(db, agents, settings)


@router.get("", response_model=List[AgentView])
def list_agents(ctx: WorkspaceContext = Depends(require_permission("agent:run")),
                agents: AgentRegistry = Depends(get_agent_registry)):
    return [AgentView(**a.describe()) for a in agents.list()]


@router.post("/runs", response_model=RunView, status_code=201)
def start_run(body: StartRunRequest, ctx: WorkspaceContext = Depends(require_permission("agent:run")),
              db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
              agents: AgentRegistry = Depends(get_agent_registry),
              tools=Depends(get_tool_registry)):
    user = ctx.principal()
    runs = _services(db, settings, agents)
    try:
        # Resolve the model first: a workspace without a usable LLM must not leave an orphan QUEUED run.
        with workspace_llm(db, settings, ctx.workspace.id) as llm:
            run = runs.create(user, body.agent_id, body.goal, idempotency_key=body.idempotency_key,
                              max_steps=body.max_steps, max_tool_calls=body.max_tool_calls,
                              max_llm_calls=body.max_llm_calls, timeout_seconds=body.timeout_seconds)
            if run.status == AgentRunStatus.QUEUED:          # an idempotent replay of a finished run is returned as is
                run = AgentExecutor(db, runs, agents, tools, llm, context_provider=memory_provider(db, settings),
                                     base_policy_provider=session_policy_provider(db)).execute(user, run.id, body.goal)
            return RunView.of(run)
    except llm_errors.LLMError as exc:
        raise llm_http(exc)
    except ae.AgentError as exc:
        raise _http(exc)


@router.get("/runs", response_model=List[RunView])
def list_runs(status: Optional[AgentRunStatus] = None, limit: int = Query(50, ge=1, le=200),
              ctx: WorkspaceContext = Depends(require_permission("agent:run")),
              db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
              agents: AgentRegistry = Depends(get_agent_registry)):
    return [RunView.of(r) for r in _services(db, settings, agents).list(ctx.principal(), status=status, limit=limit)]


@router.get("/runs/{run_id}", response_model=RunView)
def get_run(run_id: str, ctx: WorkspaceContext = Depends(require_permission("agent:run")),
            db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
            agents: AgentRegistry = Depends(get_agent_registry)):
    try:
        return RunView.of(_services(db, settings, agents).get(ctx.principal(), run_id))
    except ae.AgentError as exc:
        raise _http(exc)


@router.post("/runs/{run_id}/cancel", response_model=RunView)
def cancel_run(run_id: str, ctx: WorkspaceContext = Depends(require_permission("agent:run")),
               db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
               agents: AgentRegistry = Depends(get_agent_registry)):
    try:
        return RunView.of(_services(db, settings, agents).cancel(ctx.principal(), run_id))
    except ae.AgentError as exc:
        raise _http(exc)


@router.post("/runs/{run_id}/resume", response_model=RunView)
def resume_run(run_id: str, ctx: WorkspaceContext = Depends(require_permission("agent:run")),
               db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
               agents: AgentRegistry = Depends(get_agent_registry), tools=Depends(get_tool_registry)):
    """Continue a run whose approval has been decided. Needs no model call, so it does not resolve an LLM."""
    runs = _services(db, settings, agents)
    try:
        return RunView.of(AgentExecutor(db, runs, agents, tools, None, base_policy_provider=session_policy_provider(db)).resume(ctx.principal(), run_id))
    except ae.AgentError as exc:
        raise _http(exc)
