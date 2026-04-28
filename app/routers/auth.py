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
"""

import logging
import os
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import crud
from app.auth import (
    create_access_token,
    create_refresh_token,
    get_current_user,
    decode_token,
)
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

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Auth"])

# ── Env vars ──────────────────────────────────────────────────────────────────
SLACK_CLIENT_ID     = os.getenv("SLACK_CLIENT_ID", "")
SLACK_CLIENT_SECRET = os.getenv("SLACK_CLIENT_SECRET", "")
BACKEND_URL         = os.getenv("BACKEND_URL", "").rstrip("/")
FRONTEND_URL        = os.getenv("FRONTEND_URL", "").rstrip("/")
SLACK_REDIRECT_URI  = f"{BACKEND_URL}/auth/slack/callback"

# ── Billing config ────────────────────────────────────────────────────────────
ADMIN_EMAILS = [e.strip().lower() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip()]
TRIAL_DAYS   = 7

SLACK_USER_SCOPES = "identity.basic,identity.email,identity.avatar"

# Cookie settings
COOKIE_NAME     = "refresh_token"
COOKIE_MAX_AGE  = 60 * 60 * 24 * 30   # 30 days in seconds
COOKIE_HTTPONLY = True
COOKIE_SAMESITE = "lax"
COOKIE_SECURE   = os.getenv("APP_ENV", "development") == "production"


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


# ── Step 1: Register ──────────────────────────────────────────────────────────

@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new account",
)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> RegisterResponse:
    """
    Creates a new user account with email + password.
    After this, the frontend should redirect to /onboarding.
    """
    existing = crud.get_user_by_email(db, payload.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists. Please log in.",
        )

    try:
        trial_ends = datetime.now(timezone.utc) + timedelta(days=TRIAL_DAYS)
        is_exempt  = payload.email.lower() in ADMIN_EMAILS
        user = crud.create_user(
            db=db,
            name=payload.name,
            email=payload.email,
            password=payload.password,
            trial_ends_at=trial_ends,
            subscription_status="exempt" if is_exempt else "trialing",
        )
    except IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )

    logger.info("New user registered: id=%d email=%s", user.id, user.email)

    return RegisterResponse(
        message="Account created. Please complete onboarding.",
        user=UserResponse.model_validate(user),
    )


# ── Step 2+3: Onboarding ──────────────────────────────────────────────────────

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
    """
    Called after registration to set:
      - Role (architect / navigator / operator / solo)
      - Team name (navigator only)
      - Workspace: create new OR join existing via invite code

    Solo users skip workspace entirely.
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

    if not updated_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
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
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account has been deactivated.",
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

@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current user profile",
)
def get_me(current_user: User = Depends(get_current_user)) -> UserResponse:
    """Returns the profile of the currently logged-in user."""
    return UserResponse.model_validate(current_user)


# ── Refresh token → new access token ─────────────────────────────────────────

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
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No refresh token found. Please log in again.",
        )

    payload = decode_token(refresh_token)
    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type.",
        )

    user_id = int(payload.get("sub", 0))
    user = crud.get_user_by_id(db, user_id)

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or deactivated. Please log in again.",
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
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """
    Slack redirects here after the user approves.
    - If user exists → log them in (issue tokens).
    - If user doesn't exist → create account + redirect to onboarding.
    - Segment 7: marks slack_connected onboarding step for the user.
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

    profile_data = profile_res.json()
    if not profile_data.get("ok"):
        logger.error("Slack identity fetch failed: %s", profile_data)
        return RedirectResponse(f"{FRONTEND_URL}/login?error=slack_profile_failed")

    slack_name    = profile_data.get("user", {}).get("name", "Slack User")
    slack_email   = profile_data.get("user", {}).get("email", "")
    slack_team_id = profile_data.get("team", {}).get("id", "")

    user = crud.get_user_by_slack_id(db, slack_user_id)
    if not user and slack_email:
        user = crud.get_user_by_email(db, slack_email)

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

    # Segment 7 — mark slack_connected onboarding step (fire-and-forget)
    try:
        from app.routers.onboarding import mark_step_for_user
        mark_step_for_user(db, user.id, "slack_connected")
    except Exception as exc:
        logger.warning("Could not mark slack_connected onboarding step: %s", exc)

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
    """
    Segment 5 — Claim link handler.

    This endpoint is hit when an unregistered Slack user clicks the
    "claim your task" link the bot DM'd them.

    It validates the task exists, then redirects to the frontend
    /signup page with the task_id and invite_code pre-filled in the
    query string so the frontend can:
      1. Show a "You were assigned: <task title>" banner
      2. Pre-fill the invite code in the workspace join step
      3. After signup, highlight that task in the dashboard

    If the task doesn't exist, redirects to the generic signup page.
    """
    task = crud.get_task(db, task_id)

    if not task:
        logger.warning("Claim link hit for non-existent task_id=%d", task_id)
        return RedirectResponse(f"{FRONTEND_URL}/signup")

    params = f"task={task_id}&title={task.title or ''}"
    if invite:
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


# ── Segment 15: Billing status ────────────────────────────────────────────────

@router.get(
    "/billing-status",
    summary="Get current user's billing/trial status",
)
def billing_status(
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Returns the user's subscription status and trial info.
    Frontend uses this to decide whether to show the BillingWall.
    """
    now = datetime.now(timezone.utc)

    # Exempt users (admin/owner) — never show billing wall
    if current_user.subscription_status == "exempt":
        return {"status": "exempt", "show_wall": False}

    # Active subscription
    if current_user.subscription_status == "active":
        return {"status": "active", "show_wall": False}

    # Still in trial
    if current_user.subscription_status == "trialing" and current_user.trial_ends_at:
        trial_end = current_user.trial_ends_at
        if trial_end.tzinfo is None:
            trial_end = trial_end.replace(tzinfo=timezone.utc)
        if trial_end > now:
            days_left = (trial_end - now).days
            return {
                "status":    "trialing",
                "show_wall": False,
                "days_left": days_left,
                "trial_ends_at": trial_end.isoformat(),
            }

    # Trial expired or cancelled or past_due
    return {
        "status":    current_user.subscription_status,
        "show_wall": True,
        "trial_ends_at": current_user.trial_ends_at.isoformat() if current_user.trial_ends_at else None,
    }
