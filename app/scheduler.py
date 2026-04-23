"""
scheduler.py
------------
Background scheduler for:
  - Segment 3: Follow-up pings on overdue/drifting High/Critical tasks (hourly)
  - Segment 4: Daily "Due Today" rollup DMs at 9 AM UTC (daily)

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
from app.models import Priority, Task, TaskStatus, User, WorkspaceSettings

logger = logging.getLogger(__name__)
settings = get_settings()

scheduler = AsyncIOScheduler(timezone="UTC")

# ── Slack client ──────────────────────────────────────────────────────────────
_slack_client: WebClient | None = None


def _get_slack_client() -> WebClient:
    global _slack_client
    if _slack_client is None:
        _slack_client = WebClient(token=settings.slack_bot_token.get_secret_value())
    return _slack_client


# ── DM helper ─────────────────────────────────────────────────────────────────

def _send_dm(user_id: str, text: str) -> bool:
    """Open a DM channel with user_id and send text. Returns True on success."""
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


def _resolve_owner_id(db, workspace_id: int) -> str | None:
    """Return the Slack user ID of the workspace architect/owner, if stored."""
    ws: WorkspaceSettings | None = (
        db.query(WorkspaceSettings)
        .filter_by(workspace_id=workspace_id)
        .first()
    )
    if ws is None:
        return None
    return getattr(ws, "owner_slack_id", None)


# ── Segment 3: Overdue ping job ───────────────────────────────────────────────

def _ping_overdue_tasks() -> dict:
    """
    Synchronous job body — runs every hour.
    Finds drifting High/Critical tasks and DMs assignees + owners.
    Returns a summary dict (also used by the manual trigger endpoint).
    """
    db = SessionLocal()
    now = datetime.now(timezone.utc)
    assignee_pinged = 0
    owner_pinged = 0
    skipped = 0

    try:
        all_settings: list[WorkspaceSettings] = db.query(WorkspaceSettings).all()
        settings_map: dict[int, WorkspaceSettings] = {
            ws.workspace_id: ws for ws in all_settings
        }

        DEFAULT_THRESHOLD_HOURS = 24

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

            created_at = task.created_at
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)

            age_hours = (now - created_at).total_seconds() / 3600

            if age_hours < threshold_hours:
                skipped += 1
                continue

            # First ping: assignee DM
            if task.pinged_at is None:
                priority_label = (
                    task.priority.value if hasattr(task.priority, "value") else str(task.priority)
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

            # Second ping: owner DM at 2× threshold
            if age_hours >= threshold_hours * 2 and task.owner_pinged_at is None:
                owner_id = _resolve_owner_id(db, task.workspace_id) if task.workspace_id else None
                if owner_id:
                    priority_label = (
                        task.priority.value if hasattr(task.priority, "value") else str(task.priority)
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


# ── Segment 4: Daily rollup job ───────────────────────────────────────────────

def _daily_rollup() -> dict:
    """
    Synchronous job body — runs once daily at 09:00 UTC.

    For each user with tasks due today:
      → DMs them: "X tasks due today (Y high-priority)"

    For each manager/architect in each workspace:
      → DMs them: team overdue high-priority task summary

    Returns a summary dict (also used by the manual trigger endpoint).
    """
    from app import crud  # inline to avoid circular imports

    db = SessionLocal()
    now = datetime.now(timezone.utc)
    user_dms_sent = 0
    manager_dms_sent = 0

    try:
        # ── Part 1: Per-user "Due Today" DMs ─────────────────────────────────
        users_with_tasks: list[User] = crud.get_all_active_users_with_tasks_due_today(db)

        logger.info("Daily rollup: %d users have tasks due today", len(users_with_tasks))

        for user in users_with_tasks:
            tasks = crud.get_tasks_due_today_for_user(db, user.id)
            if not tasks:
                continue

            high_count = sum(
                1 for t in tasks
                if t.priority in (Priority.high, Priority.critical)
            )
            total_count = len(tasks)

            # Build task list lines (max 10 shown to keep DM readable)
            task_lines = []
            for t in tasks[:10]:
                priority_label = (
                    t.priority.value if hasattr(t.priority, "value") else str(t.priority)
                ).capitalize()
                task_lines.append(f"  • [{priority_label}] {t.title}")
            if total_count > 10:
                task_lines.append(f"  _...and {total_count - 10} more_")

            tasks_block = "\n".join(task_lines)
            high_note = f" *(including {high_count} high-priority)*" if high_count else ""

            msg = (
                f"📅 *Good morning! Here's your daily task rollup:*\n"
                f"You have *{total_count} task(s) due today*{high_note}:\n\n"
                f"{tasks_block}\n\n"
                f"Stay on top of it — you've got this! 💪"
            )

            if _send_dm(user.slack_user_id, msg):
                user_dms_sent += 1

        # ── Part 2: Per-manager overdue summary DMs ───────────────────────────
        workspace_ids: list[int] = crud.get_all_workspace_ids(db)

        for ws_id in workspace_ids:
            overdue_tasks = crud.get_overdue_high_priority_tasks_for_workspace(db, ws_id)
            if not overdue_tasks:
                continue

            managers: list[User] = crud.get_managers_for_workspace(db, ws_id)
            if not managers:
                continue

            # Build overdue task summary lines (max 15)
            task_lines = []
            for t in overdue_tasks[:15]:
                priority_label = (
                    t.priority.value if hasattr(t.priority, "value") else str(t.priority)
                ).capitalize()
                deadline_str = str(t.deadline) if t.deadline else "no deadline"
                task_lines.append(
                    f"  • [{priority_label}] *{t.title}* — assigned to {t.assignee or 'unassigned'} (due {deadline_str})"
                )
            if len(overdue_tasks) > 15:
                task_lines.append(f"  _...and {len(overdue_tasks) - 15} more_")

            tasks_block = "\n".join(task_lines)

            manager_msg = (
                f"🚨 *Team Overdue Summary — {now.strftime('%b %d, %Y')}*\n"
                f"Your workspace has *{len(overdue_tasks)} overdue high-priority task(s)*:\n\n"
                f"{tasks_block}\n\n"
                f"Please follow up with your team to unblock these."
            )

            for manager in managers:
                if _send_dm(manager.slack_user_id, manager_msg):
                    manager_dms_sent += 1

        summary = {
            "user_dms_sent": user_dms_sent,
            "manager_dms_sent": manager_dms_sent,
            "workspaces_checked": len(workspace_ids),
            "ran_at": now.isoformat(),
        }
        logger.info("Daily rollup complete: %s", summary)
        return summary

    except Exception as exc:
        db.rollback()
        logger.exception("Daily rollup job failed: %s", exc)
        return {"error": str(exc)}
    finally:
        db.close()


# ── APScheduler async wrappers ────────────────────────────────────────────────

async def ping_overdue_tasks_job():
    """Async wrapper for Segment 3 hourly ping job."""
    import asyncio
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _ping_overdue_tasks)


async def daily_rollup_job():
    """Async wrapper for Segment 4 daily rollup job."""
    import asyncio
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _daily_rollup)


# ── Public API used by main.py ─────────────────────────────────────────────────

def start_scheduler():
    """Register all jobs and start the scheduler. Call on app startup."""
    # Segment 3: hourly overdue ping
    scheduler.add_job(
        ping_overdue_tasks_job,
        trigger="interval",
        hours=1,
        id="ping_overdue_tasks",
        replace_existing=True,
        next_run_time=None,  # Don't run immediately on startup
    )

    # Segment 4: daily rollup at 09:00 UTC
    scheduler.add_job(
        daily_rollup_job,
        trigger="cron",
        hour=9,
        minute=0,
        id="daily_rollup",
        replace_existing=True,
    )

    scheduler.start()
    logger.info(
        "Scheduler started — overdue ping job (hourly) + daily rollup job (09:00 UTC) registered"
    )


def stop_scheduler():
    """Gracefully shut down the scheduler. Call on app shutdown."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")


def run_ping_now() -> dict:
    """Manual trigger for Segment 3 — called by POST /tasks/ping-overdue."""
    return _ping_overdue_tasks()


def run_daily_rollup_now() -> dict:
    """Manual trigger for Segment 4 — called by POST /tasks/daily-rollup."""
    return _daily_rollup()
