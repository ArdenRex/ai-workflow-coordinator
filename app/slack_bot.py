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
       B. Natural lang: @bot Hey Alina, finish the sales report today. It's urgent.
  5. Message is sent to Groq AI to extract task, assignee, deadline, priority
  6. Task is saved to PostgreSQL
  7. Bot replies in the same thread confirming task creation

Segment 5 — Viral Onboarding:
  - After task creation, if the assignee has a Slack ID but no account,
    the bot DMs them an invite link to claim the task and sign up.
  - After every 3rd task created by a user, the bot DMs them a prompt
    to invite teammates into the workspace.

Required Slack OAuth scopes (Bot Token):
  channels:history   -- read public channel messages
  chat:write         -- post replies
  app_mentions:read  -- receive @mention events
  users:read         -- resolve user display names
  im:write           -- open DM channels for invite messages
"""

import asyncio
import concurrent.futures
import logging
import os
import re

from slack_bolt import App
from slack_bolt.adapter.fastapi import SlackRequestHandler

from app.ai_extractor import extract_task_from_message
from app.config import get_settings
from app.database import SessionLocal
from app.models import Priority, Task, TaskStatus

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

# Frontend base URL — used to build invite/claim links
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

    FastAPI already runs an event loop, so asyncio.run() would fail.
    Instead we spin up a fresh event loop in a separate thread via
    concurrent.futures, which is completely isolated from FastAPI's loop.
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


# ── Segment 5: Viral onboarding helpers ──────────────────────────────────────

def _send_dm(client, slack_user_id: str, text: str) -> bool:
    """Open a DM and send text to a Slack user. Returns True on success."""
    try:
        convo = client.conversations_open(users=[slack_user_id])
        dm_channel = convo["channel"]["id"]
        client.chat_postMessage(channel=dm_channel, text=text)
        logger.info("Onboarding DM sent to slack_user_id=%s", slack_user_id)
        return True
    except Exception as exc:
        logger.warning("Failed to DM slack_user_id=%s: %s", slack_user_id, exc)
        return False


def _maybe_send_assignee_invite(
    client,
    db,
    slack_user_id: str,
    assignee_name: str,
    task_id: int,
    task_title: str,
    workspace_invite_code: str | None,
) -> None:
    """
    Segment 5A — Assignee invite DM.

    If the assignee has a Slack ID but no account in our system,
    DM them a claim link so they can sign up and see their task.
    If they already have an account, skip silently.
    """
    from app import crud as _crud

    existing_user = _crud.get_user_by_slack_id(db, slack_user_id)
    if existing_user:
        # Already registered — no invite needed
        return

    # Build the claim URL: frontend handles signup + auto-join via invite code
    claim_url = f"{FRONTEND_URL}/claim?task={task_id}"
    if workspace_invite_code:
        claim_url += f"&invite={workspace_invite_code}"

    msg = (
        f"👋 Hey *{assignee_name}*! You've been assigned a task:\n\n"
        f"📋 *{task_title}*\n\n"
        f"Click below to claim it and see your full task list:\n"
        f"👉 {claim_url}\n\n"
        f"_You'll be signed up automatically — no password needed if you use Slack login._"
    )
    _send_dm(client, slack_user_id, msg)


def _maybe_send_invite_teammate_prompt(
    client,
    db,
    creator_slack_id: str,
    workspace_invite_code: str | None,
) -> None:
    """
    Segment 5B — Teammate invite prompt.

    After a user creates their 3rd, 6th, 9th... task (every 3rd),
    DM them a prompt to invite teammates into the workspace.
    This creates the viral growth loop without being spammy.
    """
    if not creator_slack_id or not workspace_invite_code:
        return

    # Count tasks created by this Slack user
    task_count = (
        db.query(Task)
        .filter(Task.assignee_id == creator_slack_id)
        .count()
    )

    # Also count tasks where creator is the sender (using assignee_id as proxy
    # for now — in a future segment, a creator_slack_id column can be added)
    # Trigger at every 3rd task milestone
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


# ── Main event handler ────────────────────────────────────────────────────────

@bolt_app.event("app_mention")
def handle_mention(event, say, client):
    """
    Handles two message formats:

    1. Structured command (Option A):
         @bot create task [@assignee] <title>

    2. Natural language fallback (Option B):
         @bot Hey Alina, finish the sales report today. It's urgent.

    In both cases the message is sent to Groq AI to extract:
      - task title  (clean, actionable description)
      - assignee    (person mentioned in the message)
      - deadline    (e.g. "today", "Friday", "June 30")
      - priority    (low / medium / high / critical — inferred from urgency words)

    Segment 5 additions:
      - If assignee is not yet registered, sends them a claim/signup DM
      - Every 3rd task, prompts the creator to invite teammates
    """
    channel_id = event.get("channel", "")
    message_ts = event.get("ts", "")
    text       = event.get("text", "")
    thread_ts  = event.get("thread_ts") or message_ts
    sender_id  = event.get("user", "")  # Slack user ID of the person who sent the message

    # Optional channel restriction
    if settings.slack_channel_id and channel_id != settings.slack_channel_id:
        logger.info("Ignoring message from channel %s (not allowed)", channel_id)
        return

    # ── Step 1: Parse the raw message ─────────────────────────────────────────
    match = _CMD_RE.search(text)

    if match:
        # Option A: structured command
        raw_title           = match.group("title").strip()
        slack_mention       = match.group("mention")
        slack_assignee_name = (
            _resolve_slack_user(client, slack_mention) if slack_mention else None
        )
        ai_input = raw_title
        mode = "command"
    else:
        # Option B: natural language
        body = _MENTION_RE.sub("", text).strip()
        if not body:
            say(
                text=(
                    "Hi! I can create tasks two ways:\n"
                    "• *Structured:* `@bot create task [@assignee] <title>`\n"
                    "• *Natural language:* `@bot Hey Alina, finish the sales report today — it's urgent`"
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

    logger.info("Extracting task via AI | mode=%s | input=%r", mode, ai_input[:100])

    # ── Step 2: AI extraction via Groq ────────────────────────────────────────
    try:
        extracted = _run_async(extract_task_from_message(ai_input))
    except Exception as exc:
        logger.error("AI extraction failed: %s", exc, exc_info=True)
        say(
            text="⚠️ I couldn't extract a task from that message. Please try rephrasing.",
            thread_ts=thread_ts,
            channel=channel_id,
        )
        return

    # ── Step 3: Resolve final assignee ────────────────────────────────────────
    # Slack @mention takes priority over AI-extracted name
    final_assignee    = slack_assignee_name or extracted.assignee or None
    final_assignee_id = slack_mention if slack_assignee_name else None

    logger.info(
        "Extracted | task=%r | assignee=%r | deadline=%r | priority=%s | mode=%s",
        extracted.task, final_assignee, extracted.deadline, extracted.priority, mode,
    )

    # ── Step 4: Save to database ───────────────────────────────────────────────
    db = SessionLocal()
    try:
        if _task_exists(db, channel_id, message_ts):
            logger.info("Duplicate Slack event ts=%s — skipping", message_ts)
            return

        # Resolve sender's workspace so we can build invite links
        from app import crud as _crud
        sender_user = _crud.get_user_by_slack_id(db, sender_id) if sender_id else None

        # Fallback: if sender not found by Slack ID, find the first available workspace
        # This ensures Slack-created tasks are always visible in the dashboard
        if sender_user:
            workspace_id = sender_user.workspace_id
        else:
            from app.models import Workspace
            first_workspace = db.query(Workspace).first()
            workspace_id = first_workspace.id if first_workspace else None

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
        )
        db.add(new_task)
        db.commit()
        db.refresh(new_task)

        # ── Step 5: Build confirmation reply ──────────────────────────────────
        priority_val = (
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
            "Created task id=%s title=%r assignee=%r priority=%s deadline=%r mode=%s",
            new_task.id, extracted.task, final_assignee,
            extracted.priority, extracted.deadline, mode,
        )

        # ── Segment 5A: Send assignee invite DM if they're not registered ─────
        if final_assignee_id:
            try:
                _maybe_send_assignee_invite(
                    client=client,
                    db=db,
                    slack_user_id=final_assignee_id,
                    assignee_name=final_assignee or final_assignee_id,
                    task_id=new_task.id,
                    task_title=extracted.task,
                    workspace_invite_code=invite_code,
                )
            except Exception as exc:
                # Onboarding DM failure must never block task creation
                logger.warning("Assignee invite DM failed (non-fatal): %s", exc)

        # ── Segment 5B: Prompt sender to invite teammates every 3rd task ──────
        if sender_id:
            try:
                _maybe_send_invite_teammate_prompt(
                    client=client,
                    db=db,
                    creator_slack_id=sender_id,
                    workspace_invite_code=invite_code,
                )
            except Exception as exc:
                logger.warning("Teammate invite prompt failed (non-fatal): %s", exc)

    except Exception as exc:
        db.rollback()
        logger.error("Failed to save task: %s", exc, exc_info=True)
        say(
            text=f"⚠️ Sorry, I couldn't save that task. Please try again. (Error: {exc})",
            thread_ts=thread_ts,
            channel=channel_id,
        )
    finally:
        db.close()


@bolt_app.event("message")
def handle_message_events(body, logger):
    """Silently acknowledge message events we don't need to process."""
    pass
