"""
models.py
─────────
SQLAlchemy ORM models.

Status lifecycle: to_do → pending → active → completed / cancelled
"""

import enum
import secrets
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


# ── Enums ─────────────────────────────────────────────────────────────────────

class TaskStatus(str, enum.Enum):
    to_do       = "to_do"
    pending     = "pending"
    active      = "active"
    in_progress = "in_progress"
    completed   = "completed"
    cancelled   = "cancelled"


class Priority(str, enum.Enum):
    low      = "low"
    medium   = "medium"
    high     = "high"
    critical = "critical"


class UserRole(str, enum.Enum):
    architect = "architect"   # Manager  — sees ALL workspace tasks
    navigator = "navigator"   # Team Lead — sees their team tasks only
    operator  = "operator"    # Employee  — sees only tasks assigned to them
    solo      = "solo"        # Independent — no team, sees only own tasks


# ── Workspace ─────────────────────────────────────────────────────────────────

class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    invite_code: Mapped[str] = mapped_column(
        String(16), unique=True, nullable=False,
        default=lambda: secrets.token_urlsafe(8),
    )
    owner_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", use_alter=True, name="fk_workspace_owner"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    members: Mapped[list["User"]] = relationship(
        "User", back_populates="workspace", foreign_keys="User.workspace_id",
    )
    tasks: Mapped[list["Task"]] = relationship("Task", back_populates="workspace")
    settings: Mapped[Optional["WorkspaceSettings"]] = relationship(
        "WorkspaceSettings", back_populates="workspace", uselist=False,
    )

    def __repr__(self) -> str:
        return f"<Workspace id={self.id} name={self.name!r}>"


# ── WorkspaceSettings ─────────────────────────────────────────────────────────

class WorkspaceSettings(Base):
    """
    Per-workspace configuration for the priority/urgency engine.

    keyword_rules          — JSON list of {keyword, priority} dicts
    high_priority_channels — JSON list of Slack channel IDs that auto-set priority=high
    drift_alert_hours      — hours before unstarted High/Critical tasks trigger a drift alert
    owner_slack_id         — Slack user ID of the workspace architect (used for escalation DMs)
    """
    __tablename__ = "workspace_settings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id", name="fk_ws_settings_workspace"),
        nullable=False,
        unique=True,
    )

    keyword_rules: Mapped[Optional[list]] = mapped_column(
        JSON, nullable=True, default=list,
    )

    high_priority_channels: Mapped[Optional[list]] = mapped_column(
        JSON, nullable=True, default=list,
    )

    drift_alert_hours: Mapped[int] = mapped_column(
        Integer, nullable=False, default=24,
    )

    # Segment 3 — escalation DMs to workspace owner
    owner_slack_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    workspace: Mapped["Workspace"] = relationship(
        "Workspace", back_populates="settings",
    )

    def __repr__(self) -> str:
        return f"<WorkspaceSettings workspace_id={self.workspace_id}>"


# ── User ──────────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="userrole_enum", create_constraint=True),
        default=UserRole.operator,
        server_default=UserRole.operator.value,
        nullable=False,
    )
    team_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    workspace_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("workspaces.id", use_alter=True, name="fk_user_workspace"),
        nullable=True,
    )
    slack_user_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, unique=True)
    slack_team_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )

    workspace: Mapped[Optional["Workspace"]] = relationship(
        "Workspace", back_populates="members", foreign_keys=[workspace_id],
    )
    tasks: Mapped[list["Task"]] = relationship(
        "Task", back_populates="owner", foreign_keys="Task.owner_id",
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r} role={self.role}>"


# ── Task ──────────────────────────────────────────────────────────────────────

class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True, index=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    task_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    assignee: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    assignee_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    deadline: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    priority: Mapped[Priority] = mapped_column(
        Enum(Priority, name="priority_enum", create_constraint=True),
        default=Priority.medium,
        server_default=Priority.medium.value,
        nullable=False,
    )
    source_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    slack_channel_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    slack_message_ts: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, name="taskstatus_enum", create_constraint=True),
        default=TaskStatus.to_do,
        server_default=TaskStatus.to_do.value,
        nullable=False,
    )
    owner_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", use_alter=True, name="fk_task_owner"), nullable=True,
    )
    workspace_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("workspaces.id", use_alter=True, name="fk_task_workspace"), nullable=True,
    )

    # Segment 3 — follow-up ping tracking
    pinged_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    owner_pinged_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )

    owner: Mapped[Optional["User"]] = relationship(
        "User", back_populates="tasks", foreign_keys=[owner_id],
    )
    workspace: Mapped[Optional["Workspace"]] = relationship(
        "Workspace", back_populates="tasks",
    )

    __table_args__ = (
        Index("ix_tasks_owner_id",     "owner_id"),
        Index("ix_tasks_workspace_id", "workspace_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<Task id={self.id} title={self.title!r} "
            f"priority={self.priority} status={self.status}>"
        )


# ── Migration helper ──────────────────────────────────────────────────────────
MIGRATION_SQL = """
-- Run this once in Railway Query tab if columns don't auto-migrate:

ALTER TABLE tasks
    ADD COLUMN IF NOT EXISTS pinged_at       TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS owner_pinged_at TIMESTAMPTZ;

ALTER TABLE workspace_settings
    ADD COLUMN IF NOT EXISTS owner_slack_id VARCHAR(64);

-- Back-fill tasks with NULL status
UPDATE tasks
SET    status = 'to_do'
WHERE  status IS NULL
   OR  status NOT IN ('to_do', 'pending', 'active', 'in_progress', 'completed', 'cancelled');
"""
