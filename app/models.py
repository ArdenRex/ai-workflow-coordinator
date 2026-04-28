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

    # Segment 11 — integration credentials (Notion / Jira / Trello)
    integration_config: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True, default=dict,
        comment="Stores integration credentials: Notion / Jira / Trello",
    )

    # Segment 12 — workspace-level locale defaults (overridden per user)
    default_language: Mapped[Optional[str]] = mapped_column(String(10), nullable=True, default="en")
    default_timezone: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, default="UTC")
    default_currency: Mapped[Optional[str]] = mapped_column(String(8), nullable=True, default="USD")

    # Segment 9 — Microsoft Teams integration
    teams_tenant_id: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True,
        comment="Azure AD tenant ID — links workspace to a Teams organisation",
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

    # Segment 12 — per-user locale preferences
    language: Mapped[Optional[str]] = mapped_column(String(10), nullable=True, default="en")
    timezone: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, default="UTC")
    currency: Mapped[Optional[str]] = mapped_column(String(8), nullable=True, default="USD")

    # Segment 15 — Billing / Lemon Squeezy
    trial_ends_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    subscription_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="trialing", server_default="trialing",
    )
    ls_customer_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    ls_subscription_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

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
    onboarding: Mapped[Optional["OnboardingProgress"]] = relationship(
        "OnboardingProgress", back_populates="user", uselist=False,
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

    # ── Segment 8: public share token ────────────────────────────────────────
    share_token: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True, unique=True, index=True,
        default=lambda: secrets.token_urlsafe(16),
    )

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


# ── OnboardingProgress (Segment 7) ────────────────────────────────────────────

class OnboardingProgress(Base):
    """
    Tracks the 5-step guided onboarding checklist per user.

    Steps:
        1  slack_connected    — Slack OAuth completed
        2  first_command_sent — User sent their first bot mention / task command
        3  dashboard_viewed   — User opened their dashboard at least once
        4  teammate_invited   — User sent at least one workspace invite
        5  completed          — All 4 steps done; checklist is dismissed

    completed_at is set automatically when all 4 action steps are done.
    """
    __tablename__ = "onboarding_progress"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", name="fk_onboarding_user"),
        nullable=False,
        unique=True,
    )

    # Step 1 — Connect Slack
    slack_connected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    slack_connected_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # Step 2 — Send first command
    first_command_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    first_command_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # Step 3 — View dashboard
    dashboard_viewed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    dashboard_viewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # Step 4 — Invite a teammate
    teammate_invited: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    teammate_invited_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # Completion
    is_completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )

    user: Mapped["User"] = relationship("User", back_populates="onboarding")

    # ── helpers ───────────────────────────────────────────────────────────────

    @property
    def steps_completed(self) -> int:
        """Count of the 4 action steps completed (0–4)."""
        return sum([
            self.slack_connected,
            self.first_command_sent,
            self.dashboard_viewed,
            self.teammate_invited,
        ])

    @property
    def total_steps(self) -> int:
        return 4

    @property
    def progress_label(self) -> str:
        """e.g. '3/4 steps to full setup'"""
        return f"{self.steps_completed}/{self.total_steps} steps to full setup"

    def mark_complete_if_done(self) -> None:
        """Call after updating any step flag — auto-marks completion."""
        if self.steps_completed == self.total_steps and not self.is_completed:
            self.is_completed = True
            self.completed_at = datetime.utcnow()

    def __repr__(self) -> str:
        return (
            f"<OnboardingProgress user_id={self.user_id} "
            f"steps={self.steps_completed}/{self.total_steps} "
            f"completed={self.is_completed}>"
        )




# ── TeamsChannel (Segment 9) ──────────────────────────────────────────────────

class TeamsChannel(Base):
    """
    Stores registered Microsoft Teams channels for proactive notifications.
    One workspace can have multiple channels registered.
    """
    __tablename__ = "teams_channels"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id", name="fk_teams_channel_workspace"),
        nullable=False,
        index=True,
    )

    channel_id: Mapped[str] = mapped_column(
        String(255), nullable=False,
        comment="Teams channel ID from Bot Framework activity",
    )

    channel_name: Mapped[str] = mapped_column(
        String(255), nullable=False,
    )

    service_url: Mapped[str] = mapped_column(
        String(512), nullable=False,
        comment="Bot Connector Service URL for this Teams region",
    )

    conversation_id: Mapped[str] = mapped_column(
        String(512), nullable=False,
        comment="Conversation ID for sending proactive messages",
    )

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    __table_args__ = (
        Index("ix_teams_channels_workspace_id", "workspace_id"),
    )

    def __repr__(self) -> str:
        return f"<TeamsChannel id={self.id} name={self.channel_name!r} workspace_id={self.workspace_id}>"



# ── ApiKey (Segment 13) ───────────────────────────────────────────────────────

class ApiKey(Base):
    """
    Workspace-scoped API keys for the public REST API.
    The actual key value is hashed — only key_prefix is stored in plaintext
    for display purposes.
    """
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id", name="fk_api_key_workspace"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(
        String(255), nullable=False,
        comment="Human-readable label, e.g. Notion Integration",
    )

    key_hash: Mapped[str] = mapped_column(
        String(128), nullable=False, unique=True,
        comment="SHA-256 hash of the raw API key",
    )

    key_prefix: Mapped[str] = mapped_column(
        String(16), nullable=False,
        comment="First 8 chars of the raw key shown in UI, e.g. sk_live_ab",
    )

    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", name="fk_api_key_creator"), nullable=True,
    )

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    __table_args__ = (
        Index("ix_api_keys_workspace_id", "workspace_id"),
    )

    def __repr__(self) -> str:
        return f"<ApiKey id={self.id} prefix={self.key_prefix!r} workspace_id={self.workspace_id}>"
# ── Feedback (Segment 14) ─────────────────────────────────────────────────────

class FeedbackType(str, enum.Enum):
    bug            = "bug"
    feedback       = "feedback"
    feature_request = "feature_request"


class FeedbackStatus(str, enum.Enum):
    new         = "new"
    in_review   = "in_review"
    resolved    = "resolved"


class Feedback(Base):
    """
    User-submitted feedback, bug reports, and feature requests.
    Stored in DB and triggers an email alert to the workspace owner.
    """
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    type: Mapped[FeedbackType] = mapped_column(
        Enum(FeedbackType, name="feedbacktype_enum", create_constraint=True),
        nullable=False,
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)

    message: Mapped[str] = mapped_column(Text, nullable=False)

    # Optional: which page/section the user was on
    page_context: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    # Submitted by (nullable — could be anonymous)
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", name="fk_feedback_user"), nullable=True,
    )
    user_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    user_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    status: Mapped[FeedbackStatus] = mapped_column(
        Enum(FeedbackStatus, name="feedbackstatus_enum", create_constraint=True),
        default=FeedbackStatus.new,
        server_default=FeedbackStatus.new.value,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    __table_args__ = (
        Index("ix_feedback_user_id", "user_id"),
        Index("ix_feedback_type", "type"),
        Index("ix_feedback_status", "status"),
    )

    def __repr__(self) -> str:
        return f"<Feedback id={self.id} type={self.type} status={self.status}>"


# ── Migration helper ──────────────────────────────────────────────────────────
MIGRATION_SQL = """
-- Run this once in Railway Query tab if columns don't auto-migrate:

ALTER TABLE tasks
    ADD COLUMN IF NOT EXISTS pinged_at       TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS owner_pinged_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS share_token     VARCHAR(32) UNIQUE;

ALTER TABLE workspace_settings
    ADD COLUMN IF NOT EXISTS owner_slack_id VARCHAR(64);

-- Segment 11 — integration credentials
ALTER TABLE workspace_settings
    ADD COLUMN IF NOT EXISTS integration_config JSONB DEFAULT '{}';

-- Segment 12 — locale preferences
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS language VARCHAR(10) DEFAULT 'en',
    ADD COLUMN IF NOT EXISTS timezone VARCHAR(64) DEFAULT 'UTC',
    ADD COLUMN IF NOT EXISTS currency VARCHAR(8)  DEFAULT 'USD';

ALTER TABLE workspace_settings
    ADD COLUMN IF NOT EXISTS default_language VARCHAR(10) DEFAULT 'en',
    ADD COLUMN IF NOT EXISTS default_timezone VARCHAR(64) DEFAULT 'UTC',
    ADD COLUMN IF NOT EXISTS default_currency VARCHAR(8)  DEFAULT 'USD';

-- Segment 7 — onboarding progress table
CREATE TABLE IF NOT EXISTS onboarding_progress (
    id                     SERIAL PRIMARY KEY,
    user_id                INTEGER NOT NULL UNIQUE REFERENCES users(id),
    slack_connected        BOOLEAN NOT NULL DEFAULT FALSE,
    slack_connected_at     TIMESTAMPTZ,
    first_command_sent     BOOLEAN NOT NULL DEFAULT FALSE,
    first_command_sent_at  TIMESTAMPTZ,
    dashboard_viewed       BOOLEAN NOT NULL DEFAULT FALSE,
    dashboard_viewed_at    TIMESTAMPTZ,
    teammate_invited       BOOLEAN NOT NULL DEFAULT FALSE,
    teammate_invited_at    TIMESTAMPTZ,
    is_completed           BOOLEAN NOT NULL DEFAULT FALSE,
    completed_at           TIMESTAMPTZ,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Back-fill tasks with NULL status
UPDATE tasks
SET    status = 'to_do'
WHERE  status IS NULL
   OR  status NOT IN ('to_do', 'pending', 'active', 'in_progress', 'completed', 'cancelled');

-- Segment 9 — Microsoft Teams integration
ALTER TABLE workspace_settings
    ADD COLUMN IF NOT EXISTS teams_tenant_id VARCHAR(128);

CREATE TABLE IF NOT EXISTS teams_channels (
    id              SERIAL PRIMARY KEY,
    workspace_id    INTEGER NOT NULL REFERENCES workspaces(id),
    channel_id      VARCHAR(255) NOT NULL,
    channel_name    VARCHAR(255) NOT NULL,
    service_url     VARCHAR(512) NOT NULL,
    conversation_id VARCHAR(512) NOT NULL,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_teams_channels_workspace_id ON teams_channels(workspace_id);

-- Segment 13 — Public API keys
CREATE TABLE IF NOT EXISTS api_keys (
    id           SERIAL PRIMARY KEY,
    workspace_id INTEGER NOT NULL REFERENCES workspaces(id),
    name         VARCHAR(255) NOT NULL,
    key_hash     VARCHAR(128) NOT NULL UNIQUE,
    key_prefix   VARCHAR(16)  NOT NULL,
    created_by   INTEGER REFERENCES users(id),
    is_active    BOOLEAN NOT NULL DEFAULT TRUE,
    last_used_at TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_api_keys_workspace_id ON api_keys(workspace_id);

-- Segment 14 — Feedback & Request system
CREATE TABLE IF NOT EXISTS feedback (
    id           SERIAL PRIMARY KEY,
    type         VARCHAR(32)  NOT NULL,
    title        VARCHAR(255) NOT NULL,
    message      TEXT         NOT NULL,
    page_context VARCHAR(128),
    user_id      INTEGER REFERENCES users(id),
    user_email   VARCHAR(255),
    user_name    VARCHAR(255),
    status       VARCHAR(32)  NOT NULL DEFAULT 'new',
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_feedback_user_id ON feedback(user_id);
CREATE INDEX IF NOT EXISTS ix_feedback_type    ON feedback(type);
CREATE INDEX IF NOT EXISTS ix_feedback_status  ON feedback(status);
"""
