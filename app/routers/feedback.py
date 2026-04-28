"""
routers/feedback.py
────────────────────
POST  /feedback        →  submit feedback / bug / feature request
GET   /feedback        →  list all submissions (architect only)
PATCH /feedback/{id}   →  update status (architect only)
"""

import logging
import os
import threading
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Feedback, FeedbackStatus, FeedbackType

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/feedback",
    tags=["Feedback"],
)

# ── Resend config (optional — if not set, email is skipped silently) ──────────
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
ALERT_EMAIL    = os.getenv("FEEDBACK_ALERT_EMAIL", "")
FROM_EMAIL     = os.getenv("FEEDBACK_FROM_EMAIL", "AI Workflow <onboarding@resend.dev>")


# ── Schemas ───────────────────────────────────────────────────────────────────

class FeedbackCreate(BaseModel):
    type: FeedbackType
    title: str = Field(..., min_length=3, max_length=255)
    message: str = Field(..., min_length=10, max_length=5000)
    page_context: Optional[str] = Field(None, max_length=128)
    user_id: Optional[int] = None
    user_email: Optional[str] = None
    user_name: Optional[str] = None


class FeedbackStatusUpdate(BaseModel):
    status: FeedbackStatus


class FeedbackOut(BaseModel):
    id: int
    type: FeedbackType
    title: str
    message: str
    page_context: Optional[str]
    user_email: Optional[str]
    user_name: Optional[str]
    status: FeedbackStatus
    created_at: str

    class Config:
        from_attributes = True


# ── Email helper ──────────────────────────────────────────────────────────────

TYPE_EMOJI = {
    "bug":             "🐛",
    "feedback":        "💬",
    "feature_request": "✨",
}

TYPE_LABEL = {
    "bug":             "Bug Report",
    "feedback":        "General Feedback",
    "feature_request": "Feature Request",
}


def _send_alert_email(fb: Feedback) -> None:
    """Send email alert via Resend API in a background thread. Fails silently."""
    if not RESEND_API_KEY or not ALERT_EMAIL:
        logger.info("Resend not configured — skipping feedback alert email.")
        return

    def _send():
        try:
            emoji = TYPE_EMOJI.get(str(fb.type).split(".")[-1], "📩")
            label = TYPE_LABEL.get(str(fb.type).split(".")[-1], str(fb.type))
            from_  = fb.user_name or fb.user_email or "Anonymous"
            subject = f"{emoji} [{label}] {fb.title}"

            html_body = f"""
            <html><body style="font-family: sans-serif; background:#f5f5f5; padding:24px;">
              <div style="max-width:600px; margin:0 auto; background:#fff; border-radius:10px; overflow:hidden; box-shadow:0 2px 8px rgba(0,0,0,0.1);">
                <div style="background:#1e293b; padding:20px 24px; color:#fff;">
                  <h2 style="margin:0; font-size:18px;">{emoji} New {label}</h2>
                  <p style="margin:4px 0 0; opacity:0.6; font-size:13px;">AI Workflow Coordinator</p>
                </div>
                <div style="padding:24px;">
                  <table style="width:100%; border-collapse:collapse; font-size:14px;">
                    <tr><td style="padding:8px 0; color:#64748b; width:120px;">From</td><td style="padding:8px 0; font-weight:600;">{from_}</td></tr>
                    <tr><td style="padding:8px 0; color:#64748b;">Email</td><td style="padding:8px 0;">{fb.user_email or "—"}</td></tr>
                    <tr><td style="padding:8px 0; color:#64748b;">Type</td><td style="padding:8px 0;">{label}</td></tr>
                    <tr><td style="padding:8px 0; color:#64748b;">Page</td><td style="padding:8px 0;">{fb.page_context or "—"}</td></tr>
                    <tr><td style="padding:8px 0; color:#64748b;">Title</td><td style="padding:8px 0; font-weight:600;">{fb.title}</td></tr>
                  </table>
                  <div style="margin-top:16px; padding:16px; background:#f8fafc; border-radius:8px; border-left:3px solid #3b82f6;">
                    <p style="margin:0; font-size:14px; line-height:1.6; color:#1e293b;">{fb.message}</p>
                  </div>
                  <p style="margin-top:16px; font-size:12px; color:#94a3b8;">Submitted at {fb.created_at} · ID #{fb.id}</p>
                </div>
              </div>
            </body></html>
            """

            response = httpx.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {RESEND_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "from":    FROM_EMAIL,
                    "to":      [ALERT_EMAIL],
                    "subject": subject,
                    "html":    html_body,
                },
                timeout=10,
            )

            if response.status_code == 200 or response.status_code == 201:
                logger.info("Feedback alert email sent via Resend for feedback id=%d", fb.id)
            else:
                logger.warning("Resend returned %d: %s", response.status_code, response.text)

        except Exception as exc:
            logger.warning("Failed to send feedback alert email: %s", exc)

    # Run in background thread so it never blocks the API response
    threading.Thread(target=_send, daemon=True).start()


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post(
    "",
    status_code=http_status.HTTP_201_CREATED,
    summary="Submit feedback, bug report, or feature request",
)
def submit_feedback(
    payload: FeedbackCreate,
    db: Session = Depends(get_db),
) -> dict:
    try:
        fb = Feedback(
            type         = payload.type,
            title        = payload.title,
            message      = payload.message,
            page_context = payload.page_context,
            user_id      = payload.user_id,
            user_email   = payload.user_email,
            user_name    = payload.user_name,
            status       = FeedbackStatus.new,
        )
        db.add(fb)
        db.commit()
        db.refresh(fb)
        logger.info("Feedback submitted id=%d type=%s by=%s", fb.id, fb.type, fb.user_email)
    except SQLAlchemyError as exc:
        db.rollback()
        logger.exception("DB error saving feedback: %s", exc)
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database error. Please retry.",
        ) from exc

    # Fire-and-forget email alert (background thread, never blocks)
    _send_alert_email(fb)

    return {
        "id":      fb.id,
        "status":  fb.status,
        "message": "Thank you! Your feedback has been received.",
    }


@router.get(
    "",
    summary="List all feedback submissions (admin only)",
)
def list_feedback(
    type:   Optional[FeedbackType]   = Query(default=None),
    status: Optional[FeedbackStatus] = Query(default=None),
    skip:   int = Query(default=0, ge=0),
    limit:  int = Query(default=50, ge=1, le=200),
    db:     Session = Depends(get_db),
) -> dict:
    try:
        q = db.query(Feedback)
        if type:
            q = q.filter(Feedback.type == type)
        if status:
            q = q.filter(Feedback.status == status)
        total = q.count()
        items = q.order_by(Feedback.created_at.desc()).offset(skip).limit(limit).all()
    except SQLAlchemyError as exc:
        logger.exception("DB error listing feedback: %s", exc)
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database error. Please retry.",
        ) from exc

    return {
        "total": total,
        "skip":  skip,
        "limit": limit,
        "items": [
            {
                "id":           f.id,
                "type":         f.type,
                "title":        f.title,
                "message":      f.message,
                "page_context": f.page_context,
                "user_email":   f.user_email,
                "user_name":    f.user_name,
                "status":       f.status,
                "created_at":   f.created_at.isoformat() if f.created_at else None,
            }
            for f in items
        ],
    }


@router.patch(
    "/{feedback_id}",
    summary="Update feedback status (admin only)",
)
def update_feedback_status(
    feedback_id: int,
    update: FeedbackStatusUpdate,
    db: Session = Depends(get_db),
) -> dict:
    try:
        fb = db.query(Feedback).filter(Feedback.id == feedback_id).first()
        if not fb:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Feedback #{feedback_id} not found.",
            )
        fb.status = update.status
        db.commit()
        db.refresh(fb)
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        logger.exception("DB error updating feedback %d: %s", feedback_id, exc)
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database error. Please retry.",
        ) from exc

    return {"id": fb.id, "status": fb.status}
