"""AI endpoints. Every one is workspace-scoped and permission-checked like any other route."""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.identity.context import WorkspaceContext, require_permission
from app.intelligence.planning import PlanResult, ToolCallPlanner
from app.intelligence.understanding import MAX_MESSAGE_CHARS, RequestUnderstandingService, ResolvedIntent
from app.kernel.registry import ToolRegistry
from app.llm import errors as e
from app.llm.credentials import workspace_llm
from app.memory.context import memory_provider

router = APIRouter(prefix="/workspaces/{workspace_id}/ai", tags=["ai"])


class UnderstandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)


def get_tool_registry(request: Request) -> ToolRegistry:
    return request.app.state.tool_registry


def _http(exc: e.LLMError) -> HTTPException:
    """Generic client-facing errors; details stay in the audit trail and logs."""
    if isinstance(exc, e.LLMInputError):
        return HTTPException(422, "The message could not be processed")
    if isinstance(exc, e.LLMRateLimitedError):
        return HTTPException(429, "The AI provider is busy; try again shortly")
    if isinstance(exc, (e.LLMTimeoutError, e.LLMUnavailableError)):
        return HTTPException(503, "The AI provider is temporarily unavailable")
    return HTTPException(502, "The AI service is not available for this workspace")


@router.post("/understand", response_model=ResolvedIntent)
def understand(body: UnderstandRequest, ctx: WorkspaceContext = Depends(require_permission("ai:use")),
               db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
               registry: ToolRegistry = Depends(get_tool_registry)):
    try:
        with workspace_llm(db, settings, ctx.workspace.id) as llm:
            return RequestUnderstandingService(llm, registry, context_provider=memory_provider(db, settings)).understand(
                ctx.principal(), body.message)
    except e.LLMError as exc:
        raise _http(exc)


class PlanResponse(BaseModel):
    intent: ResolvedIntent
    plan: PlanResult


@router.post("/plan", response_model=PlanResponse)
def plan(body: UnderstandRequest, ctx: WorkspaceContext = Depends(require_permission("ai:use")),
         db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
         registry: ToolRegistry = Depends(get_tool_registry)):
    """Understand + plan. Returns a PROPOSAL only: nothing is executed by this endpoint."""
    principal = ctx.principal()
    try:
        with workspace_llm(db, settings, ctx.workspace.id) as llm:
            mem = memory_provider(db, settings)
            intent = RequestUnderstandingService(llm, registry, context_provider=mem).understand(principal, body.message)
            return PlanResponse(intent=intent, plan=ToolCallPlanner(llm, registry, context_provider=mem).plan(
                principal, body.message, intent))
    except e.LLMError as exc:
        raise _http(exc)
