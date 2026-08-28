"""
routers/email.py
─────────────────────────────────────────────────────────────────────────────
Receives inbound email from SendGrid's Inbound Parse webhook and hands it
off to email_bot.process_inbound_email() for AI task extraction.

Setup (SendGrid side):
  1. Own a domain/subdomain (e.g. tasks.yourdomain.com) and point its MX
     record at SendGrid per their Inbound Parse docs.
  2. In SendGrid → Settings → Inbound Parse, add that hostname and set the
     destination URL to:
       https://<your-backend>/email/inbound?token=<EMAIL_INBOUND_SECRET>
  3. Set EMAIL_INBOUND_SECRET in your .env to any random string — this
     endpoint rejects requests whose ?token= doesn't match, so random
     internet traffic can't post fake tasks. Leave it blank only for local
     testing.

SendGrid POSTs multipart/form-data with fields including "from", "subject",
"text" (plain body) and "html" — we only need the first three.
"""
import logging

from fastapi import APIRouter, Form, HTTPException, Request, status
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.email_bot import process_inbound_email

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Email"])


@router.post(
    "/email/inbound",
    status_code=200,
    summary="SendGrid Inbound Parse webhook",
    include_in_schema=True,
)
async def email_inbound(
    request: Request,
    sender: str = Form("", alias="from"),
    subject: str = Form(""),
    text: str = Form(""),
):
    """
    Receives a parsed inbound email from SendGrid and creates a task from it
    (if the AI extractor detects one). Always returns 200 to SendGrid unless
    the security token is missing/invalid, so SendGrid doesn't treat a
    "no task found" outcome as a delivery failure and retry.
    """
    settings = get_settings()

    if settings.email_inbound_secret:
        token = request.query_params.get("token", "")
        if token != settings.email_inbound_secret:
            logger.warning("Inbound email webhook called with invalid/missing token")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token.")

    logger.info("Inbound email received | from=%s | subject=%r", sender, subject[:80])

    try:
        task = await process_inbound_email(raw_from=sender, subject=subject, body_text=text)
    except Exception as exc:
        # Log but still return 200 — a bug in extraction shouldn't cause
        # SendGrid to keep retrying the same email indefinitely.
        logger.error("Unhandled error processing inbound email: %s", exc, exc_info=True)
        return JSONResponse({"status": "error_logged"}, status_code=200)

    if task:
        return JSONResponse({"status": "task_created", "task_id": task.id}, status_code=200)
    return JSONResponse({"status": "no_task_detected"}, status_code=200)
