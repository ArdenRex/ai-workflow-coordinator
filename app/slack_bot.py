"""
slack_bot.py
------------
Slack bot integration using the Bolt for Python SDK.

Flow:
  1. Slack posts an Events API payload to POST /slack/events
  2. SlackRequestHandler (ASGI) forwards it to the Bolt App
  3. Bot listens to ALL messages in channels (not just @mentions)
  4. Every message is evaluated by AI — if it looks like a task, it's created
  5. Assignee is auto-detected from the message
  6. Assignee receives a DM telling them who assigned the task and the sender's role
  7. Task is saved to PostgreSQL with correct workspace_id

Supported formats (no @mention needed):
  - "Ali make the sales report today"
  - "Hey Sarah, finish the report by Friday — it's urgent"
  - "@bot create task [@assignee] <title>"  ← still works too

Required Slack OAuth scopes (Bot Token):
  channels:history   -- read public channel messages
  chat:write         -- post replies
  app_mentions:read  -- receive @mention events
  users:read         -- resolve user display names
  im:write           -- open DM channels for notifications
"""

import asyncio
import concurrent.futures
import logging
import os
import re
import secrets as _secrets

from slack_bolt import App
from slack_bolt.adapter.fastapi import SlackRequestHandler

from app.ai_extractor import extract_task_from_message
from app.config import get_settings
from app.database import SessionLocal
from app.models import Priority, Task, TaskStatus, UserRole

logger = logging.getLogger(__name__)
settings = get_settings()

# ── Bolt app ──────────────────────────────────────────────────────────────────
bolt_app = App(
    token=settings.slack_bot_token.get_secret_value(),
    signing_secret=settings.slack_signing_secret.get_secret_value(),
    process_before_response=True,
)

slack_handler = SlackRequestHandler(bolt_app)

PRIORITY_EMOJI: dict[str, str] = {
    Priority.critical.value: ":red_circle:",
    Priority.high.value:     ":large_orange_circle:",
    Priority.medium.value:   ":large_yellow_circle:",
    Priority.low.value:      ":large_green_circle:",
}

# Role display labels for DM notifications
ROLE_LABELS: dict[str, str] = {
    UserRole.architect.value: "Manager",
    UserRole.navigator.value: "Team Lead",
    UserRole.operator.value:  "Team Member",
    UserRole.solo.value:      "Independent",
}

FRONTEND_URL = os.getenv("FRONTEND_URL", "").rstrip("/")

# ── Regex patterns ─────────────────────────────────────────────────────────────
_CMD_RE = re.compile(
    r"<@[A-Z0-9]+>\s+create\s+task\s+"
    r"(?:<@(?P<mention>[A-Z0-9]+)>\s+)?"
    r"(?P<title>.+)",
    re.IGNORECASE,
)
_MENTION_RE     = re.compile(r"<@[A-Z0-9]+>\s*", re.IGNORECASE)
_NL_ASSIGNEE_RE = re.compile(r"<@(?P<uid>[A-Z0-9]+)>", re.IGNORECASE)

# Subtypes to always ignore
_IGNORE_SUBTYPES = {
    "bot_message", "message_deleted", "message_changed",
    "channel_join", "channel_leave", "file_share",
}


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


def _run_async(coro):
    """
    Safely run an async coroutine from a sync Bolt handler.
    FastAPI already runs an event loop, so we use a thread with its own loop.
    """
    def _in_thread():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_in_thread)
        return future.result(timeout=30)


def _get_workspace_id(db, sender_slack_id: str) -> int | None:
    """
    Resolve workspace_id for the message sender.
    Falls back to the first workspace in the DB if sender isn't linked.
    This ensures ALL Slack-created tasks are visible on the dashboard.
    """
    from app import crud as _crud
    from app.models import Workspace

    if sender_slack_id:
        sender_user = _crud.get_user_by_slack_id(db, sender_slack_id)
        if sender_user and sender_user.workspace_id:
            return sender_user.workspace_id

    # Fallback: assign to the first available workspace
    first_workspace = db.query(Workspace).first()
    return first_workspace.id if first_workspace else None


def _get_sender_info(db, sender_slack_id: str) -> tuple[str | None, str | None]:
    """
    Return (sender_name, sender_role_label) from the DB.
    Used in the assignee DM notification.
    """
    from app import crud as _crud

    if not sender_slack_id:
        return None, None

    sender_user = _crud.get_user_by_slack_id(db, sender_slack_id)
    if sender_user:
        role_val   = sender_user.role.value if hasattr(sender_user.role, "value") else sender_user.role
        role_label = ROLE_LABELS.get(role_val, "Team Member")
        return sender_user.name, role_label

    return None, None


def _send_dm(client, slack_user_id: str, text: str) -> bool:
    """Open a DM and send text to a Slack user. Returns True on success."""
    try:
        convo      = client.conversations_open(users=[slack_user_id])
        dm_channel = convo["channel"]["id"]
        client.chat_postMessage(channel=dm_channel, text=text)
        logger.info("DM sent to slack_user_id=%s", slack_user_id)
        return True
    except Exception as exc:
        logger.warning("Failed to DM slack_user_id=%s: %s", slack_user_id, exc)
        return False


def _notify_assignee(
    client,
    db,
    assignee_slack_id: str,
    assignee_name: str,
    task_title: str,
    task_id: int,
    sender_slack_id: str,
    sender_name_slack: str,
    workspace_id: int | None,
) -> None:
    """
    DM the assignee telling them:
    - What task was assigned to them
    - Who assigned it and their role (e.g. "Wahaj (Manager)")
    - Link to view/claim the task on the dashboard
    """
    db_sender_name, db_sender_role = _get_sender_info(db, sender_slack_id)

    sender_display = db_sender_name or sender_name_slack or "Someone"
    role_display   = f" ({db_sender_role})" if db_sender_role else ""
    claim_url      = f"{FRONTEND_URL}/claim?task={task_id}" if FRONTEND_URL else ""

    msg_lines = [
        f"📋 *New task assigned to you!*",
        f"",
        f"*Task:* {task_title}",
        f"*Assigned by:* {sender_display}{role_display}",
    ]
    if claim_url:
        msg_lines += [
            f"",
            f"👉 View & manage it here: {claim_url}",
            f"_Sign in with your work email to access your full task list._",
        ]

    _send_dm(client, assignee_slack_id, "\n".join(msg_lines))


def _maybe_send_invite_teammate_prompt(
    client,
    db,
    creator_slack_id: str,
    workspace_invite_code: str | None,
) -> None:
    """Every 3rd task created, DM the creator to invite teammates."""
    if not creator_slack_id or not workspace_invite_code:
        return

    task_count = (
        db.query(Task)
        .filter(Task.assignee_id == creator_slack_id)
        .count()
    )

    if task_count > 0 and task_count % 3 == 0:
        invite_url = f"{FRONTEND_URL}/join?invite={workspace_invite_code}"
        msg = (
            f"🎉 You've created *{task_count} tasks* so far — great work!\n\n"
            f"Want to bring your whole team in? Share this link:\n"
            f"👉 {invite_url}\n\n"
            f"_Teammates who click it will be added to your workspace automatically._"
        )
        _send_dm(client, creator_slack_id, msg)


def _get_workspace_invite_code(db, workspace_id: int | None) -> str | None:
    """Fetch the workspace invite code for building onboarding links."""
    if not workspace_id:
        return None
    from app import crud as _crud
    workspace = _crud.get_workspace_by_id(db, workspace_id)
    return workspace.invite_code if workspace else None


# ── Core task processing (shared by mention + message handlers) ───────────────

def _process_message(event, say, client, require_mention: bool = False):
    """
    Evaluate a Slack message and create a task if the AI detects one.

    require_mention=True  → used for @mention handler; will reply with errors/help
    require_mention=False → used for message handler; stays silent if not a task
    """
    channel_id = event.get("channel", "")
    message_ts = event.get("ts", "")
    text       = event.get("text", "")
    thread_ts  = event.get("thread_ts") or message_ts
    sender_id  = event.get("user", "")
    subtype    = event.get("subtype", "")

    # Skip system/bot events
    if subtype in _IGNORE_SUBTYPES:
        return
    if event.get("bot_id"):
        return
    if not text or not text.strip():
        return

    # Optional channel restriction
    if settings.slack_channel_id and channel_id != settings.slack_channel_id:
        return

    # ── Parse message ─────────────────────────────────────────────────────────
    match = _CMD_RE.search(text)

    if match:
        raw_title           = match.group("title").strip()
        slack_mention       = match.group("mention")
        slack_assignee_name = (
            _resolve_slack_user(client, slack_mention) if slack_mention else None
        )
        ai_input = raw_title
        mode     = "command"
    else:
        body = _MENTION_RE.sub("", text).strip()
        if not body:
            if require_mention:
                say(
                    text=(
                        "Hi! I can create tasks two ways:\n"
                        "• *Structured:* `@bot create task [@assignee] <title>`\n"
                        "• *Natural language:* `@bot Hey Alina, finish the sales report today — it's urgent`\n\n"
                        "Or just send any message like _'Ali make the sales report today'_ and I'll pick it up automatically!"
                    ),
                    thread_ts=thread_ts,
                    channel=channel_id,
                )
            return

        assignee_match = _NL_ASSIGNEE_RE.search(body)
        if assignee_match:
            slack_mention       = assignee_match.group("uid")
            slack_assignee_name = _resolve_slack_user(client, slack_mention)
            ai_input = re.sub(r"\s{2,}", " ", _NL_ASSIGNEE_RE.sub("", body).strip())
        else:
            slack_mention       = None
            slack_assignee_name = None
            ai_input            = body

        mode = "natural"

    logger.info("Evaluating for task | mode=%s | input=%r", mode, ai_input[:100])

    # ── AI extraction ─────────────────────────────────────────────────────────
    try:
        extracted = _run_async(extract_task_from_message(ai_input))
    except Exception as exc:
        logger.error("AI extraction failed: %s", exc, exc_info=True)
        if require_mention:
            say(
                text="⚠️ I couldn't extract a task from that message. Please try rephrasing.",
                thread_ts=thread_ts,
                channel=channel_id,
            )
        return

    # No task detected — skip silently for auto-detection
    if not extracted or not extracted.task or not extracted.task.strip():
        logger.info("No task detected in message — skipping")
        return

    # For auto-detection (non-mention), skip low-confidence extractions
    if not require_mention:
        confidence = getattr(extracted, "confidence", 1.0) or 1.0
        if confidence < 0.6:
            logger.info("Low confidence %.2f — skipping auto-detection", confidence)
            return

    # ── Resolve assignee ──────────────────────────────────────────────────────
    final_assignee    = slack_assignee_name or extracted.assignee or None
    final_assignee_id = slack_mention if slack_assignee_name else None

    logger.info(
        "Task confirmed | task=%r | assignee=%r | deadline=%r | priority=%s | mode=%s",
        extracted.task, final_assignee, extracted.deadline, extracted.priority, mode,
    )

    # ── Save to DB ────────────────────────────────────────────────────────────
    db = SessionLocal()
    try:
        if _task_exists(db, channel_id, message_ts):
            logger.info("Duplicate event ts=%s — skipping", message_ts)
            return

        workspace_id = _get_workspace_id(db, sender_id)
        invite_code  = _get_workspace_invite_code(db, workspace_id)

        new_task = Task(
            title            = extracted.task,
            task_description = extracted.task,
            assignee         = final_assignee,
            assignee_id      = final_assignee_id,
            deadline         = extracted.deadline,
            priority         = extracted.priority or Priority.medium,
            source_message   = text,
            slack_channel_id = channel_id,
            slack_message_ts = message_ts,
            status           = TaskStatus.to_do,
            workspace_id     = workspace_id,
            share_token      = _secrets.token_urlsafe(12),
        )
        db.add(new_task)
        db.commit()
        db.refresh(new_task)

        # ── Post confirmation in channel ──────────────────────────────────────
        priority_val  = (
            new_task.priority.value
            if hasattr(new_task.priority, "value")
            else new_task.priority
        )
        emoji         = PRIORITY_EMOJI.get(priority_val, ":large_yellow_circle:")
        assignee_line = f"👤 Assigned to: *{final_assignee}*" if final_assignee else "👤 *Unassigned*"
        deadline_line = f"📅 Deadline: *{extracted.deadline}*" if extracted.deadline else ""

        lines = [
            f"✅ Task *{extracted.task}* (id: {new_task.id}) added to *To Do*.",
            assignee_line,
            f"{emoji} Priority: *{priority_val.capitalize()}*",
        ]
        if deadline_line:
            lines.append(deadline_line)

        say(text="\n".join(lines), thread_ts=thread_ts, channel=channel_id)
        logger.info(
            "Created task id=%s title=%r assignee=%r priority=%s deadline=%r mode=%s workspace_id=%s",
            new_task.id, extracted.task, final_assignee,
            extracted.priority, extracted.deadline, mode, workspace_id,
        )

        # ── DM the assignee with full context ─────────────────────────────────
        if final_assignee_id:
            try:
                sender_name_slack = _resolve_slack_user(client, sender_id) if sender_id else "Someone"
                _notify_assignee(
                    client            = client,
                    db                = db,
                    assignee_slack_id = final_assignee_id,
                    assignee_name     = final_assignee or final_assignee_id,
                    task_title        = extracted.task,
                    task_id           = new_task.id,
                    sender_slack_id   = sender_id,
                    sender_name_slack = sender_name_slack,
                    workspace_id      = workspace_id,
                )
            except Exception as exc:
                logger.warning("Assignee DM failed (non-fatal): %s", exc)

        # ── Prompt sender to invite teammates every 3rd task ──────────────────
        if sender_id:
            try:
                _maybe_send_invite_teammate_prompt(
                    client               = client,
                    db                   = db,
                    creator_slack_id     = sender_id,
                    workspace_invite_code= invite_code,
                )
            except Exception as exc:
                logger.warning("Teammate invite prompt failed (non-fatal): %s", exc)

    except Exception as exc:
        db.rollback()
        logger.error("Failed to save task: %s", exc, exc_info=True)
        if require_mention:
            say(
                text=f"⚠️ Sorry, I couldn't save that task. Please try again. (Error: {exc})",
                thread_ts=thread_ts,
                channel=channel_id,
            )
    finally:
        db.close()


# ── Slack event handlers ──────────────────────────────────────────────────────

@bolt_app.event("app_mention")
def handle_mention(event, say, client):
    """
    Handles @mentions of the bot.
    Always processes and replies (even on errors or no-task messages).
    """
    _process_message(event, say, client, require_mention=True)


@bolt_app.event("message")
def handle_all_messages(event, say, client):
    """
    Listens to ALL channel messages — no @mention needed.
    AI decides whether the message contains a task.
    Bot stays silent if it's not a task (no spam).

    Examples that auto-create tasks:
      "Ali make the sales report today"
      "Hey Sarah, finish the deck by Friday — urgent"
      "John please review the contracts this week"
    """
    # Skip bot messages
    if event.get("bot_id") or event.get("subtype") in _IGNORE_SUBTYPES:
        return

    # Skip if it's an @mention — the app_mention handler covers that
    text = event.get("text", "")
    try:
        bot_info    = bolt_app.client.auth_test()
        bot_user_id = bot_info.get("user_id", "")
        if bot_user_id and f"<@{bot_user_id}>" in text:
            return
    except Exception:
        pass

    _process_message(event, say, client, require_mention=False)
