"""Memory records. Unlike plans and runs, memory IS content (that is its job), so title/content are stored, but:
- workspace-scoped (FK) and, for preferences, owned by one user (DB check: preference <=> owner);
- content is never kept longer than it is live: superseded, deleted and expired rows have title/content/tags PURGED
  and keep only metadata (ids, kind, source, versions, timestamps) for provenance and audit;
- at most one ACTIVE row per `dedupe_key` (unique with NULL when inactive), so repeated writes cannot pile up.
All changes go through MemoryService (compare-and-swap + content-free audit).
"""
from datetime import datetime
from typing import List, Optional

from sqlalchemy import (JSON, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.memory.model import MemoryKind, SourceKind
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin, str_enum
from app.models.enums import MemoryStatus


class MemoryRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "memory_items"
    __table_args__ = (
        UniqueConstraint("workspace_id", "dedupe_key", name="uq_memory_workspace_dedupe"),
        Index("ix_memory_workspace_status_kind", "workspace_id", "status", "kind"),
        CheckConstraint("version >= 1", name="version_valid"),
        CheckConstraint("(kind = 'preference') = (owner_user_id IS NOT NULL)", name="preference_owner"),
    )

    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    kind: Mapped[MemoryKind] = mapped_column(str_enum(MemoryKind))
    status: Mapped[MemoryStatus] = mapped_column(str_enum(MemoryStatus), default=MemoryStatus.ACTIVE)
    title: Mapped[str] = mapped_column(String(120))                 # "" once purged
    content: Mapped[str] = mapped_column(Text)                      # "" once purged
    tags: Mapped[List[str]] = mapped_column(JSON, default=list)     # [] once purged
    content_chars: Mapped[int] = mapped_column(Integer)
    content_digest: Mapped[str] = mapped_column(String(64))
    dedupe_key: Mapped[Optional[str]] = mapped_column(String(160))  # set only while ACTIVE
    source_kind: Mapped[SourceKind] = mapped_column(str_enum(SourceKind))
    source_ref: Mapped[str] = mapped_column(String(200))
    source_label: Mapped[Optional[str]] = mapped_column(String(120))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    owner_user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), index=True)
    scope_ref: Mapped[Optional[str]] = mapped_column(String(200))
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))      # the human principal (or the user an agent acts for)
    created_by_agent: Mapped[Optional[str]] = mapped_column(String(32))
    version: Mapped[int] = mapped_column(Integer, default=1)
    lineage_id: Mapped[str] = mapped_column(String(36), index=True)      # id of the first version
    supersedes_id: Mapped[Optional[str]] = mapped_column(String(36))
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    ended_by: Mapped[Optional[str]] = mapped_column(String(36))
