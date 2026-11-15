"""Execution-kernel tables: executions, approvals, system events (audit trail).

workspace_id is a foreign key to workspaces (Step 4.3): an execution, approval or audit
event can no longer exist for a workspace that doesn't. Every query must filter by it.
"""
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin, str_enum, utcnow
from app.models.enums import ApprovalStatus, ExecutionStatus, RiskLevel


_enum = str_enum


class ToolExecution(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "tool_executions"
    __table_args__ = (
        UniqueConstraint("workspace_id", "idempotency_key", name="uq_tool_executions_workspace_idem"),
        Index("ix_tool_executions_workspace_status", "workspace_id", "status"),
    )

    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    tool_id: Mapped[str] = mapped_column(String(128))
    requested_by: Mapped[str] = mapped_column(String(64))
    agent: Mapped[Optional[str]] = mapped_column(String(64))
    risk_level: Mapped[RiskLevel] = mapped_column(_enum(RiskLevel))
    status: Mapped[ExecutionStatus] = mapped_column(_enum(ExecutionStatus), default=ExecutionStatus.PENDING)
    input: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    error: Mapped[Optional[str]] = mapped_column(Text)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(128))
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    approvals: Mapped[list["Approval"]] = relationship(back_populates="execution")


class Approval(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "approvals"

    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    execution_id: Mapped[str] = mapped_column(ForeignKey("tool_executions.id"), index=True)
    status: Mapped[ApprovalStatus] = mapped_column(_enum(ApprovalStatus), default=ApprovalStatus.PENDING)
    requested_by: Mapped[str] = mapped_column(String(64))
    decided_by: Mapped[Optional[str]] = mapped_column(String(64))
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    reason: Mapped[Optional[str]] = mapped_column(Text)

    execution: Mapped[ToolExecution] = relationship(back_populates="approvals")


class SystemEvent(UUIDPrimaryKeyMixin, Base):
    """Append-only audit record. Never updated or deleted by application code."""
    __tablename__ = "system_events"
    __table_args__ = (Index("ix_system_events_workspace_created", "workspace_id", "created_at"),)

    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    actor: Mapped[Optional[str]] = mapped_column(String(64))
    execution_id: Mapped[Optional[str]] = mapped_column(ForeignKey("tool_executions.id"), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
