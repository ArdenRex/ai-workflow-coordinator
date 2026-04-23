"""
routers/workspace_settings.py
──────────────────────────────
Segment 2: API endpoints for workspace priority/urgency settings.

Endpoints:
  GET    /workspace/settings          — get current workspace's settings
  PUT    /workspace/settings          — create or update settings
  POST   /workspace/settings/preview  — preview how rules would affect a message
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import Priority, User, UserRole, WorkspaceSettings
from app.priority_engine import apply_priority_rules
from app.schemas import (
    WorkspaceSettingsResponse,
    WorkspaceSettingsUpdate,
    PriorityPreviewRequest,
    PriorityPreviewResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/workspace", tags=["Workspace Settings"])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _require_architect(current_user: User) -> None:
    """Only architects (managers) can change workspace settings."""
    if current_user.role != UserRole.architect:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only workspace architects (managers) can change these settings.",
        )


def _get_or_create_settings(db: Session, workspace_id: int) -> WorkspaceSettings:
    """Fetch existing settings row or create a default one."""
    settings = (
        db.query(WorkspaceSettings)
        .filter_by(workspace_id=workspace_id)
        .first()
    )
    if not settings:
        settings = WorkspaceSettings(
            workspace_id=workspace_id,
            keyword_rules=[],
            high_priority_channels=[],
            drift_alert_hours=24,
        )
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get(
    "/settings",
    response_model=WorkspaceSettingsResponse,
    summary="Get workspace priority/urgency settings",
)
def get_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Returns the current workspace's priority engine settings.
    All authenticated users can view settings.
    """
    if not current_user.workspace_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You are not part of a workspace yet. Complete onboarding first.",
        )

    settings = _get_or_create_settings(db, current_user.workspace_id)
    return settings


@router.put(
    "/settings",
    response_model=WorkspaceSettingsResponse,
    summary="Update workspace priority/urgency settings",
)
def update_settings(
    payload: WorkspaceSettingsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Create or update workspace priority/urgency rules.
    **Only architects (managers) can call this.**

    - `keyword_rules`: list of `{keyword, priority}` objects
    - `high_priority_channels`: list of Slack channel IDs
    - `drift_alert_hours`: hours before drift alert fires (min 1, max 168)
    """
    if not current_user.workspace_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You are not part of a workspace yet.",
        )

    _require_architect(current_user)

    settings = _get_or_create_settings(db, current_user.workspace_id)

    if payload.keyword_rules is not None:
        # Validate each rule has keyword + valid priority
        validated_rules = []
        for rule in payload.keyword_rules:
            kw = str(rule.get("keyword", "")).strip()
            pr = str(rule.get("priority", "")).lower().strip()
            if not kw:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"keyword_rules: each rule must have a non-empty 'keyword'. Got: {rule}",
                )
            valid_priorities = {p.value for p in Priority}
            if pr not in valid_priorities:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"keyword_rules: '{pr}' is not a valid priority. Choose from: {sorted(valid_priorities)}",
                )
            validated_rules.append({"keyword": kw, "priority": pr})
        settings.keyword_rules = validated_rules

    if payload.high_priority_channels is not None:
        # Strip whitespace and deduplicate
        settings.high_priority_channels = list(
            {ch.strip() for ch in payload.high_priority_channels if ch.strip()}
        )

    if payload.drift_alert_hours is not None:
        hours = max(1, min(168, payload.drift_alert_hours))  # clamp 1h–7d
        settings.drift_alert_hours = hours

    try:
        db.commit()
        db.refresh(settings)
    except Exception as exc:
        db.rollback()
        logger.error("Error saving workspace settings: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save settings. Please try again.",
        )

    logger.info(
        "Workspace %d settings updated by user %d",
        current_user.workspace_id,
        current_user.id,
    )
    return settings


@router.post(
    "/settings/preview",
    response_model=PriorityPreviewResponse,
    summary="Preview how rules would affect a message",
)
def preview_priority(
    payload: PriorityPreviewRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Test how the priority engine would classify a given message.
    Useful for testing your keyword rules before saving.

    Pass any message text and optionally a Slack channel ID.
    Returns the final priority and an explanation of why.
    """
    if not current_user.workspace_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You are not part of a workspace yet.",
        )

    settings = _get_or_create_settings(db, current_user.workspace_id)

    base_priority = payload.base_priority or Priority.medium
    urgency = payload.urgency or "medium"

    final_priority = apply_priority_rules(
        message=payload.message,
        base_priority=base_priority,
        urgency=urgency,
        slack_channel_id=payload.slack_channel_id,
        settings=settings,
    )

    # Build explanation
    boosted = final_priority != base_priority
    explanation = (
        f"Priority would be set to '{final_priority.value}'."
    )
    if boosted:
        explanation = (
            f"Priority boosted from '{base_priority.value}' → '{final_priority.value}' "
            f"by workspace rules."
        )

    return PriorityPreviewResponse(
        base_priority=base_priority,
        final_priority=final_priority,
        boosted=boosted,
        explanation=explanation,
    )
