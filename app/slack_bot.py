"""
slack_bot.py
------------
Slack bot integration using the Bolt for Python SDK.

Flow:
  1. Slack posts an Events API payload to POST /slack/events
  2. SlackRequestHandler (ASGI) forwards it to the Bolt App
  3. @app.event("message") fires for every message in a subscribed channel
  4. Bot filters its own messages (bot_id guard) and sub-types (edits etc.)
  5. Message text is sent to OpenAI -> ExtractedTask
  6. Task is saved to PostgreSQL via crud.create_task()
  7. Bot replies in the same thread confirming task creation

Required Slack OAuth scopes (Bot Token):
  channels:history   -- read public channel messages
  groups:history     -- read private channel messages (if needed)
  chat:write         -- post replies
  app_mentions:read  -- optional, for @mention flows

Required Event Subscriptions (in your Slack App dashboard):
  message.channels   -- messages in public channels
  message.groups     -- messages in private channels (if needed)
"""

import asyncio
import logging

from slack_bolt import App
from slack_bolt.adapter.fastapi import SlackRequestHandler

from app import crud
from app.ai_extractor import extract_task_from_message
from app.config import get_settings
from app.database import SessionLocal
from app.models import Priority

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

# Slack message text min length — shorter messages are unlikely to contain tasks
_MIN_TEXT_LENGTH = 10


def _build_reply(
    task_text: str,
    assignee: str | None,
    deadline: str | None,
    priority: str,
    task_id: int,
) -> str:
    """Compose the threaded Slack reply."""
    assignee_label = f"*{assignee}*" if assignee else "*Unassigned*"
    emoji = PRIORITY_EMOJI.get(priority, ":large_yellow_circle:")
    lines = [
        f":white_check_mark: Task #{task_id} created and assigned to {assignee_label}",
        f"  > {task_text}",
    ]
    meta: list[str] = []
    if deadline:
        meta.append(f"Deadline: {deadline}")
    meta.append(f"Priority: {emoji} {priority.capitalize()}")
    lines.append("  > " + "  |  ".join(meta))
    return "\n".join(lines)


def _run_async(coro):
    """
    Run an async coroutine from a sync Bolt handler.

    Bolt's sync handlers run in a threadpool executor — there is no running
    event loop in that thread, so we must create a fresh one per call.
    asyncio.run() handles loop creation, cleanup, and cancels pending tasks.
    """
    return asyncio.run(coro)


def _is_duplicate(db, channel_id: str, message_ts: str) -> bool:
    """Return True if we've already processed this exact Slack message."""
    return crud.get_task_by_slack_ts(db, channel_id, message_ts) is not None


@bolt_app.event("message")
def handle_message(event, say):
    """
    Handles incoming Slack messages.
    Guards against bot messages, edits, duplicates, and off-channel messages.
    """
    subtype = event.get("subtype")

    # Skip sub-typed events (edits, joins, bot_message, file shares, etc.)
    if subtype:
        logger.debug("Skipping sub-typed event: %s", subtype)
        return

    # Skip messages from bots (prevents infinite reply loops)
    if event.get("bot_id"):
        logger.debug("Skipping bot message: bot_id=%s", event.get("bot_id"))
        return

    channel_id: str = event.get("channel", "")
    message_ts: str = event.get("ts", "")

    # Optional: restrict to a specific channel
    if settings.slack_channel_id and channel_id != settings.slack_channel_id:
        return

    text: str = (event.get("text") or "").strip()
    if len(text) < _MIN_TEXT_LENGTH:
        return

    thread_ts: str = event.get("thread_ts") or message_ts
    user_id: str = event.get("user", "unknown")

    logger.info(
        "Processing message user=%s channel=%s ts=%s: %r",
        user_id, channel_id, message_ts, text[:80],
    )

    # ── Deduplication: skip if we already handled this message ────────────────
    # Slack retries delivery on 5xx or timeout — without this guard a single
    # message can create multiple tasks.
    db = SessionLocal()
    try:
        if _is_duplicate(db, channel_id, message_ts):
            logger.info("Duplicate Slack event ts=%s — skipping.", message_ts)
            return

        # ── Step 1: AI extraction ─────────────────────────────────────────────
        try:
            extracted = _run_async(extract_task_from_message(text))
        except Exception as exc:
            logger.exception("AI extraction failed for ts=%s: %s", message_ts, exc)
            say(
                text=":warning: Could not extract a task from that message. Please try rephrasing.",
                thread_ts=thread_ts,
                channel=channel_id,
            )
            return

        # ── Step 2: Save to database ──────────────────────────────────────────
        try:
            task = crud.create_task(
                db=db,
                source_message=text,
                extracted=extracted,
                slack_channel_id=channel_id,
                slack_message_ts=message_ts,
            )
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.exception("DB save failed for ts=%s: %s", message_ts, exc)
            say(
                text=":warning: Task was extracted but could not be saved. Please try again.",
                thread_ts=thread_ts,
                channel=channel_id,
            )
            return

    finally:
        db.close()

    logger.info(
        "Task #%d saved — assignee=%r priority=%s",
        task.id, task.assignee, task.priority,
    )

    # ── Step 3: Reply in thread ───────────────────────────────────────────────
    reply = _build_reply(
        task_text=task.task_description,
        assignee=task.assignee,
        deadline=task.deadline,
        priority=task.priority.value if hasattr(task.priority, "value") else task.priority,
        task_id=task.id,
    )
    say(text=reply, thread_ts=thread_ts, channel=channel_id)


@bolt_app.event("app_mention")
def handle_mention(event, say):
    """Responds to @bot mentions with a help message."""
    thread_ts: str = event.get("thread_ts") or event.get("ts", "")
    channel_id: str = event.get("channel", "")
    say(
        text=(
            ":wave: I'm the *AI Workflow Coordinator*.\n"
            "Post any message describing a task and I'll extract it automatically.\n"
            '_Example: "Hey Sarah, please deploy the hotfix by Friday — it\'s urgent"_'
        ),
        thread_ts=thread_ts,
        channel=channel_id,
    )
