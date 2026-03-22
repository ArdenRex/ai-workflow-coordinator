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
    pending = "pending"
    in_progress = "in_progress"
    completed = "completed"
    cancelled = "cancelled"


class Priority(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class Task(Base):
    __tablename__ = "tasks"

    # ── Primary key ───────────────────────────────────────────────────────────
    id: Mapped[int] = mapped_column(primary_key=True, index=True, autoincrement=True)

    # ── Core AI-extracted fields ──────────────────────────────────────────────
    task_description: Mapped[str] = mapped_column(Text, nullable=False)

    assignee: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Store as ISO-8601 string; nullable — AI may not extract a deadline
    deadline: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    priority: Mapped[Priority] = mapped_column(
        Enum(Priority, name="priority_enum", create_constraint=True),
        default=Priority.medium,
        server_default=Priority.medium.value,
        nullable=False,
    )

    # ── Source ────────────────────────────────────────────────────────────────
    source_message: Mapped[str] = mapped_column(Text, nullable=False)

    # Optional: Slack channel or message TS for traceability
    slack_channel_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    slack_message_ts: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # ── Status ────────────────────────────────────────────────────────────────
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, name="taskstatus_enum", create_constraint=True),
        default=TaskStatus.pending,
        server_default=TaskStatus.pending.value,
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

    # ── Composite indexes for common query patterns ───────────────────────────
    __table_args__ = (
        Index("ix_tasks_status", "status"),
        Index("ix_tasks_assignee", "assignee"),
        Index("ix_tasks_status_created_at", "status", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<Task id={self.id} assignee={self.assignee!r} "
            f"priority={self.priority} status={self.status}>"
        )
