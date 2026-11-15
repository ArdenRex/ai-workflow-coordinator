"""Workspace and membership rules (the invariants that need queries).

Rules: creator becomes OWNER atomically; an actor may only grant or change roles at or
below their own rank and only touch members at or below their rank (so admins can't touch
owners); a workspace always keeps at least one active owner; memberships are deactivated,
never deleted; every change is audited in the same transaction.
"""
import re
import secrets

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.identity.context import WorkspaceContext
from app.identity.roles import outranks_or_equals
from app.kernel.audit import record_event
from app.models.enums import Role
from app.models.identity import SLUG_RE, Membership, User, Workspace


class IdentityError(Exception):
    pass


class SlugTakenError(IdentityError): ...
class UserNotFoundError(IdentityError): ...
class MemberNotFoundError(IdentityError): ...
class AlreadyMemberError(IdentityError): ...
class RoleNotPermittedError(IdentityError): ...
class LastOwnerError(IdentityError): ...


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40].strip("-")
    return s if SLUG_RE.match(s) else "workspace"


class IdentityService:
    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------ workspaces
    def create_workspace(self, user: User, name: str, slug: str | None = None) -> Membership:
        explicit = slug is not None
        base = slug if explicit else slugify(name)
        for attempt in range(4):
            candidate = base if attempt == 0 else f"{base[:55]}-{secrets.token_hex(2)}"
            try:
                ws = Workspace(name=name, slug=candidate, created_by=user.id)
                self.db.add(ws)
                self.db.flush()
                m = Membership(workspace_id=ws.id, user_id=user.id, role=Role.OWNER)
                self.db.add(m)
                record_event(self.db, workspace_id=ws.id, event_type="workspace.created", actor=user.id,
                             payload={"slug": ws.slug})
                self.db.commit()
                return m
            except IntegrityError:
                self.db.rollback()
                if explicit:
                    raise SlugTakenError("Slug already in use")
        raise SlugTakenError("Could not allocate a unique slug")

    def list_for_user(self, user: User) -> list[Membership]:
        return list(self.db.scalars(
            select(Membership).join(Workspace, Workspace.id == Membership.workspace_id)
            .where(Membership.user_id == user.id, Membership.is_active.is_(True), Workspace.is_active.is_(True))
            .order_by(Workspace.created_at)))

    # ------------------------------------------------------------ members
    def list_members(self, ctx: WorkspaceContext) -> list[tuple[Membership, User]]:
        return list(self.db.execute(
            select(Membership, User).join(User, User.id == Membership.user_id)
            .where(Membership.workspace_id == ctx.workspace.id, Membership.is_active.is_(True))
            .order_by(Membership.created_at)).all())

    def add_member(self, ctx: WorkspaceContext, email: str, role: Role) -> Membership:
        self._may_grant(ctx, role)
        user = self.db.scalar(select(User).where(User.email == email.strip().lower(), User.is_active.is_(True)))
        if user is None:
            raise UserNotFoundError("User not found")
        m = self._membership(ctx.workspace.id, user.id, for_update=True)
        if m is not None and m.is_active:
            raise AlreadyMemberError("User is already a member")
        if m is None:
            m = Membership(workspace_id=ctx.workspace.id, user_id=user.id, role=role)
            self.db.add(m)
        else:                                   # reactivate a previously removed member
            m.is_active, m.role = True, role
        record_event(self.db, workspace_id=ctx.workspace.id, event_type="member.added", actor=ctx.user.id,
                     payload={"user_id": user.id, "role": role.value})
        self._commit_or(AlreadyMemberError("User is already a member"))
        return m

    def change_role(self, ctx: WorkspaceContext, user_id: str, role: Role) -> Membership:
        m = self._active_member(ctx, user_id)
        self._may_grant(ctx, role)
        self._may_touch(ctx, m)
        if m.role == Role.OWNER and role != Role.OWNER:
            self._ensure_other_owner(ctx.workspace.id, user_id)
        old, m.role = m.role, role
        record_event(self.db, workspace_id=ctx.workspace.id, event_type="member.role_changed",
                     actor=ctx.user.id, payload={"user_id": user_id, "from": old.value, "to": role.value})
        self.db.commit()
        return m

    def remove_member(self, ctx: WorkspaceContext, user_id: str) -> None:
        m = self._active_member(ctx, user_id)
        self._may_touch(ctx, m)
        if m.role == Role.OWNER:
            self._ensure_other_owner(ctx.workspace.id, user_id)
        m.is_active = False
        record_event(self.db, workspace_id=ctx.workspace.id, event_type="member.removed",
                     actor=ctx.user.id, payload={"user_id": user_id})
        self.db.commit()

    # ------------------------------------------------------------ helpers
    def _membership(self, ws_id: str, user_id: str, for_update: bool = False) -> Membership | None:
        q = select(Membership).where(Membership.workspace_id == ws_id, Membership.user_id == user_id)
        return self.db.scalar(q.with_for_update() if for_update else q)

    def _active_member(self, ctx: WorkspaceContext, user_id: str) -> Membership:
        m = self._membership(ctx.workspace.id, user_id, for_update=True)
        if m is None or not m.is_active:
            raise MemberNotFoundError("Member not found")
        return m

    @staticmethod
    def _may_grant(ctx: WorkspaceContext, role: Role) -> None:
        if not outranks_or_equals(ctx.role, role):
            raise RoleNotPermittedError("Cannot grant a role above your own")

    @staticmethod
    def _may_touch(ctx: WorkspaceContext, target: Membership) -> None:
        if not outranks_or_equals(ctx.role, target.role):
            raise RoleNotPermittedError("Cannot modify a member above your own role")

    def _ensure_other_owner(self, ws_id: str, leaving_user_id: str) -> None:
        # Lock all active owner rows (no-op on SQLite) so two concurrent demotions can't both pass.
        owners = self.db.scalars(select(Membership).where(
            Membership.workspace_id == ws_id, Membership.role == Role.OWNER,
            Membership.is_active.is_(True)).with_for_update()).all()
        if not any(o.user_id != leaving_user_id for o in owners):
            raise LastOwnerError("A workspace must keep at least one owner")

    def _commit_or(self, exc: IdentityError) -> None:
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            raise exc
