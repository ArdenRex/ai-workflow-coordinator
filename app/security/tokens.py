"""Signed access tokens (HS256 JWT via PyJWT).

The signing key is derived from APP_SECRET_KEY with a purpose label, so the same root
secret can later also feed credential encryption (4.4) without key reuse.
"""
import hashlib
import hmac
import uuid
from datetime import datetime, timedelta, timezone

import jwt

from app.config import Settings

ALGORITHM = "HS256"
TOKEN_TYPE = "access"


class InvalidTokenError(Exception):
    """Token missing, malformed, expired, or otherwise untrusted. Message is never user-facing."""


def derive_key(settings: Settings, purpose: str) -> bytes:
    return hmac.new(settings.app_secret_key.encode(), f"aceden-ai-os:{purpose}".encode(), hashlib.sha256).digest()


def create_access_token(settings: Settings, user_id: str, now: datetime | None = None, version: int = 0,
                        remember: bool = False) -> tuple[str, int]:
    now = now or datetime.now(timezone.utc)
    ttl = timedelta(days=settings.remember_me_ttl_days) if remember else timedelta(minutes=settings.access_token_ttl_minutes)
    claims = {
        "sub": user_id, "typ": TOKEN_TYPE, "iss": settings.jwt_issuer,
        "iat": int(now.timestamp()), "exp": int((now + ttl).timestamp()), "jti": uuid.uuid4().hex, "tv": int(version),
    }
    token = jwt.encode(claims, derive_key(settings, "jwt"), algorithm=ALGORITHM)
    return token, int(ttl.total_seconds())


def decode_access_token(settings: Settings, token: str) -> str:
    """Returns the user id (sub) or raises InvalidTokenError."""
    return decode_access_claims(settings, token)[0]


def decode_access_claims(settings: Settings, token: str) -> tuple[str, int]:
    """Returns (user id, token version) or raises InvalidTokenError. A token without a version claim counts as version 0."""
    try:
        claims = jwt.decode(
            token, derive_key(settings, "jwt"), algorithms=[ALGORITHM],   # pinned: no 'none', no RS/HS confusion
            issuer=settings.jwt_issuer, options={"require": ["exp", "iat", "sub", "iss"]},
        )
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(type(exc).__name__) from exc
    sub = claims.get("sub")
    if claims.get("typ") != TOKEN_TYPE or not isinstance(sub, str) or not sub:
        raise InvalidTokenError("bad claims")
    tv = claims.get("tv", 0)
    if isinstance(tv, bool) or not isinstance(tv, int) or tv < 0:
        raise InvalidTokenError("bad claims")
    return sub, tv
