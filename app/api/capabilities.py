"""Business capability endpoints (Step 11). Thin: all reading goes through the kernel in the capability service.

POST /workspaces/{id}/capabilities/attention       the operations digest ("what requires attention"); read-only.
POST /workspaces/{id}/capabilities/opportunities   qualified sales opportunities from the CRM; read-only.
POST /workspaces/{id}/capabilities/changes         what changed in the last 7 days (calendar, project, CRM, email counts); read-only.
POST /workspaces/{id}/capabilities/meetings        briefing for tomorrow's (UTC) meetings with possible related CRM leads; read-only.
Humans only (the signed-in user acting as themselves). It is a POST because it creates audited tool executions. The digest only
contains what the caller's own permissions allow; other sources are reported as not_permitted. Responses are fixed-shape and carry
no error text from remote systems.
"""
from typing import Callable

from fastapi import APIRouter, Depends

from app.api.ai import get_tool_registry
from app.capabilities.attention import AttentionDigest, AttentionService
from app.capabilities.changes import ChangesService, WeeklyChanges
from app.capabilities.meetings import MeetingBriefing, MeetingService
from app.capabilities.opportunities import OpportunityList, OpportunityService
from app.database import get_db
from app.identity.context import WorkspaceContext, get_workspace_context
from app.kernel.policy import WorkspacePolicy
from app.kernel.registry import ToolRegistry
from app.kernel.service import ToolExecutionService
from app.runtime import request_policy_provider
from sqlalchemy.orm import Session

router = APIRouter(prefix="/workspaces/{workspace_id}/capabilities", tags=["capabilities"])


@router.post("/attention", response_model=AttentionDigest)
def attention(ctx: WorkspaceContext = Depends(get_workspace_context), db: Session = Depends(get_db),
              tools: ToolRegistry = Depends(get_tool_registry),
              policy: Callable[[str], WorkspacePolicy] = Depends(request_policy_provider)) -> AttentionDigest:
    return AttentionService(ToolExecutionService(db, tools, policy_provider=policy)).digest(ctx.principal())


@router.post("/opportunities", response_model=OpportunityList)
def opportunities(ctx: WorkspaceContext = Depends(get_workspace_context), db: Session = Depends(get_db),
                  tools: ToolRegistry = Depends(get_tool_registry),
              policy: Callable[[str], WorkspacePolicy] = Depends(request_policy_provider)) -> OpportunityList:
    return OpportunityService(ToolExecutionService(db, tools, policy_provider=policy)).list(ctx.principal())


@router.post("/changes", response_model=WeeklyChanges)
def changes(ctx: WorkspaceContext = Depends(get_workspace_context), db: Session = Depends(get_db),
            tools: ToolRegistry = Depends(get_tool_registry),
              policy: Callable[[str], WorkspacePolicy] = Depends(request_policy_provider)) -> WeeklyChanges:
    return ChangesService(ToolExecutionService(db, tools, policy_provider=policy)).report(ctx.principal())


@router.post("/meetings", response_model=MeetingBriefing)
def meetings(ctx: WorkspaceContext = Depends(get_workspace_context), db: Session = Depends(get_db),
             tools: ToolRegistry = Depends(get_tool_registry),
              policy: Callable[[str], WorkspacePolicy] = Depends(request_policy_provider)) -> MeetingBriefing:
    return MeetingService(ToolExecutionService(db, tools, policy_provider=policy)).brief(ctx.principal())
