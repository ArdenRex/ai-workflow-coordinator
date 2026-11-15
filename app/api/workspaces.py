"""Workspace + membership endpoints. Every {workspace_id} route resolves identity through
get_workspace_context / require_permission; nothing here trusts a client-supplied role."""
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database import get_db
from app.identity.context import WorkspaceContext, get_workspace_context, require_permission
from app.identity.service import (AlreadyMemberError, IdentityError, IdentityService, LastOwnerError,
                                  MemberNotFoundError, RoleNotPermittedError, SlugTakenError, UserNotFoundError)
from app.models.identity import Membership, User
from app.schemas_workspace import (MemberAdd, MemberOut, MemberRoleUpdate, WorkspaceContextOut,
                                   WorkspaceCreate, WorkspaceOut)

router = APIRouter(prefix="/workspaces", tags=["workspaces"])

_STATUS = {SlugTakenError: 409, AlreadyMemberError: 409, LastOwnerError: 409, UserNotFoundError: 404,
           MemberNotFoundError: 404, RoleNotPermittedError: 403}


def _http(exc: IdentityError) -> HTTPException:
    return HTTPException(_STATUS.get(type(exc), 400), str(exc))


def _ws_out(m: Membership) -> dict:
    w = m.workspace
    return dict(id=w.id, name=w.name, slug=w.slug, role=m.role, created_at=w.created_at)


@router.post("", response_model=WorkspaceOut, status_code=status.HTTP_201_CREATED)
def create_workspace(body: WorkspaceCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        return _ws_out(IdentityService(db).create_workspace(user, body.name, body.slug))
    except IdentityError as exc:
        raise _http(exc)


@router.get("", response_model=list[WorkspaceOut])
def list_workspaces(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [_ws_out(m) for m in IdentityService(db).list_for_user(user)]


@router.get("/{workspace_id}", response_model=WorkspaceContextOut)
def get_workspace(ctx: WorkspaceContext = Depends(get_workspace_context)):
    w = ctx.workspace
    return dict(id=w.id, name=w.name, slug=w.slug, role=ctx.role, created_at=w.created_at,
                permissions=sorted(ctx.permissions))


@router.get("/{workspace_id}/members", response_model=list[MemberOut])
def list_members(ctx: WorkspaceContext = Depends(require_permission("workspace:read")),
                 db: Session = Depends(get_db)):
    return [dict(user_id=u.id, email=u.email, full_name=u.full_name, role=m.role)
            for m, u in IdentityService(db).list_members(ctx)]


def _member_out(m: Membership, db: Session) -> dict:
    u = db.get(User, m.user_id)
    return dict(user_id=u.id, email=u.email, full_name=u.full_name, role=m.role)


@router.post("/{workspace_id}/members", response_model=MemberOut, status_code=status.HTTP_201_CREATED)
def add_member(body: MemberAdd, ctx: WorkspaceContext = Depends(require_permission("member:manage")),
               db: Session = Depends(get_db)):
    try:
        return _member_out(IdentityService(db).add_member(ctx, body.email, body.role), db)
    except IdentityError as exc:
        raise _http(exc)


@router.patch("/{workspace_id}/members/{user_id}", response_model=MemberOut)
def change_role(user_id: str, body: MemberRoleUpdate,
                ctx: WorkspaceContext = Depends(require_permission("member:manage")),
                db: Session = Depends(get_db)):
    try:
        return _member_out(IdentityService(db).change_role(ctx, user_id, body.role), db)
    except IdentityError as exc:
        raise _http(exc)


@router.delete("/{workspace_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(user_id: str, ctx: WorkspaceContext = Depends(require_permission("member:manage")),
                  db: Session = Depends(get_db)):
    try:
        IdentityService(db).remove_member(ctx, user_id)
    except IdentityError as exc:
        raise _http(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
