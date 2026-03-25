"""
slack_bot.py
------------
Slack bot integration using the Bolt for Python SDK.

Flow:
  1. Slack posts an Events API payload to POST /slack/events
  2. SlackRequestHandler (ASGI) forwards it to the Bolt App
  3. @app.event("app_mention") fires when the bot is @mentioned
  4. Bot supports two formats:
       A. Structured:   @bot create task [@assignee] <title>
       B. Natural lang: @bot Hey Sarah, finish the sales report by Friday
  5. Task is saved to PostgreSQL directly
  6. Bot replies in the same thread confirming task creation

Required Slack OAuth scopes (Bot Token):
  channels:history   -- read public channel messages
  groups:history     -- read private channel messages (if needed)
  chat:write         -- post replies
  app_mentions:read  -- receive @mention events
  users:read         -- resolve user display names

Required Event Subscriptions (in your Slack App dashboard):
  app_mention        -- @bot mentions
  message.channels   -- messages in public channels (optional)
"""

import logging
import re

from slack_bolt import App
from slack_bolt.adapter.fastapi import SlackRequestHandler

from app.config import get_settings
from app.database import SessionLocal
from app.models import Priority, Task, TaskStatus

logger = logging.getLogger(__name__)
settings = get_settings()

# ── Bolt app ──────────────────────────────────────────────────────────────────
# process_before_response=True is required for FastAPI (ASGI) — without it,
# Slack's 3-second ack deadline will time out before the handler completes.
bolt_app = App(
    token=settings.slack_bot_token.get_secret_value(),
    signing_secret=settings.slack_signing_secret.get_secret_value(),
    process_before_response=True,
)

# FastAPI <-> Bolt adapter (handles signature verification + ack)
slack_handler = SlackRequestHandler(bolt_app)

PRIORITY_EMOJI: dict[str, str] = {
    Priority.critical.value: ":red_circle:",
    Priority.high.value:     ":large_orange_circle:",
    Priority.medium.value:   ":large_yellow_circle:",
    Priority.low.value:      ":large_green_circle:",
}

# ── Regex patterns ─────────────────────────────────────────────────────────────
# Structured command:
#   @bot create task <title>
#   @bot create task @ali Finish sales report
_CMD_RE = re.compile(
    r"<@[A-Z0-9]+>\s+create\s+task\s+"    # mention + "create task "
    r"(?:<@(?P<mention>[A-Z0-9]+)>\s+)?"   # optional @assignee mention
    r"(?P<title>.+)",                       # task title (rest of message)
    re.IGNORECASE,
)

# Strip ALL bot mentions to get the plain message body
_MENTION_RE = re.compile(r"<@[A-Z0-9]+>\s*", re.IGNORECASE)

# Detect an @assignee anywhere in natural-language messages
_NL_ASSIGNEE_RE = re.compile(r"<@(?P<uid>[A-Z0-9]+)>", re.IGNORECASE)


def _resolve_slack_user(client, user_id: str) -> str:
    """Return display name for a Slack user ID, fallback to raw ID."""
    try:
        info = client.users_info(user=user_id)
        profile = info["user"].get("profile", {})
        return (
            profile.get("display_name")
            or profile.get("real_name")
            or user_id
        )
    except Exception:
        return user_id


def _task_exists(db, channel_id: str, message_ts: str) -> bool:
    """Idempotency check — True if this Slack message was already processed."""
    return (
        db.query(Task)
        .filter_by(slack_channel_id=channel_id, slack_message_ts=message_ts)
        .first()
        is not None
    )


@bolt_app.event("app_mention")
def handle_mention(event, say, client):
    """
    Handles two message formats:

    1. Structured command (Option A):
         @bot create task [@assignee] <title>
         → Extracts title and optional assignee from the command syntax.

    2. Natural language fallback (Option B):
         @bot Hey Sarah, please finish the sales report by Friday
         → Strips the bot mention, uses the rest as the task title.
         → If another @user is mentioned in the message, they become the assignee.
    """
    channel_id = event.get("channel", "")
    message_ts = event.get("ts", "")
    text       = event.get("text", "")
    thread_ts  = event.get("thread_ts") or message_ts

    # Optional channel restriction
    if settings.slack_channel_id and channel_id != settings.slack_channel_id:
        logger.info("Ignoring message from channel %s (not allowed)", channel_id)
        return

    # ── Route: structured command vs natural language ──────────────────────────
    match = _CMD_RE.search(text)

    if match:
        # ── Option A: structured "@bot create task [@assignee] <title>" ──────
        title         = match.group("title").strip()
        assignee_id   = match.group("mention")
        assignee_name = (
            _resolve_slack_user(client, assignee_id) if assignee_id else None
        )
        mode = "command"

    else:
        # ── Option B: natural language fallback ───────────────────────────────
        body = _MENTION_RE.sub("", text).strip()

        if not body:
            say(
                text=(
                    "Hi! I can create tasks two ways:\n"
                    "• *Structured:* `@bot create task [@assignee] <title>`\n"
                    "• *Natural language:* `@bot Hey Sarah, finish the report by Friday`"
                ),
                thread_ts=thread_ts,
                channel=channel_id,
            )
            return

        title = body

        # Look for an @mention in the body to use as assignee
        assignee_match = _NL_ASSIGNEE_RE.search(body)
        if assignee_match:
            assignee_id   = assignee_match.group("uid")
            assignee_name = _resolve_slack_user(client, assignee_id)
            # Clean the mention tag out of the title for readability
            title = _NL_ASSIGNEE_RE.sub("", body).strip()
            title = re.sub(r"\s{2,}", " ", title)
        else:
            assignee_id   = None
            assignee_name = None

        mode = "natural"

    logger.info(
        "Processing task | mode=%s | title=%r | assignee=%r | ts=%s",
        mode, title, assignee_name, message_ts,
    )

    # ── DB insert ──────────────────────────────────────────────────────────────
    db = SessionLocal()
    try:
        if _task_exists(db, channel_id, message_ts):
            logger.info("Duplicate Slack event ts=%s — skipping", message_ts)
            return

        new_task = Task(
            title            = title,
            task_description = title,       # keep legacy column in sync
            assignee         = assignee_name,
            assignee_id      = assignee_id,
            source_message   = text,
            slack_channel_id = channel_id,
            slack_message_ts = message_ts,
            status           = TaskStatus.to_do,
        )
        db.add(new_task)
        db.commit()
        db.refresh(new_task)

        if assignee_name:
            reply = (
                f"✅ Task *{title}* (id: {new_task.id}) "
                f"assigned to *{assignee_name}* and added to *To Do*."
            )
        else:
            reply = (
                f"✅ Task *{title}* (id: {new_task.id}) "
                f"added to *To Do* (no assignee)."
            )

        say(text=reply, thread_ts=thread_ts, channel=channel_id)
        logger.info(
            "Created task id=%s title=%r assignee=%r mode=%s",
            new_task.id, title, assignee_name, mode,
        )

    except Exception as exc:
        db.rollback()
        logger.error("Failed to create task: %s", exc, exc_info=True)
        say(
            text=f"⚠️ Sorry, I couldn't create that task. Please try again. (Error: {exc})",
            thread_ts=thread_ts,
            channel=channel_id,
        )
    finally:
        db.close()
