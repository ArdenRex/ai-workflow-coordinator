"""
app/routers/viral.py
────────────────────
Segment 6 — Viral onboarding by design.

Endpoints:
    GET  /viral/stats          — workspace social-proof metrics (tasks this month, active members, etc.)
    POST /viral/invite/claim   — unregistered user clicks their invite link → redirect to signup
    GET  /viral/invite/{token} — resolve an invite token to workspace + task context
"""

import logging
import os
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import User, UserRole
from app.routers.auth import get_current_user
from app import crud
from app.schemas import WorkspaceStatsResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/viral", tags=["Viral Onboarding"])

FRONTEND_URL = os.getenv("FRONTEND_URL", "").rstrip("/")


# ── DB dependency ─────────────────────────────────────────────────────────────

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


DB   = Annotated[Session, Depends(get_db)]
Auth = Annotated[User,    Depends(get_current_user)]


# ── GET /viral/stats ──────────────────────────────────────────────────────────

@router.get(
    "/stats",
    response_model=WorkspaceStatsResponse,
    summary="Get workspace social-proof metrics",
)
def get_workspace_stats(current_user: Auth, db: DB) -> WorkspaceStatsResponse:
    """
    Returns social-proof metrics for the current user's workspace:
    tasks created this month, active members, top assignee, completion rate.
    Used by the Dashboard to show the social-proof widget.
    """
    if not current_user.workspace_id:
        return WorkspaceStatsResponse(
            tasks_this_month=0,
            total_tasks=0,
            active_members=0,
        )

    stats = crud.get_workspace_stats(db, current_user.workspace_id)
    return WorkspaceStatsResponse(**stats)


# ── GET /viral/invite/{token} ─────────────────────────────────────────────────

@router.get(
    "/invite/{token}",
    summary="Resolve an invite token",
)
def resolve_invite(token: str, db: DB):
    """
    Looks up a pending invite by token.
    Returns workspace name + task title so the signup page can show context.
    Called by the frontend signup page when an invite link is opened.
    """
    from app.models import PendingInvite
    from sqlalchemy import select

    stmt = select(PendingInvite).where(PendingInvite.invite_token == token.strip())
    invite = db.scalars(stmt).first()

    if not invite:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invite link is invalid or has already been used.",
        )

    workspace = crud.get_workspace_by_id(db, invite.workspace_id)
    task      = crud.get_task(db, invite.task_id) if invite.task_id else None

    return {
        "token":          token,
        "assignee_name":  invite.assignee_name,
        "workspace_name": workspace.name if workspace else "your team",
        "task_title":     task.title if task else None,
        "workspace_id":   invite.workspace_id,
    }
