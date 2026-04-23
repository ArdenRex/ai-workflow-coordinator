"""
app/auth.py
───────────
JWT token creation, validation, and FastAPI dependencies.

Two token types:
  - access_token  → short-lived (30 min) — sent in Authorization header
  - refresh_token → long-lived (30 days) — issued when remember_me=True
                    stored in httpOnly cookie on frontend

Usage in route handlers:
    from app.auth import get_current_user
    
    @router.get("/me")
    def get_me(current_user: User = Depends(get_current_user)):
        return current_user
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Cookie, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import User

logger = logging.getLogger(__name__)
settings = get_settings()

# ── JWT config ────────────────────────────────────────────────────────────────
SECRET_KEY  = settings.app_secret_key.get_secret_value()
ALGORITHM   = settings.jwt_algorithm
ACCESS_EXPIRE_MINUTES = settings.jwt_access_token_expire_minutes
REFRESH_EXPIRE_DAYS   = settings.jwt_refresh_token_expire_days

# Bearer token extractor — reads Authorization: Bearer <token> header
bearer_scheme = HTTPBearer(auto_error=False)


# ── Token creation ────────────────────────────────────────────────────────────

def create_access_token(user_id: int) -> tuple[str, int]:
    """
    Create a short-lived JWT access token.

    Returns:
        (token_string, expires_in_seconds)
    """
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_EXPIRE_MINUTES)
    payload = {
        "sub":  str(user_id),
        "type": "access",
        "exp":  expire,
        "iat":  datetime.now(timezone.utc),
    }
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    return token, ACCESS_EXPIRE_MINUTES * 60


def create_refresh_token(user_id: int) -> str:
    """
    Create a long-lived JWT refresh token (for Remember Me).
    Should be stored in an httpOnly cookie on the frontend.
    """
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_EXPIRE_DAYS)
    payload = {
        "sub":  str(user_id),
        "type": "refresh",
        "exp":  expire,
        "iat":  datetime.now(timezone.utc),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """
    Decode and validate a JWT token.
    Raises HTTPException 401 if invalid or expired.
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError as exc:
        logger.warning("JWT decode failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is invalid or expired. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ── FastAPI dependencies ──────────────────────────────────────────────────────

def _extract_user_id(token: str, expected_type: str = "access") -> int:
    """
    Decode token, verify type, return user_id as int.
    """
    payload = decode_token(token)

    token_type = payload.get("type")
    if token_type != expected_type:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token type. Expected '{expected_type}'.",
        )

    user_id_str = payload.get("sub")
    if not user_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject claim.",
        )

    try:
        return int(user_id_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token subject is not a valid user ID.",
        )


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    refresh_token: Optional[str] = Cookie(default=None, alias="refresh_token"),
    db: Session = Depends(get_db),
) -> User:
    """
    FastAPI dependency — resolves the current authenticated user.

    Priority:
      1. Authorization: Bearer <access_token> header  (normal requests)
      2. refresh_token cookie                          (when access token expired + remember_me)

    Raises HTTP 401 if neither is present or both are invalid.
    """
    token = None
    token_type = "access"

    if credentials and credentials.credentials:
        token = credentials.credentials
        token_type = "access"
    elif refresh_token:
        token = refresh_token
        token_type = "refresh"

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Please log in.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = _extract_user_id(token, expected_type=token_type)

    user = db.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account not found. Please log in again.",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account has been deactivated.",
        )

    return user


def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    refresh_token: Optional[str] = Cookie(default=None, alias="refresh_token"),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """
    Same as get_current_user but returns None instead of raising 401.
    Used for endpoints that work both authenticated and unauthenticated.
    """
    try:
        return get_current_user(credentials, refresh_token, db)
    except HTTPException:
        return None


# ── Role guards ───────────────────────────────────────────────────────────────

def require_role(*allowed_roles):
    """
    Dependency factory — restricts endpoint to specific roles.

    Usage:
        @router.get("/admin")
        def admin_only(user = Depends(require_role("architect"))):
            ...
    """
    def _guard(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role.value not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Access denied. This action requires one of: "
                    f"{', '.join(allowed_roles)}. "
                    f"Your role is: {current_user.role.value}."
                ),
            )
        return current_user
    return _guard


# ── Convenience role dependencies ─────────────────────────────────────────────
# Use these directly in route handlers for clean code:
#   def my_route(user = Depends(require_architect)):

require_architect = require_role("architect")
require_navigator = require_role("architect", "navigator")
require_operator  = require_role("architect", "navigator", "operator")
# solo can only access their own routes — handled in the route itself
