"""
routers/messages.py
────────────────────
POST /process-message  →  AI extracts task  →  saves to DB  →  returns result

Auth required: tasks are stamped with the current user's owner_id and workspace_id
so they are isolated per user/workspace and never leak to other accounts.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import crud
from app.ai_extractor import extract_task_from_message
from app.auth import get_current_user
from app.database import get_db
from app.models import User
from app.schemas import MessageRequest, ProcessMessageResponse

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/process-message",
    tags=["Messages"],
)


@router.post(
    "",
    response_model=ProcessMessageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Process a Slack/email message with AI",
    description=(
        "Send a raw message. The AI extracts the task, assignee, deadline, and priority, "
        "then stores it in the database under the authenticated user's workspace."
    ),
)
async def process_message(
    payload: MessageRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProcessMessageResponse:
    """
    Full pipeline: raw message → AI extraction → DB persist → response.
    Tasks are always stamped with owner_id and workspace_id from the
    authenticated user so they never leak across accounts.
    """

    # ── Step 1: AI extraction ─────────────────────────────────────────────────
    try:
        extracted = await extract_task_from_message(payload.message)
    except ValueError as exc:
        logger.warning("AI extraction validation error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"AI extraction failed: {exc}",
        ) from exc
    except Exception as exc:
        logger.exception("Unexpected error during AI extraction: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected error during task extraction.",
        ) from exc

    # ── Step 2: Persist to database (stamped with current user) ──────────────
    try:
        task = crud.create_task(
            db=db,
            source_message=payload.message,
            extracted=extracted,
            owner_id=current_user.id,                  # ← locks task to this user
            workspace_id=current_user.workspace_id,    # ← locks task to this workspace
        )
    except SQLAlchemyError as exc:
        logger.exception("Database error saving task: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database error. Task could not be saved.",
        ) from exc
    except Exception as exc:
        logger.exception("Unexpected error saving task: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected error saving task.",
        ) from exc

    logger.info(
        "Task #%d created — owner_id=%d workspace_id=%s assignee=%r priority=%s",
        task.id, current_user.id, current_user.workspace_id,
        task.assignee, task.priority,
    )

    return ProcessMessageResponse(
        message="Task extracted and saved successfully.",
        extracted=extracted,
        task=task,
    )
