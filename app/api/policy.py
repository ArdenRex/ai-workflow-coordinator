"""Workspace policy endpoints (Step 12.1). Humans only (the signed-in user acting as themselves); admin and owner via `policy:*`.

GET /workspaces/{id}/policy   the effective policy (the baseline, version 0, when nothing is stored).
PUT /workspaces/{id}/policy   replace it; body carries `expected_version` (0 for the first write). 409 on a stale version.
The policy can only tighten: disable tools or force approval. Levels 4 and 5 are refused until they can be enforced. Errors are fixed
text and never echo the input.
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.ai import get_tool_registry
from app.database import get_db
from app.identity.context import WorkspaceContext, require_permission
from app.kernel.policy_store import DEFAULT_LEVEL, AutonomyLevel, PolicyError, PolicyService, to_workspace_policy
from app.kernel.registry import ToolRegistry
from app.models.policy import WorkspacePolicyRecord

router = APIRouter(prefix="/workspaces/{workspace_id}/policy", tags=["policy"])


class PolicyView(BaseModel):
    workspace_id: str
    version: int
    is_default: bool
    autonomy_level: int
    autonomy_name: str
    disabled_tools: List[str]
    approval_required_tools: List[str]
    risk_overrides: Dict[str, str]
    execution_limit: Optional[Dict[str, int]] = None
    escalation: Optional[Dict[str, int]] = None
    approval_routing: Dict[str, str] = {}
    auto_execute_tools: List[str] = []
    auto_execute_max_risk: str
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None


def view(workspace_id: str, rec: Optional[WorkspacePolicyRecord]) -> PolicyView:
    pol = to_workspace_policy(rec)
    level = AutonomyLevel(rec.autonomy_level) if rec else DEFAULT_LEVEL
    return PolicyView(workspace_id=workspace_id, version=rec.version if rec else 0, is_default=rec is None, autonomy_level=int(level),
                      autonomy_name=level.name.lower(), disabled_tools=sorted(pol.disabled_tools),
                      approval_required_tools=sorted(pol.approval_required_tools),
                      risk_overrides={k: v.value for k, v in sorted(pol.risk_overrides.items())}, auto_execute_max_risk=pol.auto_execute_max_risk.value,
                      execution_limit=({"max_executions": pol.execution_limit.max_executions, "window_seconds": pol.execution_limit.window_seconds}
                                       if pol.execution_limit else None),
                      auto_execute_tools=sorted(pol.auto_execute_tools),
                      approval_routing=dict(sorted(pol.approval_routing.items())),
                      escalation=({"threshold": pol.escalation.threshold, "window_seconds": pol.escalation.window_seconds}
                                  if pol.escalation else None),
                      updated_at=rec.updated_at.isoformat() if rec else None, updated_by=rec.updated_by if rec else None)


@router.get("", response_model=PolicyView)
def get_policy(ctx: WorkspaceContext = Depends(require_permission("policy:read")), db: Session = Depends(get_db),
               tools: ToolRegistry = Depends(get_tool_registry)) -> PolicyView:
    return view(ctx.workspace.id, PolicyService(db, tools).get(ctx.workspace.id))


@router.put("", response_model=PolicyView)
def put_policy(body: Dict[str, Any], ctx: WorkspaceContext = Depends(require_permission("policy:update")),
               db: Session = Depends(get_db), tools: ToolRegistry = Depends(get_tool_registry)) -> PolicyView:
    try:
        return view(ctx.workspace.id, PolicyService(db, tools).set(ctx.principal(), body))
    except PolicyError as exc:
        raise HTTPException(exc.http, {"code": exc.code, "message": exc.message})
