"""
models.py
─────────
SQLAlchemy ORM models.

Status lifecycle: to_do → pending → active → completed / cancelled
"""

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    Enum,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TaskStatus(str, enum.Enum):
    to_do      = "to_do"       # ← default for Slack-created tasks
    pending    = "pending"
    active     = "active"
    completed  = "completed"
    cancelled  = "cancelled"


class Priority(str, enum.Enum):
    low      = "low"
    medium   = "medium"
    high     = "high"
    critical = "critical"


class Task(Base):
    __tablename__ = "tasks"

    # ── Primary key ───────────────────────────────────────────────────────────
    id: Mapped[int] = mapped_column(primary_key=True, index=True, autoincrement=True)

    # ── Core fields ───────────────────────────────────────────────────────────
    title: Mapped[str] = mapped_column(String(500), nullable=False)

    # Legacy column kept for backwards-compat; prefer `title`
    task_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    assignee: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    assignee_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # Store as ISO-8601 string; nullable — AI may not extract a deadline
    deadline: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    priority: Mapped[Priority] = mapped_column(
        Enum(Priority, name="priority_enum", create_constraint=True),
        default=Priority.medium,
        server_default=Priority.medium.value,
        nullable=False,
    )

    # ── Source ────────────────────────────────────────────────────────────────
    source_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Slack traceability fields
    slack_channel_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    slack_message_ts: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # ── Status ────────────────────────────────────────────────────────────────
    # FIX: default changed from "pending" → "to_do"
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, name="taskstatus_enum", create_constraint=True),
        default=TaskStatus.to_do,
        server_default=TaskStatus.to_do.value,
        nullable=False,
    )

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # ── Composite indexes ─────────────────────────────────────────────────────
    __table_args__ = (
        Index("ix_tasks_status",            "status"),
        Index("ix_tasks_assignee",          "assignee"),
        Index("ix_tasks_status_created_at", "status", "created_at"),
        # Idempotency: unique on (slack_channel_id, slack_message_ts) so the
        # same Slack message can never produce two rows.
        Index(
            "uq_tasks_slack_msg",
            "slack_channel_id",
            "slack_message_ts",
            unique=True,
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<Task id={self.id} title={self.title!r} "
            f"assignee={self.assignee!r} priority={self.priority} status={self.status}>"
        )


# ── Migration helper (run once, outside normal app startup) ───────────────────
MIGRATION_SQL = """
-- 1. Add the new enum value if using PostgreSQL native ENUM
--    (skip if status column is plain VARCHAR)
-- ALTER TYPE taskstatus_enum ADD VALUE IF NOT EXISTS 'to_do';
-- ALTER TYPE taskstatus_enum ADD VALUE IF NOT EXISTS 'active';

-- 2. Back-fill rows that have NULL or an unrecognised status
UPDATE tasks
SET    status = 'to_do'
WHERE  status IS NULL
   OR  status NOT IN ('to_do', 'pending', 'active', 'completed', 'cancelled');
"""
