from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from app.models.enums import Role
from app.models.identity import SLUG_RE
from app.schemas_auth import _email


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    slug: Optional[str] = Field(default=None, max_length=64)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name is required")
        return v

    @field_validator("slug")
    @classmethod
    def _slug(cls, v):
        if v is None:
            return v
        v = v.strip().lower()
        if not SLUG_RE.match(v):
            raise ValueError("Slug must be 2-63 chars: lowercase letters, digits, hyphens")
        return v


class WorkspaceOut(BaseModel):
    id: str
    name: str
    slug: str
    role: Role
    created_at: datetime


class WorkspaceContextOut(WorkspaceOut):
    permissions: List[str]


class MemberOut(BaseModel):
    user_id: str
    email: str
    full_name: Optional[str]
    role: Role


class MemberAdd(BaseModel):
    email: str
    role: Role = Role.MEMBER
    _e = field_validator("email")(_email)


class MemberRoleUpdate(BaseModel):
    role: Role
