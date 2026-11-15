"""Shared API dependencies. get_current_user is the only way endpoints learn who is calling."""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.models.identity import User
from app.security.tokens import InvalidTokenError, decode_access_claims

_bearer = HTTPBearer(auto_error=False)


def _unauthorized() -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated", headers={"WWW-Authenticate": "Bearer"})


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    if creds is None or creds.scheme.lower() != "bearer":
        raise _unauthorized()
    try:
        user_id, version = decode_access_claims(settings, creds.credentials)
    except InvalidTokenError:
        raise _unauthorized()
    user = db.get(User, user_id)
    if user is None or not user.is_active or (user.token_version or 0) != version:     # deactivated users and logged-out tokens lose access immediately
        raise _unauthorized()
    return user
