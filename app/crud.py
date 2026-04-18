"""
crud.py
───────
All database read/write operations. Keeps business logic out of route handlers.
"""

import logging
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import Priority, Task, TaskStatus
from app.schemas import ExtractedTask, TaskStatusUpdate

logger = logging.getLogger(__name__)


def create_task(
    db: Session,
    source_message: str,
    extracted: ExtractedTask,
    slack_channel_id: Optional[str] = None,
    slack_message_ts: Optional[str] = None,
) -> Task:
    """Create and persist a new task from AI-extracted data."""
    task = Task(
        title=extracted.task,             # FIX 1: was missing — title is NOT NULL, caused silent crash
        task_description=extracted.task,  # legacy column kept in sync
        assignee=extracted.assignee,
        deadline=extracted.deadline,
        priority=extracted.priority or Priority.medium,
        source_message=source_message,
        status=TaskStatus.to_do,          # FIX 2: was TaskStatus.pending — frontend only shows to_do column
        slack_channel_id=slack_channel_id,
        slack_message_ts=slack_message_ts,
    )
    db.add(task)
    try:
        db.commit()                       # FIX 3: was db.flush() — flush never commits, task lost on session close
        db.refresh(task)
    except IntegrityError as exc:
        db.rollback()
        logger.error("IntegrityError creating task: %s", exc, exc_info=True)
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        logger.error("SQLAlchemyError creating task: %s", exc, exc_info=True)
        raise
    return task


def get_task(db: Session, task_id: int) -> Optional[Task]:
    """Fetch a single task by ID. Returns None if not found."""
    if task_id <= 0:
        return None
    return db.get(Task, task_id)


def list_tasks(
    db: Session,
    status: Optional[TaskStatus] = None,
    assignee: Optional[str] = None,
    priority: Optional[Priority] = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[int, list[Task]]:
    """
    List tasks with optional filters.

    Returns:
        (total_count, tasks_page) tuple for pagination.
    """
    skip = max(0, skip)
    limit = max(1, min(limit, 200))

    stmt = select(Task)

    if status is not None:
        stmt = stmt.where(Task.status == status)
    if assignee:
        stmt = stmt.where(Task.assignee.ilike(f"%{assignee.strip()}%"))
    if priority is not None:
        stmt = stmt.where(Task.priority == priority)

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total: int = db.scalar(count_stmt) or 0

    stmt = stmt.order_by(Task.created_at.desc()).offset(skip).limit(limit)
    tasks: list[Task] = list(db.scalars(stmt).all())

    return total, tasks


def update_task_status(
    db: Session, task_id: int, update: TaskStatusUpdate
) -> Optional[Task]:
    """Update the status of a task. Returns None if task not found."""
    task = db.get(Task, task_id)
    if not task:
        return None

    task.status = update.status
    try:
        db.commit()                       # FIX: was db.flush()
        db.refresh(task)
    except SQLAlchemyError as exc:
        db.rollback()
        logger.error("SQLAlchemyError updating task %d: %s", task_id, exc, exc_info=True)
        raise
    return task


def update_task(
    db: Session,
    task_id: int,
    **fields,
) -> Optional[Task]:
    """
    Partial update for arbitrary task fields.
    Only updates fields explicitly passed in kwargs.
    Returns None if task not found.
    """
    task = db.get(Task, task_id)
    if not task:
        return None

    allowed_fields = {
        "task_description", "assignee", "deadline",
        "priority", "status", "slack_channel_id", "slack_message_ts",
    }
    for key, value in fields.items():
        if key not in allowed_fields:
            logger.warning("update_task: ignoring unknown field %r", key)
            continue
        setattr(task, key, value)

    try:
        db.commit()                       # FIX: was db.flush()
        db.refresh(task)
    except SQLAlchemyError as exc:
        db.rollback()
        logger.error("SQLAlchemyError in update_task %d: %s", task_id, exc, exc_info=True)
        raise
    return task


def get_task_by_slack_ts(
    db: Session,
    slack_channel_id: str,
    slack_message_ts: str,
) -> Optional[Task]:
    """
    Look up a task by its originating Slack message.
    Used to deduplicate Slack event retries.
    """
    stmt = select(Task).where(
        Task.slack_channel_id == slack_channel_id,
        Task.slack_message_ts == slack_message_ts,
    )
    return db.scalars(stmt).first()
