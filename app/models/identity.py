"""Identity tables: users, workspaces, memberships (role per user per workspace).

Rules enforced here: emails are stored lowercase (DB check + validator), slugs are
URL-safe, one membership per (workspace, user), no cascading deletes (deactivate
instead; history must survive). Invariants that need queries (e.g. a workspace always
keeps at least one owner) live in the identity service (Step 4.3).
"""
import re
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin, str_enum, utcnow
from app.models.enums import Role

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("email = lower(email)", name="email_lowercase"),)

    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[Optional[str]] = mapped_column(String(255))
    full_name: Mapped[Optional[str]] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    token_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")      # 14.7: bumping it invalidates every token issued before

    memberships: Mapped[list["Membership"]] = relationship(back_populates="user")

    @validates("email")
    def _normalize_email(self, _key, value: str) -> str:
        value = (value or "").strip().lower()
        if not EMAIL_RE.match(value) or len(value) > 320:
            raise ValueError("Invalid email address")
        return value


class Workspace(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workspaces"

    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"))

    memberships: Mapped[list["Membership"]] = relationship(back_populates="workspace")

    @validates("slug")
    def _check_slug(self, _key, value: str) -> str:
        value = (value or "").strip().lower()
        if not SLUG_RE.match(value):
            raise ValueError("Invalid workspace slug")
        return value

    @validates("name")
    def _check_name(self, _key, value: str) -> str:
        value = (value or "").strip()
        if not value or len(value) > 120:
            raise ValueError("Invalid workspace name")
        return value


class Membership(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id", name="uq_memberships_workspace_user"),)

    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[Role] = mapped_column(str_enum(Role), default=Role.MEMBER)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    workspace: Mapped[Workspace] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="memberships")


class AuthEvent(UUIDPrimaryKeyMixin, Base):
    """Account activity (14.8): register, login, failed login, logout, password change. Not workspace-scoped (it is about the person);
    holds no email, password or token. `ip` is the direct peer address. A user only ever reads their own rows."""
    __tablename__ = "auth_events"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(32))
    ip: Mapped[Optional[str]] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
