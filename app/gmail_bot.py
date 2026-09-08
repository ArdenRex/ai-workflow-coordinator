"""
gmail_bot.py
------------
Gmail Connect — the "connect your own inbox" equivalent of slack_bot.py /
email_bot.py.

Flow:
  1. A user clicks "Connect Gmail" in the dashboard → routers/gmail_router.py
     sends them through Google's OAuth consent screen (readonly Gmail scope).
  2. Google redirects back with a code; the callback exchanges it for an
     access_token + refresh_token, stored on that User row.
  3. A background job (started in main.py's lifespan) calls
     poll_all_connected_users() every GMAIL_POLL_INTERVAL_SECONDS. For each
     connected user it lists Gmail messages received since their last check,
     runs each one through the SAME AI extractor Slack/email use, and saves
     a Task — exactly like a Slack- or email-created task.

Difference from Slack/email:
  - Per-user OAuth (Gmail has no "install to a shared inbox" concept) — the
    tokens live on app.models.User, not a workspace-level install.
  - No webhook — Gmail doesn't push to us without a paid Pub/Sub setup, so
    this uses simple polling on a fixed interval instead.
  - Idempotency: each created Task stores the Gmail message id
    (Task.gmail_message_id). The poller re-queries a small overlapping
    window each run (rather than trusting a single "since" boundary down to
    the second) and skips any message id that already has a Task — cheaper
    than Gmail's History API and doesn't expire the way a historyId does.
"""

import base64
import logging
from datetime import datetime, timedelta, timezone

import httpx

from app.ai_extractor import extract_task_from_message
from app.config import get_settings
from app.database import SessionLocal
from app.models import Priority, Task, TaskStatus, User

logger = logging.getLogger(__name__)

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_API_BASE   = "https://gmail.googleapis.com/gmail/v1/users/me"

# How far back to re-query on every poll, regardless of gmail_last_checked_at
# — a small overlap so a message that arrives right at the boundary of one
# poll isn't missed. Duplicate messages inside the overlap are skipped via
# Task.gmail_message_id (see module docstring).
OVERLAP_SECONDS = 180


# ── Token refresh ────────────────────────────────────────────────────────────

async def _refresh_access_token(db, user: User) -> str | None:
    """
    Exchange a stored refresh_token for a fresh access_token, save it on the
    user, and return it. Returns None (and flags the user as disconnected)
    if the refresh_token itself has been revoked.
    """
    settings = get_settings()
    if not user.gmail_refresh_token:
        return None

    async with httpx.AsyncClient() as client:
        resp = await client.post(GOOGLE_TOKEN_URL, data={
            "client_id":     settings.google_client_id,
            "client_secret": settings.google_client_secret.get_secret_value(),
            "refresh_token": user.gmail_refresh_token,
            "grant_type":    "refresh_token",
        })

    data = resp.json()
    if resp.status_code != 200 or "access_token" not in data:
        logger.warning(
            "Gmail token refresh failed for user_id=%s: %s — marking disconnected",
            user.id, data,
        )
        # A revoked/expired refresh_token means the user has to reconnect —
        # clear the connection so the UI reflects reality instead of
        # silently failing every poll from here on.
        user.gmail_connected = False
        db.add(user)
        db.commit()
        return None

    user.gmail_access_token = data["access_token"]
    user.gmail_token_expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=int(data.get("expires_in", 3600))
    )
    db.add(user)
    db.commit()
    return data["access_token"]


async def _get_valid_access_token(db, user: User) -> str | None:
    if (
        user.gmail_access_token
        and user.gmail_token_expires_at
        and user.gmail_token_expires_at > datetime.now(timezone.utc) + timedelta(seconds=60)
    ):
        return user.gmail_access_token
    return await _refresh_access_token(db, user)


# ── Gmail API helpers ────────────────────────────────────────────────────────

def _extract_plain_text(payload: dict) -> str:
    """Walk a Gmail message payload (possibly multipart) for the text/plain part."""
    if payload.get("mimeType") == "text/plain":
        data = payload.get("body", {}).get("data")
        if data:
            return _b64url_decode(data)

    for part in payload.get("parts") or []:
        if part.get("mimeType") == "text/plain":
            data = part.get("body", {}).get("data")
            if data:
                return _b64url_decode(data)
        if part.get("parts"):
            nested = _extract_plain_text(part)
            if nested:
                return nested
    return ""


def _b64url_decode(data: str) -> str:
    padded = data + "=" * (-len(data) % 4)
    try:
        return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")
    except Exception:
        return ""


def _header(headers: list[dict], name: str) -> str:
    for h in headers or []:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


async def _list_recent_message_ids(client: httpx.AsyncClient, access_token: str, since: datetime) -> list[str]:
    unix_ts = int(since.timestamp())
    resp = await client.get(
        f"{GMAIL_API_BASE}/messages",
        headers={"Authorization": f"Bearer {access_token}"},
        params={"q": f"after:{unix_ts} category:primary", "maxResults": 25},
    )
    if resp.status_code != 200:
        logger.warning("Gmail message list failed (%s): %s", resp.status_code, resp.text[:200])
        return []
    return [m["id"] for m in resp.json().get("messages", [])]


async def _fetch_message(client: httpx.AsyncClient, access_token: str, message_id: str) -> dict | None:
    resp = await client.get(
        f"{GMAIL_API_BASE}/messages/{message_id}",
        headers={"Authorization": f"Bearer {access_token}"},
        params={"format": "full"},
    )
    if resp.status_code != 200:
        logger.warning("Gmail message fetch failed for %s (%s)", message_id, resp.status_code)
        return None
    return resp.json()


# ── Core polling logic ───────────────────────────────────────────────────────

async def poll_gmail_for_user(db, user: User) -> int:
    """
    Check one connected user's inbox for new mail since their last check and
    create a Task for each one the AI extractor detects a task in. Returns
    the number of tasks created.
    """
    if not user.gmail_connected or not user.workspace_id:
        return 0

    access_token = await _get_valid_access_token(db, user)
    if not access_token:
        return 0

    since = (user.gmail_last_checked_at or datetime.now(timezone.utc) - timedelta(hours=1))
    since = since - timedelta(seconds=OVERLAP_SECONDS)
    poll_started_at = datetime.now(timezone.utc)

    created_count = 0
    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            message_ids = await _list_recent_message_ids(client, access_token, since)
        except Exception as exc:
            logger.error("Gmail poll failed listing messages for user_id=%s: %s", user.id, exc, exc_info=True)
            return 0

        for message_id in message_ids:
            # Skip messages we've already turned into a task
            existing = db.query(Task.id).filter(Task.gmail_message_id == message_id).first()
            if existing:
                continue

            try:
                msg = await _fetch_message(client, access_token, message_id)
            except Exception as exc:
                logger.error("Gmail poll failed fetching message %s: %s", message_id, exc, exc_info=True)
                continue
            if not msg:
                continue

            headers = msg.get("payload", {}).get("headers", [])
            subject = _header(headers, "Subject")
            body    = _extract_plain_text(msg.get("payload", {})) or msg.get("snippet", "")
            combined = "\n".join(part for part in (subject, body) if part).strip()
            if not combined:
                continue

            try:
                extracted = await extract_task_from_message(combined)
            except Exception as exc:
                logger.error("AI extraction failed for Gmail message %s: %s", message_id, exc, exc_info=True)
                continue

            if not extracted or not extracted.task or not extracted.task.strip():
                continue
            confidence = getattr(extracted, "confidence", 1.0) or 1.0
            if confidence < 0.6:
                continue

            import secrets as _secrets
            new_task = Task(
                title            = extracted.task,
                task_description = extracted.task,
                assignee         = extracted.assignee or None,
                deadline         = extracted.deadline,
                priority         = extracted.priority or Priority.medium,
                source_message   = combined,
                status           = TaskStatus.to_do,
                workspace_id     = user.workspace_id,
                owner_id         = user.id,
                share_token      = _secrets.token_urlsafe(12),
                gmail_message_id = message_id,
            )
            db.add(new_task)
            db.commit()
            db.refresh(new_task)
            created_count += 1

            logger.info(
                "Created task id=%s from Gmail | user_id=%s title=%r workspace_id=%s",
                new_task.id, user.id, extracted.task, user.workspace_id,
            )

    user.gmail_last_checked_at = poll_started_at
    db.add(user)
    db.commit()
    return created_count


async def poll_all_connected_users() -> None:
    """Entry point called on a fixed interval by the scheduler in main.py."""
    db = SessionLocal()
    try:
        users = db.query(User).filter(User.gmail_connected.is_(True)).all()
        if not users:
            return
        total = 0
        for user in users:
            try:
                total += await poll_gmail_for_user(db, user)
            except Exception as exc:
                logger.error("Gmail poll failed for user_id=%s: %s", user.id, exc, exc_info=True)
        if total:
            logger.info("Gmail poll cycle complete — %d task(s) created across %d user(s)", total, len(users))
    finally:
        db.close()
