"""Workspace policy record (Step 12.1): one row per workspace, changed only through PolicyService (compare-and-swap on version).

It stores ONLY tightening knobs and the autonomy level. Tool ids are not secrets; no free text is stored.
"""
from typing import Any, Dict, List, Optional

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class WorkspacePolicyRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workspace_policies"
    __table_args__ = (
        UniqueConstraint("workspace_id", name="uq_workspace_policies_workspace"),
        CheckConstraint("version >= 1", name="version_valid"),
        CheckConstraint("autonomy_level >= 1 AND autonomy_level <= 5", name="autonomy_level_valid"),
    )

    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"))
    updated_by: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    autonomy_level: Mapped[int] = mapped_column(Integer)
    disabled_tools: Mapped[List[Any]] = mapped_column(JSON, default=list)
    approval_required_tools: Mapped[List[Any]] = mapped_column(JSON, default=list)
    risk_overrides: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)   # tool id -> "medium" | "high" (tighten only)
    execution_limit: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True, default=None)  # {"max_executions", "window_seconds"} or null
    auto_execute_tools: Mapped[List[Any]] = mapped_column(JSON, default=list)   # level 4 only: tool ids allowed to run unattended
    approval_routing: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)   # risk level -> "owner" (decisions need an owner-only permission)
    escalation: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True, default=None)  # {"threshold", "window_seconds"} or null
