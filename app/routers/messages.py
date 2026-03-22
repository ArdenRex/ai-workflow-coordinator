"""
routers/messages.py
────────────────────
POST /process-message  →  AI extracts task  →  saves to DB  →  returns result
"""

import logging

import openai
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import crud
from app.ai_extractor import extract_task_from_message
from app.database import get_db
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
        "then stores it in the database."
    ),
)
async def process_message(
    payload: MessageRequest,
    db: Session = Depends(get_db),
) -> ProcessMessageResponse:
    """
    Full pipeline: raw message → AI extraction → DB persist → response.
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
    except openai.RateLimitError as exc:
        logger.error("OpenAI rate limit hit: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="AI service is rate-limited. Please retry shortly.",
        ) from exc
    except openai.AuthenticationError as exc:
        logger.critical("OpenAI authentication error — check API key: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI service authentication failure.",
        ) from exc
    except openai.APITimeoutError as exc:
        logger.error("OpenAI request timed out: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="AI service timed out. Please retry.",
        ) from exc
    except openai.APIError as exc:
        logger.exception("OpenAI API error during extraction: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI service error. Please retry later.",
        ) from exc
    except Exception as exc:
        logger.exception("Unexpected error during AI extraction: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected error during task extraction.",
        ) from exc

    # ── Step 2: Persist to database ───────────────────────────────────────────
    try:
        task = crud.create_task(
            db=db,
            source_message=payload.message,
            extracted=extracted,
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
        "Task #%d created — assignee=%r priority=%s source=%s",
        task.id, task.assignee, task.priority, payload.source,
    )

    return ProcessMessageResponse(
        message="Task extracted and saved successfully.",
        extracted=extracted,
        task=task,
    )
