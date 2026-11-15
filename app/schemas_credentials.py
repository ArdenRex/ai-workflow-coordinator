import re
from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

PROVIDER_RE = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,63}$")
_SECRETISH = ("secret", "token", "password", "passwd", "api_key", "apikey", "api-key", "authorization",
              "credential", "private", "bearer")


def _check_secret(v: SecretStr) -> SecretStr:
    raw = v.get_secret_value()
    if not raw.strip() or len(raw) > 4096:
        raise ValueError("Secret must be 1-4096 characters and not blank")
    return v


class CredentialCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str
    name: str
    secret: SecretStr
    config: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("provider")
    @classmethod
    def _p(cls, v: str) -> str:
        v = v.strip().lower()
        if not PROVIDER_RE.match(v):
            raise ValueError("Provider must be 2-32 chars: lowercase letters, digits, - or _")
        return v

    @field_validator("name")
    @classmethod
    def _n(cls, v: str) -> str:
        v = v.strip()
        if not NAME_RE.match(v):
            raise ValueError("Name must be 1-64 chars: letters, digits, space, . _ -")
        return v

    _s = field_validator("secret")(_check_secret)

    @field_validator("config")
    @classmethod
    def _c(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        if len(v) > 20:
            raise ValueError("Too many config keys")
        for k, val in v.items():
            if any(s in k.lower() for s in _SECRETISH):
                raise ValueError("config is for non-secret metadata; put secrets in 'secret'")
            if not isinstance(val, (str, int, float, bool)) or (isinstance(val, str) and len(val) > 500):
                raise ValueError("config values must be short strings, numbers or booleans")
        return v


class CredentialRotate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    secret: SecretStr
    _s = field_validator("secret")(_check_secret)


class CredentialOut(BaseModel):
    """Deliberately has no secret or ciphertext field."""
    model_config = ConfigDict(from_attributes=True)
    id: str
    provider: str
    name: str
    config: Dict[str, Any]
    version: int
    is_active: bool
    created_at: datetime
    rotated_at: Optional[datetime]
    revoked_at: Optional[datetime]
    last_tested_at: Optional[datetime] = None
    last_test_ok: Optional[bool] = None
    last_test_message: Optional[str] = None


class ConnectionTestOut(BaseModel):
    ok: bool
    message: str
    provider: str
    capabilities: list[str]
    tested_at: Optional[datetime]
