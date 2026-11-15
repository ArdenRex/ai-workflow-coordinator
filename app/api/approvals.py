"""Approval inbox and workspace activity (Step F4). Thin: every rule lives in ApprovalService.

GET  /workspaces/{id}/approvals               list approvals, newest first (?status=PENDING|APPROVED|REJECTED|EXPIRED|EXECUTED).
GET  /workspaces/{id}/approvals/{approval_id} one approval; the tool input is shown only to people who can decide.
POST /workspaces/{id}/approvals/{approval_id}/approve | /reject   decide (needs approval:decide; never the requester; never an agent).
GET  /workspaces/{id}/activity                the workspace audit trail (needs audit:read), fixed fields only.

People who cannot decide see only approvals they requested themselves, without the tool input. Another workspace's
rows are never reachable (a plain 404). Deciding does not run anything: the run or plan that asked continues from
its own screen, and the kernel re-checks the approval and the exact approved input before it acts.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.identity.context import WorkspaceContext, get_workspace_context, require_permission
from app.kernel import errors as ke
from app.kernel.approvals import DECIDE_PERMISSION, ApprovalService
from app.kernel.policy_store import session_policy_provider
from app.models.enums import ApprovalStatus
from app.models.kernel import Approval, SystemEvent, ToolExecution

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["approvals"])

_SAFE_PAYLOAD_KEYS = ("tool_id", "risk", "reason", "policy", "agent", "approval_id")   # codes and ids only, never content


class ApprovalView(BaseModel):
    id: str
    execution_id: str
    status: ApprovalStatus
    tool_id: str
    risk: str
    agent: Optional[str]
    requested_by: str
    decided_by: Optional[str]
    decided_at: Optional[datetime]
    reason: Optional[str]
    expires_at: Optional[datetime]
    created_at: datetime
    can_decide: bool
    input: Optional[Dict[str, Any]] = None


class DecideRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Optional[str] = Field(default=None, max_length=500)


class ActivityEvent(BaseModel):
    id: str
    event_type: str
    actor: Optional[str]
    execution_id: Optional[str]
    created_at: datetime
    details: Dict[str, Any]


def _view(a: Approval, ex: ToolExecution, ctx: WorkspaceContext, *, with_input: bool) -> ApprovalView:
    can = ctx.principal().can(DECIDE_PERMISSION) and ctx.user.id != a.requested_by and a.status == ApprovalStatus.PENDING
    return ApprovalView(
        id=a.id, execution_id=a.execution_id, status=a.status, tool_id=ex.tool_id, risk=ex.risk_level.value,
        agent=ex.agent, requested_by=a.requested_by, decided_by=a.decided_by, decided_at=a.decided_at,
        reason=a.reason, expires_at=a.expires_at, created_at=a.created_at, can_decide=can,
        input=ex.input if with_input else None)


def _http(exc: ke.KernelError) -> HTTPException:
    """Fixed client-facing text; the audit trail holds the detail."""
    if isinstance(exc, ke.ApprovalNotFoundError):
        return HTTPException(404, "Approval not found")
    if isinstance(exc, ke.ApprovalPermissionError):
        return HTTPException(403, "You cannot decide this approval")
    if isinstance(exc, ke.ApprovalExpiredError):
        return HTTPException(409, "This approval has expired")
    if isinstance(exc, ke.ApprovalStateError):
        return HTTPException(409, "This approval has already been decided")
    return HTTPException(400, "The approval could not be processed")


def _service(db: Session, ctx: WorkspaceContext) -> ApprovalService:
    return ApprovalService(db, policy_provider=session_policy_provider(db))


def _load(db: Session, ctx: WorkspaceContext, approval_id: str) -> tuple:
    row = db.execute(select(Approval, ToolExecution).join(ToolExecution, ToolExecution.id == Approval.execution_id)
                     .where(Approval.id == approval_id, Approval.workspace_id == ctx.workspace.id,
                            ToolExecution.workspace_id == ctx.workspace.id)).first()
    if row is None or (not ctx.principal().can(DECIDE_PERMISSION) and row[0].requested_by != ctx.user.id):
        raise HTTPException(404, "Approval not found")
    return row


@router.get("/approvals", response_model=List[ApprovalView])
def list_approvals(status: Optional[ApprovalStatus] = None, limit: int = Query(50, ge=1, le=200),
                   ctx: WorkspaceContext = Depends(get_workspace_context), db: Session = Depends(get_db)):
    deciders = ctx.principal().can(DECIDE_PERMISSION)
    if deciders:
        _service(db, ctx).expire_stale(ctx.workspace.id)           # an overdue approval never shows as pending
    q = (select(Approval, ToolExecution).join(ToolExecution, ToolExecution.id == Approval.execution_id)
         .where(Approval.workspace_id == ctx.workspace.id, ToolExecution.workspace_id == ctx.workspace.id))
    if not deciders:
        q = q.where(Approval.requested_by == ctx.user.id)
    if status is not None:
        q = q.where(Approval.status == status)
    rows = db.execute(q.order_by(Approval.created_at.desc(), Approval.id).limit(limit)).all()
    return [_view(a, ex, ctx, with_input=deciders) for a, ex in rows]


@router.get("/approvals/{approval_id}", response_model=ApprovalView)
def get_approval(approval_id: str, ctx: WorkspaceContext = Depends(get_workspace_context), db: Session = Depends(get_db)):
    a, ex = _load(db, ctx, approval_id)
    return _view(a, ex, ctx, with_input=ctx.principal().can(DECIDE_PERMISSION))


def _decide(approval_id: str, body: DecideRequest, ctx: WorkspaceContext, db: Session, approve: bool) -> ApprovalView:
    _load(db, ctx, approval_id)                                    # 404 first for anything the caller may not see
    try:
        a = _service(db, ctx).decide(approval_id, ctx.principal(), approve=approve, reason=(body.reason or None))
    except ke.KernelError as exc:
        raise _http(exc)
    ex = db.get(ToolExecution, a.execution_id)
    return _view(a, ex, ctx, with_input=True)


@router.post("/approvals/{approval_id}/approve", response_model=ApprovalView)
def approve(approval_id: str, body: DecideRequest = DecideRequest(), ctx: WorkspaceContext = Depends(get_workspace_context),
            db: Session = Depends(get_db)):
    return _decide(approval_id, body, ctx, db, True)


@router.post("/approvals/{approval_id}/reject", response_model=ApprovalView)
def reject(approval_id: str, body: DecideRequest = DecideRequest(), ctx: WorkspaceContext = Depends(get_workspace_context),
           db: Session = Depends(get_db)):
    return _decide(approval_id, body, ctx, db, False)


@router.get("/activity", response_model=List[ActivityEvent])
def activity(limit: int = Query(50, ge=1, le=200), event_type: Optional[str] = Query(None, max_length=64),
             ctx: WorkspaceContext = Depends(require_permission("audit:read")), db: Session = Depends(get_db)):
    q = select(SystemEvent).where(SystemEvent.workspace_id == ctx.workspace.id)
    if event_type:
        q = q.where(SystemEvent.event_type == event_type)
    rows = db.scalars(q.order_by(SystemEvent.created_at.desc(), SystemEvent.id).limit(limit))
    return [ActivityEvent(id=e.id, event_type=e.event_type, actor=e.actor, execution_id=e.execution_id, created_at=e.created_at,
                          details={k: (e.payload or {}).get(k) for k in _SAFE_PAYLOAD_KEYS
                                   if isinstance((e.payload or {}).get(k), (str, int, bool))})
            for e in rows]
