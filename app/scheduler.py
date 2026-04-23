"""
scheduler.py
------------
Background scheduler for follow-up pings on overdue tasks.

Runs every hour and:
  1. Finds High/Critical tasks still in To Do past the drift threshold
  2. Sends a Slack DM to the assignee (first ping)
  3. If still unstarted after 2× threshold, pings the workspace owner/architect too
  4. Stamps pinged_at / owner_pinged_at so we never double-ping

Requires APScheduler:
  pip install apscheduler
"""

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from app.config import get_settings
from app.database import SessionLocal
from app.models import Priority, Task, TaskStatus, WorkspaceSettings

logger = logging.getLogger(__name__)
settings = get_settings()

scheduler = AsyncIOScheduler(timezone="UTC")

# ── Slack client (reuse token from settings) ──────────────────────────────────
_slack_client: WebClient | None = None


def _get_slack_client() -> WebClient:
    global _slack_client
    if _slack_client is None:
        _slack_client = WebClient(token=settings.slack_bot_token.get_secret_value())
    return _slack_client


# ── DM helpers ────────────────────────────────────────────────────────────────

def _send_dm(user_id: str, text: str) -> bool:
    """
    Open a DM channel with user_id and send text.
    Returns True on success, False on failure.
    """
    client = _get_slack_client()
    try:
        convo = client.conversations_open(users=[user_id])
        dm_channel = convo["channel"]["id"]
        client.chat_postMessage(channel=dm_channel, text=text)
        logger.info("DM sent to user_id=%s", user_id)
        return True
    except SlackApiError as exc:
        logger.warning("Failed to DM user_id=%s: %s", user_id, exc.response["error"])
        return False


def _resolve_owner_id(db, workspace_id: str) -> str | None:
    """
    Return the Slack user ID of the workspace architect/owner, if stored.
    Falls back to None so we skip the owner ping gracefully.
    """
    ws: WorkspaceSettings | None = (
        db.query(WorkspaceSettings)
        .filter_by(workspace_id=workspace_id)
        .first()
    )
    if ws is None:
        return None
    return getattr(ws, "owner_slack_id", None)


# ── Core ping logic ────────────────────────────────────────────────────────────

def _ping_overdue_tasks() -> dict:
    """
    Synchronous job body — called by APScheduler every hour.

    Returns a summary dict (also used by the manual trigger endpoint).
    """
    db = SessionLocal()
    now = datetime.now(timezone.utc)
    assignee_pinged = 0
    owner_pinged = 0
    skipped = 0

    try:
        # Fetch all workspace settings so we know the drift threshold per workspace
        all_settings: list[WorkspaceSettings] = db.query(WorkspaceSettings).all()
        settings_map: dict[str, WorkspaceSettings] = {
            ws.workspace_id: ws for ws in all_settings
        }

        # Default threshold: 24 hours (used when no workspace settings exist)
        DEFAULT_THRESHOLD_HOURS = 24

        # Find High/Critical tasks still in To Do that have an assignee_id
        drifting_tasks: list[Task] = (
            db.query(Task)
            .filter(
                Task.status == TaskStatus.to_do,
                Task.priority.in_([Priority.high, Priority.critical]),
                Task.assignee_id.isnot(None),
            )
            .all()
        )

        logger.info("Ping job: found %d candidate drifting tasks", len(drifting_tasks))

        for task in drifting_tasks:
            ws_config = settings_map.get(task.workspace_id) if task.workspace_id else None
            threshold_hours = (
                ws_config.drift_threshold_hours
                if ws_config and hasattr(ws_config, "drift_threshold_hours")
                else DEFAULT_THRESHOLD_HOURS
            )

            # How long has this task been sitting?
            created_at = task.created_at
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)

            age_hours = (now - created_at).total_seconds() / 3600

            if age_hours < threshold_hours:
                skipped += 1
                continue  # Not overdue yet

            # ── First ping: assignee DM ────────────────────────────────────────
            if task.pinged_at is None:
                priority_label = (
                    task.priority.value
                    if hasattr(task.priority, "value")
                    else str(task.priority)
                ).capitalize()

                msg = (
                    f"⚠️ *Overdue Task Alert*\n"
                    f"Your *{priority_label}* priority task has been sitting in *To Do* "
                    f"for {int(age_hours)}h:\n"
                    f"📋 *{task.title}*\n"
                    f"Please update its status or reach out to your manager."
                )
                if _send_dm(task.assignee_id, msg):
                    task.pinged_at = now
                    assignee_pinged += 1

            # ── Second ping: owner DM at 2× threshold ─────────────────────────
            if age_hours >= threshold_hours * 2 and task.owner_pinged_at is None:
                owner_id = _resolve_owner_id(db, task.workspace_id) if task.workspace_id else None
                if owner_id:
                    priority_label = (
                        task.priority.value
                        if hasattr(task.priority, "value")
                        else str(task.priority)
                    ).capitalize()

                    owner_msg = (
                        f"🚨 *Escalation Alert*\n"
                        f"Task *{task.title}* (assigned to *{task.assignee}*) "
                        f"has been in *To Do* for {int(age_hours)}h — "
                        f"over 2× the {threshold_hours}h threshold.\n"
                        f"Priority: *{priority_label}* | Task ID: `{task.id}`"
                    )
                    if _send_dm(owner_id, owner_msg):
                        task.owner_pinged_at = now
                        owner_pinged += 1

        db.commit()
        summary = {
            "checked": len(drifting_tasks),
            "assignee_pinged": assignee_pinged,
            "owner_pinged": owner_pinged,
            "skipped_not_overdue": skipped,
            "ran_at": now.isoformat(),
        }
        logger.info("Ping job complete: %s", summary)
        return summary

    except Exception as exc:
        db.rollback()
        logger.exception("Ping job failed: %s", exc)
        return {"error": str(exc)}
    finally:
        db.close()


# ── APScheduler job wrapper ────────────────────────────────────────────────────

async def ping_overdue_tasks_job():
    """Async wrapper so APScheduler's AsyncIOScheduler can call the sync body."""
    import asyncio
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _ping_overdue_tasks)


# ── Public API used by main.py ─────────────────────────────────────────────────

def start_scheduler():
    """Register the hourly job and start the scheduler. Call on app startup."""
    scheduler.add_job(
        ping_overdue_tasks_job,
        trigger="interval",
        hours=1,
        id="ping_overdue_tasks",
        replace_existing=True,
        next_run_time=None,  # Don't run immediately on startup
    )
    scheduler.start()
    logger.info("Scheduler started — overdue ping job registered (hourly)")


def stop_scheduler():
    """Gracefully shut down the scheduler. Call on app shutdown."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")


def run_ping_now() -> dict:
    """
    Manual trigger — called by the /tasks/ping-overdue endpoint.
    Runs synchronously and returns the summary.
    """
    return _ping_overdue_tasks()
