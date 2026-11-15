"""Auth endpoints: register, login, me. Workspace creation/membership arrives in 4.3."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.config import Settings, get_settings
from app.database import get_db
from app.models.base import utcnow
from app.models.identity import AuthEvent, User
from app.schemas_auth import ActivityOut, LoginRequest, PasswordChangeRequest, RegisterRequest, TokenResponse, UserOut
from app.security.clientip import client_ip
from app.security.passwords import burn_verify, hash_password, needs_rehash, verify_password
from app.security.tokens import create_access_token

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

_BAD_LOGIN = HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password",
                           headers={"WWW-Authenticate": "Bearer"})


def _client_ip(request: Request) -> str:
    return client_ip(request)      # direct peer unless TRUSTED_PROXY_COUNT is set (see app/security/clientip.py)


def _too_many(wait: int) -> HTTPException:
    return HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts. Try again later.", headers={"Retry-After": str(wait)})


def _log(db: Session, user_id: str, event_type: str, request: Request) -> None:
    db.add(AuthEvent(user_id=user_id, event_type=event_type, ip=_client_ip(request)[:64]))


def _throttle_request(request: Request) -> None:
    wait = request.app.state.auth_throttle.check_request(_client_ip(request))
    if wait is not None:
        raise _too_many(wait)


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, request: Request, db: Session = Depends(get_db)) -> User:
    _throttle_request(request)
    if db.scalar(select(User).where(User.email == body.email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    user = User(email=body.email, password_hash=hash_password(body.password), full_name=body.full_name)
    db.add(user)
    try:
        db.flush()
        _log(db, user.id, "register", request)
        db.commit()
    except IntegrityError:                      # concurrent registration of the same email
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    logger.info("user registered", extra={"user_id": user.id})
    return user


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db),
          settings: Settings = Depends(get_settings)) -> TokenResponse:
    throttle, ip, email = request.app.state.auth_throttle, _client_ip(request), body.email.strip().lower()
    _throttle_request(request)
    wait = throttle.check_login(email, ip)      # before any password work: a locked key can't be used to test guesses
    if wait is not None:
        raise _too_many(wait)
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        burn_verify(body.password)              # equalize timing: unknown email vs wrong password
        throttle.record_failure(email, ip)
        raise _BAD_LOGIN
    ok = verify_password(body.password, user.password_hash)
    if not ok or not user.is_active:            # same response for wrong password and disabled account
        throttle.record_failure(email, ip)
        _log(db, user.id, "login_failed", request)
        db.commit()
        raise _BAD_LOGIN
    throttle.record_success(email, ip)
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
    user.last_login_at = utcnow()
    _log(db, user.id, "login", request)
    db.commit()
    token, ttl = create_access_token(settings, user.id, version=user.token_version or 0, remember=body.remember_me)
    return TokenResponse(access_token=token, expires_in=ttl)


@router.post("/logout", status_code=204)
def logout(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Response:
    """Invalidates EVERY token issued to this user so far (this device and others). Log in again for a new one."""
    db.execute(update(User).where(User.id == user.id).values(token_version=User.token_version + 1))   # atomic, no lost update
    _log(db, user.id, "logout", request)
    db.commit()
    return Response(status_code=204)


@router.post("/password", response_model=TokenResponse)
def change_password(body: PasswordChangeRequest, request: Request, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> TokenResponse:
    """Changes the password and invalidates every token issued so far (all devices); the response carries a fresh one for this caller."""
    throttle, ip = request.app.state.auth_throttle, _client_ip(request)
    _throttle_request(request)
    wait = throttle.check_login(user.email, ip)         # guessing the current password is throttled exactly like login
    if wait is not None:
        raise _too_many(wait)
    if not verify_password(body.current_password, user.password_hash):
        throttle.record_failure(user.email, ip)
        _log(db, user.id, "password_change_failed", request)
        db.commit()
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Current password is incorrect")
    if verify_password(body.new_password, user.password_hash):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "New password must differ from the current one")
    throttle.record_success(user.email, ip)
    db.execute(update(User).where(User.id == user.id).values(password_hash=hash_password(body.new_password),
                                                             token_version=User.token_version + 1))
    _log(db, user.id, "password_changed", request)
    db.commit()
    db.refresh(user)
    token, ttl = create_access_token(settings, user.id, version=user.token_version or 0, remember=body.remember_me)
    return TokenResponse(access_token=token, expires_in=ttl)


@router.get("/activity", response_model=list[ActivityOut])
def activity(limit: int = Query(50, ge=1, le=200), user: User = Depends(get_current_user),
             db: Session = Depends(get_db)) -> list[AuthEvent]:
    """The caller's own recent account activity, newest first."""
    return list(db.scalars(select(AuthEvent).where(AuthEvent.user_id == user.id)
                           .order_by(AuthEvent.created_at.desc(), AuthEvent.id).limit(limit)))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user
