"""Encrypted external-system credentials, one row per credential per workspace.

The secret exists only as AES-GCM ciphertext (secret_ciphertext). `config` holds NON-secret
connection metadata (e.g. a base URL) and is validated to reject secret-looking keys.
Revoking keeps the row (history/audit) but erases the ciphertext.
"""
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class Credential(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "credentials"
    __table_args__ = (UniqueConstraint("workspace_id", "provider", "name", name="uq_credentials_workspace_provider_name"),)

    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    provider: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(64))
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    secret_ciphertext: Mapped[Optional[str]] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    rotated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    # Connection status (Step 4.5): result of the last connection test. Message is a safe code.
    last_tested_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_test_ok: Mapped[Optional[bool]] = mapped_column(Boolean)
    last_test_message: Mapped[Optional[str]] = mapped_column(String(64))

    def __repr__(self) -> str:                     # never include the ciphertext
        return f"<Credential {self.provider}/{self.name} v{self.version} active={self.is_active}>"
