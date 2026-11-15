"""WorkspaceContext: who is calling, in which workspace, as what role -> kernel Principal."""
from dataclasses import dataclass
from typing import FrozenSet, Optional

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database import get_db
from app.identity.roles import permissions_for
from app.kernel.permissions import Principal
from app.models.enums import Role
from app.models.identity import Membership, User, Workspace


@dataclass(frozen=True)
class WorkspaceContext:
    user: User
    workspace: Workspace
    membership: Membership

    @property
    def role(self) -> Role:
        return self.membership.role

    @property
    def permissions(self) -> FrozenSet[str]:
        return permissions_for(self.role)

    def principal(self, *, agent: Optional[str] = None,
                  agent_scope: Optional[FrozenSet[str]] = None) -> Principal:
        """The only way request identity becomes a kernel Principal."""
        return Principal(user_id=self.user.id, workspace_id=self.workspace.id,
                         permissions=self.permissions, agent=agent, agent_scope=agent_scope)


def load_context(db: Session, user: User, workspace_id: str) -> WorkspaceContext | None:
    row = db.execute(
        select(Membership, Workspace).join(Workspace, Workspace.id == Membership.workspace_id)
        .where(Membership.workspace_id == workspace_id, Membership.user_id == user.id,
               Membership.is_active.is_(True), Workspace.is_active.is_(True))).first()
    return WorkspaceContext(user, row[1], row[0]) if row else None


def get_workspace_context(workspace_id: str, user: User = Depends(get_current_user),
                          db: Session = Depends(get_db)) -> WorkspaceContext:
    """Any route with a {workspace_id} path parameter. Non-member, inactive membership,
    inactive workspace and nonexistent workspace all look identical (404): no existence leak."""
    ctx = load_context(db, user, workspace_id)
    if ctx is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found")
    return ctx


def require_permission(permission: str):
    def dep(ctx: WorkspaceContext = Depends(get_workspace_context)) -> WorkspaceContext:
        if not ctx.principal().can(permission):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
        return ctx
    return dep
