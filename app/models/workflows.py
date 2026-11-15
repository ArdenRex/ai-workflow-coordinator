"""Workflow records: immutable versioned definitions, runs of a definition, and one row per step of a run.

Definitions DO store their text (instructions are the template and were secret-filtered on the way in); a version
is never edited, a change is a new version. Runs and steps are lifecycle records: they store ids, states, attempt
counts, timing and fixed error codes, never instructions, inputs or agent output beyond a redacted, capped summary.
Status changes only through WorkflowService (compare-and-swap), and every change writes a content-free audit event.
"""
from datetime import datetime
from typing import Any, List, Optional

from sqlalchemy import (JSON, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin, str_enum
from app.models.enums import StepState, WorkflowRunStatus, WorkflowStatus


class WorkflowRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workflow_definitions"
    __table_args__ = (
        UniqueConstraint("workspace_id", "workflow_key", "version", name="uq_wf_defs_key_version"),
        Index("ix_wf_defs_workspace_key", "workspace_id", "workflow_key"),
        CheckConstraint("version >= 1", name="version_valid"),
    )

    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    workflow_key: Mapped[str] = mapped_column(String(40))
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[WorkflowStatus] = mapped_column(str_enum(WorkflowStatus), default=WorkflowStatus.ACTIVE)
    name: Mapped[str] = mapped_column(String(100))
    definition: Mapped[dict[str, Any]] = mapped_column(JSON)
    definition_digest: Mapped[str] = mapped_column(String(64))
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class WorkflowRunRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workflow_runs"
    __table_args__ = (
        UniqueConstraint("workspace_id", "idempotency_key", name="uq_wf_runs_workspace_idem"),
        UniqueConstraint("workspace_id", "workflow_key", "trigger_type", "trigger_ref", name="uq_wf_runs_trigger_ref"),
        Index("ix_wf_runs_workspace_status", "workspace_id", "status"),
        CheckConstraint("step_count >= 1", name="step_count_valid"),
    )

    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    requested_by: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    definition_id: Mapped[str] = mapped_column(ForeignKey("workflow_definitions.id"), index=True)
    workflow_key: Mapped[str] = mapped_column(String(40))
    version: Mapped[int] = mapped_column(Integer)
    definition_digest: Mapped[str] = mapped_column(String(64))
    status: Mapped[WorkflowRunStatus] = mapped_column(str_enum(WorkflowRunStatus), default=WorkflowRunStatus.PENDING)
    trigger_type: Mapped[str] = mapped_column(String(16))
    trigger_ref: Mapped[Optional[str]] = mapped_column(String(128))     # event id / schedule slot; dedupes starts
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(128))
    step_count: Mapped[int] = mapped_column(Integer)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    result: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    error_code: Mapped[Optional[str]] = mapped_column(String(64))
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class WorkflowStepRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workflow_run_steps"
    __table_args__ = (
        UniqueConstraint("run_id", "step_key", name="uq_wf_steps_key"),
        UniqueConstraint("agent_run_id", name="uq_wf_steps_agent_run"),   # one agent run serves at most one step
        CheckConstraint("position >= 0", name="position_valid"),
        CheckConstraint("attempts >= 0", name="attempts_valid"),
    )

    run_id: Mapped[str] = mapped_column(ForeignKey("workflow_runs.id"), index=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    step_key: Mapped[str] = mapped_column(String(32))
    position: Mapped[int] = mapped_column(Integer)
    agent_id: Mapped[str] = mapped_column(String(32))
    depends_on: Mapped[List[str]] = mapped_column(JSON, default=list)
    status: Mapped[StepState] = mapped_column(str_enum(StepState), default=StepState.PENDING)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=1)
    timeout_seconds: Mapped[int] = mapped_column(Integer)
    next_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))   # set while waiting to retry
    deadline_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))       # set while an attempt runs
    agent_run_id: Mapped[Optional[str]] = mapped_column(ForeignKey("agent_runs.id"))       # the CURRENT attempt's run
    result: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    error_code: Mapped[Optional[str]] = mapped_column(String(64))
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class WorkflowEventRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An internal event that may start workflows. Content-free by design: a type, an emitter-chosen reference used
    to dedupe redelivery, and counts. There is deliberately NO payload (event data would be untrusted input to
    prompts; carrying it is a separate, later decision)."""
    __tablename__ = "workflow_events"
    __table_args__ = (
        UniqueConstraint("workspace_id", "event_type", "event_ref", name="uq_wf_events_ref"),
        CheckConstraint("matched_count >= 0 AND started_count >= 0 AND skipped_count >= 0", name="counts_valid"),
    )

    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    emitted_by: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(140))
    event_ref: Mapped[str] = mapped_column(String(128))
    matched_count: Mapped[int] = mapped_column(Integer, default=0)
    started_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    truncated: Mapped[bool] = mapped_column(Boolean, default=False)
    dispatched_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class WorkflowScheduleRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An armed interval trigger. Runs it starts belong to `armed_by`, whose permissions are re-checked at every fire.
    Slots are deterministic (next_fire_at), so a repeated or concurrent tick cannot start the same slot twice."""
    __tablename__ = "workflow_schedules"
    __table_args__ = (
        UniqueConstraint("workspace_id", "workflow_key", "interval_seconds", name="uq_wf_schedules_key_interval"),
        Index("ix_wf_schedules_due", "enabled", "next_fire_at"),
        CheckConstraint("interval_seconds >= 60", name="interval_valid"),
        CheckConstraint("fired_count >= 0 AND skipped_count >= 0", name="counts_valid"),
    )

    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    armed_by: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    workflow_key: Mapped[str] = mapped_column(String(40))
    interval_seconds: Mapped[int] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    next_fire_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_fired_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    fired_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    disabled_reason: Mapped[Optional[str]] = mapped_column(String(32))
