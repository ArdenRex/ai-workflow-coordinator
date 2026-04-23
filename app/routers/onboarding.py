"""
app/routers/onboarding.py
──────────────────────────
Segment 7 — Auto-onboarding checklist (in-app guided tour).

Endpoints
─────────
GET  /onboarding/progress   → fetch current user's checklist state
POST /onboarding/step       → mark a single step complete
POST /onboarding/reset      → (dev/testing) reset checklist for current user

Steps
─────
1. slack_connected      — auto-marked when user completes Slack OAuth (auth.py)
2. first_command_sent   — call from slack_bot.py after first task created
3. dashboard_viewed     — frontend calls POST /onboarding/step on dashboard load
4. teammate_invited     — frontend calls POST /onboarding/step after invite sent

Frontend integration
────────────────────
- Call GET /onboarding/progress on every dashboard load.
- Render a progress bar using steps_completed / total_steps.
- Hide the checklist banner when is_completed == true.
- Show "You're done. You own who-owns-what now." on completion.
"""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import get_current_user          # real JWT dependency
from app.database import get_db
from app.models import OnboardingProgress, User
from app.schemas import OnboardingProgressResponse, OnboardingStepUpdate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/onboarding", tags=["Onboarding"])


# ── Step maps ─────────────────────────────────────────────────────────────────

_STEP_FLAG_MAP: dict[str, str] = {
    "slack_connected":    "slack_connected",
    "first_command_sent": "first_command_sent",
    "dashboard_viewed":   "dashboard_viewed",
    "teammate_invited":   "teammate_invited",
}

_STEP_TIMESTAMP_MAP: dict[str, str] = {
    "slack_connected":    "slack_connected_at",
    "first_command_sent": "first_command_sent_at",
    "dashboard_viewed":   "dashboard_viewed_at",
    "teammate_invited":   "teammate_invited_at",
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _get_or_create_progress(db: Session, user: User) -> OnboardingProgress:
    """Return the user's OnboardingProgress row, creating it if missing."""
    progress = db.query(OnboardingProgress).filter_by(user_id=user.id).first()
    if not progress:
        progress = OnboardingProgress(user_id=user.id)
        db.add(progress)
        db.commit()
        db.refresh(progress)
        logger.info("Created OnboardingProgress for user_id=%s", user.id)
    return progress


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get(
    "/progress",
    response_model=OnboardingProgressResponse,
    summary="Get onboarding checklist progress",
    description=(
        "Returns the current user's 4-step onboarding checklist state. "
        "Auto-creates a progress record on first call. "
        "Use steps_completed / total_steps to render the progress bar."
    ),
)
def get_progress(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    progress = _get_or_create_progress(db, current_user)
    return progress


@router.post(
    "/step",
    response_model=OnboardingProgressResponse,
    summary="Mark an onboarding step complete",
    description=(
        "Marks a single checklist step as complete for the current user. "
        "Idempotent — calling it again for an already-completed step is a no-op. "
        "Auto-marks the whole checklist complete when all 4 steps are done."
    ),
)
def complete_step(
    payload: OnboardingStepUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    progress = _get_or_create_progress(db, current_user)

    flag_attr = _STEP_FLAG_MAP[payload.step]
    ts_attr   = _STEP_TIMESTAMP_MAP[payload.step]

    if getattr(progress, flag_attr):
        # Already done — no-op
        logger.debug(
            "Step %r already complete for user_id=%s — no-op",
            payload.step, current_user.id,
        )
        return progress

    setattr(progress, flag_attr, True)
    setattr(progress, ts_attr, datetime.utcnow())
    progress.mark_complete_if_done()

    db.commit()
    db.refresh(progress)

    logger.info(
        "Onboarding step %r completed for user_id=%s | progress=%s/%s | done=%s",
        payload.step, current_user.id,
        progress.steps_completed, progress.total_steps,
        progress.is_completed,
    )

    return progress


@router.post(
    "/reset",
    response_model=OnboardingProgressResponse,
    summary="Reset onboarding checklist (dev/testing only)",
    description="Resets all onboarding steps. Remove or guard with an admin check in production.",
)
def reset_progress(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    progress = _get_or_create_progress(db, current_user)

    progress.slack_connected       = False
    progress.slack_connected_at    = None
    progress.first_command_sent    = False
    progress.first_command_sent_at = None
    progress.dashboard_viewed      = False
    progress.dashboard_viewed_at   = None
    progress.teammate_invited      = False
    progress.teammate_invited_at   = None
    progress.is_completed          = False
    progress.completed_at          = None

    db.commit()
    db.refresh(progress)

    logger.info("Onboarding progress reset for user_id=%s", current_user.id)
    return progress


# ── Internal helper (called from other modules) ───────────────────────────────

def mark_step_for_user(db: Session, user_id: int, step: str) -> None:
    """
    Fire-and-forget helper — mark a step without going through HTTP.

    Called from:
      - auth.py  → mark_step_for_user(db, user.id, "slack_connected")
      - slack_bot.py → mark_step_for_user(db, user.id, "first_command_sent")

    Valid steps:
        slack_connected | first_command_sent | dashboard_viewed | teammate_invited
    """
    if step not in _STEP_FLAG_MAP:
        logger.warning("mark_step_for_user: unknown step %r — ignoring", step)
        return

    progress = db.query(OnboardingProgress).filter_by(user_id=user_id).first()
    if not progress:
        progress = OnboardingProgress(user_id=user_id)
        db.add(progress)

    flag_attr = _STEP_FLAG_MAP[step]
    ts_attr   = _STEP_TIMESTAMP_MAP[step]

    if getattr(progress, flag_attr):
        return  # already done

    setattr(progress, flag_attr, True)
    setattr(progress, ts_attr, datetime.utcnow())
    progress.mark_complete_if_done()

    db.commit()
    logger.info(
        "mark_step_for_user: step=%r user_id=%s progress=%s/%s",
        step, user_id, progress.steps_completed, progress.total_steps,
    )
