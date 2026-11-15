"""Orchestration records: one plan row + one row per step. Lifecycle records, not transcripts.

Neither the goal nor any step instruction is stored: only digests and lengths. The plan's structure (step keys,
agents, dependencies) is stored because scheduling and audit need it; it carries no user content. Status changes
only through PlanService (compare-and-swap), and every change writes a content-free audit event.
"""
from datetime import datetime
from typing import Any, List, Optional

from sqlalchemy import (JSON, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin, str_enum
from app.models.enums import PlanStatus, StepState


class PlanRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "orchestration_plans"
    __table_args__ = (
        UniqueConstraint("workspace_id", "idempotency_key", name="uq_orch_plans_workspace_idem"),
        Index("ix_orch_plans_workspace_status", "workspace_id", "status"),
        CheckConstraint("step_count >= 1", name="step_count_valid"),
    )

    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    requested_by: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[PlanStatus] = mapped_column(str_enum(PlanStatus), default=PlanStatus.PENDING)
    goal_digest: Mapped[str] = mapped_column(String(64))
    goal_chars: Mapped[int] = mapped_column(Integer)
    plan_digest: Mapped[str] = mapped_column(String(64))
    step_count: Mapped[int] = mapped_column(Integer)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(128))
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    result: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    error_code: Mapped[Optional[str]] = mapped_column(String(64))
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class PlanStepRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "plan_steps"
    __table_args__ = (
        UniqueConstraint("plan_id", "step_key", name="uq_plan_steps_key"),
        UniqueConstraint("run_id", name="uq_plan_steps_run"),          # one agent run serves at most one step
        CheckConstraint("position >= 0", name="position_valid"),
    )

    plan_id: Mapped[str] = mapped_column(ForeignKey("orchestration_plans.id"), index=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    step_key: Mapped[str] = mapped_column(String(32))
    position: Mapped[int] = mapped_column(Integer)
    agent_id: Mapped[str] = mapped_column(String(32))
    instruction_digest: Mapped[str] = mapped_column(String(64))
    instruction_chars: Mapped[int] = mapped_column(Integer)
    depends_on: Mapped[List[str]] = mapped_column(JSON, default=list)
    status: Mapped[StepState] = mapped_column(str_enum(StepState), default=StepState.PENDING)
    run_id: Mapped[Optional[str]] = mapped_column(ForeignKey("agent_runs.id"))
    result: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    error_code: Mapped[Optional[str]] = mapped_column(String(64))
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
