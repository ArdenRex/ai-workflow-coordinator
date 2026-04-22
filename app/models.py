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
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


# ── Existing enums (unchanged) ────────────────────────────────────────────────

class TaskStatus(str, enum.Enum):
    to_do       = "to_do"        # ← default for Slack-created tasks
    pending     = "pending"
    active      = "active"       # kept for backwards-compat
    in_progress = "in_progress"  # ← used by frontend Start button
    completed   = "completed"
    cancelled   = "cancelled"


class Priority(str, enum.Enum):
    low      = "low"
    medium   = "medium"
    high     = "high"
    critical = "critical"


# ── NEW: User role enum ───────────────────────────────────────────────────────

class UserRole(str, enum.Enum):
    architect = "architect"   # Manager  — sees ALL workspace tasks
    navigator = "navigator"   # Team Lead — sees their team tasks only
    operator  = "operator"    # Employee  — sees only tasks assigned to them
    solo      = "solo"        # Independent — no team, sees only own tasks


# ── NEW: Workspace model ──────────────────────────────────────────────────────

class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Unique invite code — share this with teammates so they can join
    invite_code: Mapped[str] = mapped_column(
        String(16),
        unique=True,
        nullable=False,
        default=lambda: secrets.token_urlsafe(8),
    )

    # The user who created this workspace
    owner_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", use_alter=True, name="fk_workspace_owner"),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    members: Mapped[list["User"]] = relationship(
        "User",
        back_populates="workspace",
        foreign_keys="User.workspace_id",
    )
    tasks: Mapped[list["Task"]] = relationship(
        "Task",
        back_populates="workspace",
    )

    def __repr__(self) -> str:
        return f"<Workspace id={self.id} name={self.name!r} code={self.invite_code!r}>"


# ── NEW: User model ───────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Auth
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # null = Slack-only user

    # Profile
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Role
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="userrole_enum", create_constraint=True),
        default=UserRole.operator,
        server_default=UserRole.operator.value,
        nullable=False,
    )

    # Team name — used by navigator role to filter team tasks
    team_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Workspace membership
    workspace_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("workspaces.id", use_alter=True, name="fk_user_workspace"),
        nullable=True,
    )

    # Slack OAuth identity
    slack_user_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, unique=True)
    slack_team_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # Account flags
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

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

    # Relationships
    workspace: Mapped[Optional["Workspace"]] = relationship(
        "Workspace",
        back_populates="members",
        foreign_keys=[workspace_id],
    )
    tasks: Mapped[list["Task"]] = relationship(
        "Task",
        back_populates="owner",
        foreign_keys="Task.owner_id",
    )

    __table_args__ = (
        Index("ix_users_email",     "email"),
        Index("ix_users_workspace", "workspace_id"),
        Index("ix_users_slack_uid", "slack_user_id"),
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r} role={self.role}>"


# ── Existing Task model — only added owner_id + workspace_id ─────────────────

class Task(Base):
    __tablename__ = "tasks"

    # ── Primary key ───────────────────────────────────────────────────────────
    id: Mapped[int] = mapped_column(primary_key=True, index=True, autoincrement=True)

    # ── Core fields (unchanged) ───────────────────────────────────────────────
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

    # ── Source (unchanged) ────────────────────────────────────────────────────
    source_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    slack_channel_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    slack_message_ts: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # ── Status (unchanged) ────────────────────────────────────────────────────
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, name="taskstatus_enum", create_constraint=True),
        default=TaskStatus.to_do,
        server_default=TaskStatus.to_do.value,
        nullable=False,
    )

    # ── NEW: Ownership fields ─────────────────────────────────────────────────
    # Links task to the user who owns/created it
    owner_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", use_alter=True, name="fk_task_owner"),
        nullable=True,
    )

    # Scopes task to a workspace for role-based dashboard filtering
    workspace_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("workspaces.id", use_alter=True, name="fk_task_workspace"),
        nullable=True,
    )

    # ── Timestamps (unchanged) ────────────────────────────────────────────────
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

    # ── NEW: Relationships ────────────────────────────────────────────────────
    owner: Mapped[Optional["User"]] = relationship(
        "User",
        back_populates="tasks",
        foreign_keys=[owner_id],
    )
    workspace: Mapped[Optional["Workspace"]] = relationship(
        "Workspace",
        back_populates="tasks",
    )

    # ── Composite indexes ─────────────────────────────────────────────────────
    __table_args__ = (
        Index("ix_tasks_status",            "status"),
        Index("ix_tasks_assignee",          "assignee"),
        Index("ix_tasks_owner_id",          "owner_id"),        # NEW
        Index("ix_tasks_workspace_id",      "workspace_id"),    # NEW
        Index("ix_tasks_status_created_at", "status", "created_at"),
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


# ── Migration helper (unchanged) ──────────────────────────────────────────────
MIGRATION_SQL = """
-- 1. Add the new enum value if using PostgreSQL native ENUM
--    (skip if status column is plain VARCHAR)
-- ALTER TYPE taskstatus_enum ADD VALUE IF NOT EXISTS 'to_do';
-- ALTER TYPE taskstatus_enum ADD VALUE IF NOT EXISTS 'active';
-- ALTER TYPE taskstatus_enum ADD VALUE IF NOT EXISTS 'in_progress';

-- 2. Back-fill rows that have NULL or an unrecognised status
UPDATE tasks
SET    status = 'to_do'
WHERE  status IS NULL
   OR  status NOT IN ('to_do', 'pending', 'active', 'in_progress', 'completed', 'cancelled');
"""
