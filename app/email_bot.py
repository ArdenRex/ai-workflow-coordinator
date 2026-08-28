"""
email_bot.py
------------
Email integration — the email equivalent of slack_bot.py.

Flow:
  1. A user sends/forwards an email to the workspace's shared task inbox
     (e.g. tasks@yourdomain.com), configured via SendGrid Inbound Parse.
  2. SendGrid POSTs the parsed email to POST /email/inbound (see routers/email.py)
  3. This module resolves the sender to an existing registered User by their
     From: address (no new DB fields needed — User.email already exists).
  4. Subject + body is run through the SAME AI extractor Slack uses
     (extract_task_from_message) — no duplicate AI logic.
  5. Task is saved to PostgreSQL under the sender's workspace_id, owned by
     the sender — exactly like a Slack-created task.

Difference from Slack:
  - No @mention parsing — email has no equivalent, so the full subject+body
    always goes straight to the AI extractor (this is the same code path as
    Slack's "natural language" mode).
  - Sender identity comes from a verified From: address matched against
    User.email, not a per-workspace bot install — so only people with an
    existing account can create tasks this way. Unrecognized senders are
    logged and ignored (no task created, no error surfaced — mirrors how
    Slack silently ignores non-task messages).
  - No retry-storm risk (Inbound Parse doesn't hammer the webhook the way
    Slack's Events API does on a slow ack), so no idempotency table is
    needed for the MVP.
"""

import logging
import secrets as _secrets

from app.ai_extractor import extract_task_from_message
from app.database import SessionLocal
from app.models import Priority, Task, TaskStatus

logger = logging.getLogger(__name__)


def _extract_sender_address(raw_from: str) -> str:
    """
    SendGrid's 'from' field looks like 'Wahaj Kashan <wahaj@example.com>'
    or just 'wahaj@example.com'. Pull out the bare address.
    """
    raw_from = (raw_from or "").strip()
    if "<" in raw_from and ">" in raw_from:
        return raw_from.split("<", 1)[1].split(">", 1)[0].strip().lower()
    return raw_from.lower()


async def process_inbound_email(raw_from: str, subject: str, body_text: str) -> Task | None:
    """
    Evaluate an inbound email and create a task if the AI detects one.
    Returns the created Task, or None if no task was created (unrecognized
    sender, empty body, or low-confidence/no extraction).
    """
    sender_address = _extract_sender_address(raw_from)
    if not sender_address:
        logger.warning("Inbound email missing a usable From: address — skipping")
        return None

    subject    = (subject or "").strip()
    body_text  = (body_text or "").strip()
    combined   = "\n".join(part for part in (subject, body_text) if part)

    if not combined:
        logger.info("Inbound email from %s had no content — skipping", sender_address)
        return None

    db = SessionLocal()
    try:
        from app import crud as _crud

        sender_user = _crud.get_user_by_email(db, sender_address)
        if not sender_user:
            logger.info(
                "Inbound email from unrecognized address %s — skipping (no matching account)",
                sender_address,
            )
            return None

        if not sender_user.workspace_id:
            logger.info(
                "Inbound email from %s — user has no workspace yet, skipping", sender_address
            )
            return None

        # ── AI extraction (same call Slack uses) ────────────────────────────
        try:
            extracted = await extract_task_from_message(combined)
        except Exception as exc:
            logger.error("AI extraction failed for inbound email from %s: %s", sender_address, exc, exc_info=True)
            return None

        if not extracted or not extracted.task or not extracted.task.strip():
            logger.info("No task detected in email from %s — skipping", sender_address)
            return None

        confidence = getattr(extracted, "confidence", 1.0) or 1.0
        if confidence < 0.6:
            logger.info("Low confidence %.2f on email from %s — skipping", confidence, sender_address)
            return None

        new_task = Task(
            title             = extracted.task,
            task_description  = extracted.task,
            assignee          = extracted.assignee or None,
            deadline          = extracted.deadline,
            priority          = extracted.priority or Priority.medium,
            source_message    = combined,
            status            = TaskStatus.to_do,
            workspace_id      = sender_user.workspace_id,
            owner_id          = sender_user.id,
            share_token       = _secrets.token_urlsafe(12),
        )
        db.add(new_task)
        db.commit()
        db.refresh(new_task)

        logger.info(
            "Created task id=%s from email | sender=%s | title=%r assignee=%r priority=%s workspace_id=%s",
            new_task.id, sender_address, extracted.task, extracted.assignee,
            extracted.priority, sender_user.workspace_id,
        )
        return new_task

    except Exception as exc:
        db.rollback()
        logger.error("Failed to save task from inbound email (%s): %s", sender_address, exc, exc_info=True)
        return None
    finally:
        db.close()
