"""Request/response models for authentication endpoints."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.identity import EMAIL_RE
from app.security.passwords import WeakPasswordError, validate_password_strength


def _email(v: str) -> str:
    v = (v or "").strip().lower()
    if not EMAIL_RE.match(v) or len(v) > 320:
        raise ValueError("Invalid email address")
    return v


class RegisterRequest(BaseModel):
    email: str
    password: str
    full_name: Optional[str] = Field(default=None, max_length=200)

    _e = field_validator("email")(_email)

    @field_validator("password")
    @classmethod
    def _strong(cls, v: str) -> str:
        try:
            return validate_password_strength(v)
        except WeakPasswordError as exc:
            raise ValueError(str(exc))

    @field_validator("full_name")
    @classmethod
    def _name(cls, v):
        v = (v or "").strip()
        return v or None


class PasswordChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: str = Field(max_length=1024)
    new_password: str
    remember_me: bool = False

    @field_validator("new_password")
    @classmethod
    def _strong(cls, v: str) -> str:
        try:
            return validate_password_strength(v)
        except WeakPasswordError as exc:
            raise ValueError(str(exc))


class ActivityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    event_type: str
    ip: Optional[str]
    created_at: datetime


class LoginRequest(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=1024)
    remember_me: bool = False


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    email: str
    full_name: Optional[str]
    is_active: bool
    created_at: datetime
