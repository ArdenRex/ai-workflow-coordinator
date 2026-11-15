"""Agent runs: one row per attempt by an agent to work on a goal for a user in a workspace.

The row is a lifecycle record, not a transcript: the goal text is never stored (only a digest and its
length), and `result` / `error_code` are bounded and content-free by service rules. Status changes only
through AgentRunService (compare-and-swap), and every change writes an audit event.
"""
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (JSON, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin, str_enum
from app.models.enums import AgentRunStatus


class AgentRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        UniqueConstraint("workspace_id", "idempotency_key", name="uq_agent_runs_workspace_idem"),
        Index("ix_agent_runs_workspace_status", "workspace_id", "status"),
        CheckConstraint("max_steps >= 1 AND max_tool_calls >= 0 AND max_llm_calls >= 0", name="limits_valid"),
        CheckConstraint("steps_used >= 0 AND steps_used <= max_steps", name="steps_in_budget"),
        CheckConstraint("tool_calls_used >= 0 AND tool_calls_used <= max_tool_calls", name="tool_calls_in_budget"),
        CheckConstraint("llm_calls_used >= 0 AND llm_calls_used <= max_llm_calls", name="llm_calls_in_budget"),
    )

    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    agent_id: Mapped[str] = mapped_column(String(32))
    requested_by: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[AgentRunStatus] = mapped_column(str_enum(AgentRunStatus), default=AgentRunStatus.QUEUED)
    goal_digest: Mapped[str] = mapped_column(String(64))
    goal_chars: Mapped[int] = mapped_column(Integer)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(128))

    max_steps: Mapped[int] = mapped_column(Integer)
    max_tool_calls: Mapped[int] = mapped_column(Integer)
    max_llm_calls: Mapped[int] = mapped_column(Integer)
    steps_used: Mapped[int] = mapped_column(Integer, default=0)
    tool_calls_used: Mapped[int] = mapped_column(Integer, default=0)
    llm_calls_used: Mapped[int] = mapped_column(Integer, default=0)

    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    pending_execution_id: Mapped[Optional[str]] = mapped_column(ForeignKey("tool_executions.id"))
    result: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    error_code: Mapped[Optional[str]] = mapped_column(String(64))

    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
