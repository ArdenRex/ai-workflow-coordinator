"""
app/routers/auth.py
────────────────────
Authentication endpoints.

POST /auth/register          → Step 1: create account (email + password)
POST /auth/onboarding        → Step 2+3: choose role + create/join workspace
POST /auth/login             → Email + password login
POST /auth/logout            → Clear refresh token cookie
GET  /auth/me                → Get current logged-in user profile
GET  /auth/slack/login       → Begin Slack OAuth login flow
GET  /auth/slack/callback    → Slack OAuth callback (login or register via Slack)
POST /auth/refresh           → Exchange refresh token for new access token
GET  /auth/claim             → Segment 5: claim an assigned task + auto-join workspace
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
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import IntegrityError
from fastapi import Cookie, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app import crud
from app.auth import (
    create_access_token,
    create_refresh_token,
    get_current_user,
    decode_token,
)
from app.config import get_settings
from app.database import get_db
from app.models import User, UserRole
from app.schemas import (
    LoginRequest,
    OnboardingRequest,
    OnboardingResponse,
    RegisterRequest,
    RegisterResponse,
    TokenResponse,
    UserResponse,
    WorkspaceResponse,
)
from app.models import User

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/auth", tags=["Auth"])
# ── JWT config ────────────────────────────────────────────────────────────────
SECRET_KEY  = settings.app_secret_key.get_secret_value()
ALGORITHM   = settings.jwt_algorithm
ACCESS_EXPIRE_MINUTES = settings.jwt_access_token_expire_minutes
REFRESH_EXPIRE_DAYS   = settings.jwt_refresh_token_expire_days

# ── Env vars ──────────────────────────────────────────────────────────────────
SLACK_CLIENT_ID     = os.getenv("SLACK_CLIENT_ID", "")
SLACK_CLIENT_SECRET = os.getenv("SLACK_CLIENT_SECRET", "")
BACKEND_URL         = os.getenv("BACKEND_URL", "").rstrip("/")
FRONTEND_URL        = os.getenv("FRONTEND_URL", "").rstrip("/")
SLACK_REDIRECT_URI  = f"{BACKEND_URL}/auth/slack/callback"
# Bearer token extractor — reads Authorization: Bearer <token> header
bearer_scheme = HTTPBearer(auto_error=False)

SLACK_USER_SCOPES = "identity.basic,identity.email,identity.avatar"

# Cookie settings
COOKIE_NAME     = "refresh_token"
COOKIE_MAX_AGE  = 60 * 60 * 24 * 30   # 30 days in seconds
COOKIE_HTTPONLY = True
COOKIE_SAMESITE = "lax"
COOKIE_SECURE   = os.getenv("APP_ENV", "development") == "production"
# ── Token creation ────────────────────────────────────────────────────────────

def create_access_token(user_id: int) -> tuple[str, int]:
    """
    Create a short-lived JWT access token.

def _set_refresh_cookie(response: Response, token: str) -> None:
    """Attach the refresh token as an httpOnly cookie."""
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=COOKIE_MAX_AGE,
        httponly=COOKIE_HTTPONLY,
        samesite=COOKIE_SAMESITE,
        secure=COOKIE_SECURE,
    )


def _clear_refresh_cookie(response: Response) -> None:
    """Remove the refresh token cookie."""
    response.delete_cookie(key=COOKIE_NAME, samesite=COOKIE_SAMESITE)

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

# ── Step 1: Register ──────────────────────────────────────────────────────────

@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new account",
)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> RegisterResponse:
def decode_token(token: str) -> dict:
    """
    Creates a new user account with email + password.
    After this, the frontend should redirect to /onboarding.
    Decode and validate a JWT token.
    Raises HTTPException 401 if invalid or expired.
    """
    existing = crud.get_user_by_email(db, payload.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists. Please log in.",
        )

    try:
        user = crud.create_user(
            db=db,
            name=payload.name,
            email=payload.email,
            password=payload.password,
        )
    except IntegrityError:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError as exc:
        logger.warning("JWT decode failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is invalid or expired. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    logger.info("New user registered: id=%d email=%s", user.id, user.email)

    return RegisterResponse(
        message="Account created. Please complete onboarding.",
        user=UserResponse.model_validate(user),
    )


# ── Step 2+3: Onboarding ──────────────────────────────────────────────────────
# ── FastAPI dependencies ──────────────────────────────────────────────────────

@router.post(
    "/onboarding",
    response_model=OnboardingResponse,
    summary="Complete role + workspace setup",
)
def onboarding(
    payload: OnboardingRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OnboardingResponse:
def _extract_user_id(token: str, expected_type: str = "access") -> int:
    """
    Called after registration to set:
      - Role (architect / navigator / operator / solo)
      - Team name (navigator only)
      - Workspace: create new OR join existing via invite code

    Solo users skip workspace entirely.
    Decode token, verify type, return user_id as int.
    """
    workspace = None

    if payload.role == UserRole.solo:
        workspace_id = None
    elif payload.create_workspace:
        if not payload.workspace_name:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="workspace_name is required when creating a new workspace.",
            )
        workspace = crud.create_workspace(
            db=db,
            name=payload.workspace_name,
            owner_id=current_user.id,
        )
        workspace_id = workspace.id
    else:
        if not payload.invite_code:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="invite_code is required when joining an existing workspace.",
            )
        workspace = crud.get_workspace_by_invite_code(db, payload.invite_code)
        if not workspace:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Invalid invite code. Please check and try again.",
            )
        workspace_id = workspace.id

    updated_user = crud.update_user_onboarding(
        db=db,
        user_id=current_user.id,
        role=payload.role,
        team_name=payload.team_name,
        workspace_id=workspace_id,
    )
    payload = decode_token(token)

    if not updated_user:
    token_type = payload.get("type")
    if token_type != expected_type:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token type. Expected '{expected_type}'.",
        )

    if workspace_id and not workspace:
        workspace = crud.get_workspace_by_id(db, workspace_id)

    logger.info(
        "Onboarding complete: user_id=%d role=%s workspace_id=%s",
        updated_user.id, updated_user.role, workspace_id,
    )

    return OnboardingResponse(
        message="Onboarding complete. Welcome aboard!",
        user=UserResponse.model_validate(updated_user),
        workspace=WorkspaceResponse.model_validate(workspace) if workspace else None,
    )


# ── Login ─────────────────────────────────────────────────────────────────────

@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Login with email + password",
)
def login(
    payload: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> TokenResponse:
    user = crud.authenticate_user(db, payload.email, payload.password)
    if not user:
    user_id_str = payload.get("sub")
    if not user_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
            detail="Token missing subject claim.",
        )

    if not user.is_active:
    try:
        return int(user_id_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account has been deactivated.",
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token subject is not a valid user ID.",
        )

    access_token, expires_in = create_access_token(user.id)

    if payload.remember_me:
        refresh_token = create_refresh_token(user.id)
        _set_refresh_cookie(response, refresh_token)

    logger.info(
        "User logged in: id=%d email=%s remember_me=%s",
        user.id, user.email, payload.remember_me,
    )

    return TokenResponse(
        access_token=access_token,
        expires_in=expires_in,
        remember_me=payload.remember_me,
        user=UserResponse.model_validate(user),
    )


# ── Logout ────────────────────────────────────────────────────────────────────

@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Logout — clears refresh token cookie",
)
def logout(response: Response) -> None:
    """Clears the refresh token cookie. Frontend should also discard the access token."""
    _clear_refresh_cookie(response)
    logger.info("User logged out — refresh cookie cleared.")


# ── Me ────────────────────────────────────────────────────────────────────────
def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    refresh_token: Optional[str] = Cookie(default=None, alias="refresh_token"),
    db: Session = Depends(get_db),
) -> User:
    """
    FastAPI dependency — resolves the current authenticated user.

@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current user profile",
)
def get_me(current_user: User = Depends(get_current_user)) -> UserResponse:
    """Returns the profile of the currently logged-in user."""
    return UserResponse.model_validate(current_user)
    Priority:
      1. Authorization: Bearer <access_token> header  (normal requests)
      2. refresh_token cookie                          (when access token expired + remember_me)

    Raises HTTP 401 if neither is present or both are invalid.
    """
    token = None
    token_type = "access"

# ── Refresh token → new access token ─────────────────────────────────────────
    if credentials and credentials.credentials:
        token = credentials.credentials
        token_type = "access"
    elif refresh_token:
        token = refresh_token
        token_type = "refresh"

@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Get a new access token using the refresh token cookie",
)
def refresh_access_token(
    response: Response,
    refresh_token: str = Cookie(default=None, alias="refresh_token"),
    db: Session = Depends(get_db),
) -> TokenResponse:
    if not refresh_token:
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No refresh token found. Please log in again.",
            detail="Not authenticated. Please log in.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_token(refresh_token)
    if payload.get("type") != "refresh":
    user_id = _extract_user_id(token, expected_type=token_type)

    user = db.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type.",
            detail="User account not found. Please log in again.",
        )

    user_id = int(payload.get("sub", 0))
    user = crud.get_user_by_id(db, user_id)

    if not user or not user.is_active:
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or deactivated. Please log in again.",
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account has been deactivated.",
        )

    access_token, expires_in = create_access_token(user.id)
    new_refresh_token = create_refresh_token(user.id)
    _set_refresh_cookie(response, new_refresh_token)

    logger.info("Access token refreshed for user_id=%d", user.id)

    return TokenResponse(
        access_token=access_token,
        expires_in=expires_in,
        remember_me=True,
        user=UserResponse.model_validate(user),
    )


# ── Slack OAuth Login ─────────────────────────────────────────────────────────

@router.get(
    "/slack/login",
    summary="Begin Slack OAuth login flow",
)
def slack_login() -> RedirectResponse:
    url = (
        "https://slack.com/oauth/v2/authorize"
        f"?client_id={SLACK_CLIENT_ID}"
        f"&user_scope={SLACK_USER_SCOPES}"
        f"&redirect_uri={SLACK_REDIRECT_URI}"
    )
    return RedirectResponse(url)


@router.get(
    "/slack/callback",
    summary="Slack OAuth callback — login or register via Slack",
)
async def slack_callback(
    response: Response,
    code: str = None,
    error: str = None,
    return user


def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    refresh_token: Optional[str] = Cookie(default=None, alias="refresh_token"),
    db: Session = Depends(get_db),
) -> RedirectResponse:
) -> Optional[User]:
    """
    Slack redirects here after the user approves.
    - If user exists → log them in (issue tokens).
    - If user doesn't exist → create account + redirect to onboarding.
    Same as get_current_user but returns None instead of raising 401.
    Used for endpoints that work both authenticated and unauthenticated.
    """
    if error:
        logger.warning("Slack login denied: %s", error)
        return RedirectResponse(f"{FRONTEND_URL}/login?error=slack_denied")

    if not code:
        return RedirectResponse(f"{FRONTEND_URL}/login?error=missing_code")

    async with httpx.AsyncClient() as client:
        token_res = await client.post(
            "https://slack.com/api/oauth.v2.access",
            data={
                "client_id":     SLACK_CLIENT_ID,
                "client_secret": SLACK_CLIENT_SECRET,
                "code":          code,
                "redirect_uri":  SLACK_REDIRECT_URI,
            },
        )

    token_data = token_res.json()
    if not token_data.get("ok"):
        logger.error("Slack token exchange failed: %s", token_data)
        return RedirectResponse(f"{FRONTEND_URL}/login?error=slack_failed")

    authed_user      = token_data.get("authed_user", {})
    slack_user_id    = authed_user.get("id")
    slack_user_token = authed_user.get("access_token")

    if not slack_user_id or not slack_user_token:
        return RedirectResponse(f"{FRONTEND_URL}/login?error=slack_identity_missing")

    async with httpx.AsyncClient() as client:
        profile_res = await client.get(
            "https://slack.com/api/users.identity",
            headers={"Authorization": f"Bearer {slack_user_token}"},
        )
    try:
        return get_current_user(credentials, refresh_token, db)
    except HTTPException:
        return None

    profile_data = profile_res.json()
    if not profile_data.get("ok"):
        logger.error("Slack identity fetch failed: %s", profile_data)
        return RedirectResponse(f"{FRONTEND_URL}/login?error=slack_profile_failed")

    slack_name    = profile_data.get("user", {}).get("name", "Slack User")
    slack_email   = profile_data.get("user", {}).get("email", "")
    slack_team_id = profile_data.get("team", {}).get("id", "")
# ── Role guards ───────────────────────────────────────────────────────────────

    user = crud.get_user_by_slack_id(db, slack_user_id)
    if not user and slack_email:
        user = crud.get_user_by_email(db, slack_email)
def require_role(*allowed_roles):
    """
    Dependency factory — restricts endpoint to specific roles.

    is_new_user = False
    if not user:
        user = crud.create_user(
            db=db,
            name=slack_name,
            email=slack_email or f"{slack_user_id}@slack.local",
            slack_user_id=slack_user_id,
            slack_team_id=slack_team_id,
        )
        is_new_user = True
        logger.info("New user via Slack: id=%d slack_id=%s", user.id, slack_user_id)
    else:
        logger.info("Existing user via Slack login: id=%d", user.id)

    access_token, expires_in = create_access_token(user.id)
    refresh_token = create_refresh_token(user.id)

    redirect_response = RedirectResponse(
        f"{FRONTEND_URL}/{'onboarding' if is_new_user else 'dashboard'}"
        f"?token={access_token}"
    )
    redirect_response.set_cookie(
        key=COOKIE_NAME,
        value=refresh_token,
        max_age=COOKIE_MAX_AGE,
        httponly=COOKIE_HTTPONLY,
        samesite=COOKIE_SAMESITE,
        secure=COOKIE_SECURE,
    )

    return redirect_response


# ── Segment 5: Claim task invite link ────────────────────────────────────────

@router.get(
    "/claim",
    summary="Claim an assigned task via invite link (Segment 5)",
    description=(
        "Called when an unregistered assignee clicks the DM invite link. "
        "Redirects to the frontend with pre-filled invite code and task ID "
        "so the signup flow can auto-join the workspace and highlight the task."
    ),
)
def claim_task(
    task_id: int = Query(..., description="ID of the task being claimed"),
    invite: str = Query(default=None, description="Workspace invite code (auto-joins on signup)"),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    Usage:
        @router.get("/admin")
        def admin_only(user = Depends(require_role("architect"))):
            ...
    """
    Segment 5 — Claim link handler.
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

    This endpoint is hit when an unregistered Slack user clicks the
    "claim your task" link the bot DM'd them.

    It validates the task exists, then redirects to the frontend
    /signup page with the task_id and invite_code pre-filled in the
    query string so the frontend can:
      1. Show a "You were assigned: <task title>" banner
      2. Pre-fill the invite code in the workspace join step
      3. After signup, highlight that task in the dashboard
# ── Convenience role dependencies ─────────────────────────────────────────────
# Use these directly in route handlers for clean code:
#   def my_route(user = Depends(require_architect)):

    If the task doesn't exist, redirects to the generic signup page.
    """
    task = crud.get_task(db, task_id)

    if not task:
        logger.warning("Claim link hit for non-existent task_id=%d", task_id)
        # Redirect to generic signup — don't error out
        return RedirectResponse(f"{FRONTEND_URL}/signup")

    # Build frontend URL with context so the signup page can personalise
    params = f"task={task_id}&title={task.title or ''}"
    if invite:
        # Validate invite code is real before forwarding it
        workspace = crud.get_workspace_by_invite_code(db, invite)
        if workspace:
            params += f"&invite={invite}&workspace={workspace.name}"
        else:
            logger.warning("Claim link has invalid invite code=%r", invite)

    redirect_url = f"{FRONTEND_URL}/signup?{params}"
    logger.info(
        "Claim link redirect: task_id=%d invite=%r → %s", task_id, invite, redirect_url
    )
    return RedirectResponse(redirect_url)
require_architect = require_role("architect")
require_navigator = require_role("architect", "navigator")
require_operator  = require_role("architect", "navigator", "operator")
# solo can only access their own routes — handled in the route itself
