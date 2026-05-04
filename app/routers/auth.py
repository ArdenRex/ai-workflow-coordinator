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
from app.models import User, UserRole, FreelancerRequest
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

# ── Disposable / temp email domains blocklist ─────────────────────────────────
_BLOCKED_EMAIL_DOMAINS = {
    "mailinator.com", "guerrillamail.com", "guerrillamail.net", "guerrillamail.org",
    "guerrillamail.biz", "guerrillamail.de", "guerrillamailblock.com",
    "sharklasers.com", "spam4.me", "grr.la",
    "tempmail.com", "temp-mail.org", "temp-mail.io", "tempmail.net",
    "throwaway.email", "throwam.com", "throwam.net",
    "yopmail.com", "yopmail.fr",
    "dispostable.com", "mailnull.com",
    "trashmail.com", "trashmail.me", "trashmail.net", "trashmail.org",
    "trashmail.at", "trashmail.io", "trashmail.xyz",
    "fakeinbox.com", "fakeinbox.net", "maildrop.cc",
    "spambox.us", "spambox.me", "spambox.info",
    "discard.email", "discardmail.com", "discardmail.de",
    "mailnesia.com", "mailexpire.com", "mailscrap.com",
    "getonemail.com", "getonemail.net",
    "tempinbox.com", "tempinbox.co.uk",
    "temporaryemail.net", "temporaryemail.us",
    "temporaryforwarding.com", "temporaryinbox.com",
    "10minutemail.com", "10minutemail.net", "10minutemail.org",
    "10minutemail.co.za", "10minutemail.de", "10minutemail.ru",
    "20minutemail.com", "20minutemail.it",
    "0-mail.com", "mailtemp.info", "mailtemp.net", "one-time.email",
    "inboxbear.com", "mohmal.com", "spamgap.com", "tempr.email",
    "anonbox.net", "ano-mail.net", "bugmenot.com",
    "deadaddress.com", "deadletter.ga", "despam.it",
    "dodgeit.com", "dodgemail.de", "dontreg.com",
    "dump-email.info", "dumpmail.de", "dumpyemail.com",
    "email60.com", "emaildienst.de", "emailigo.com",
    "emailmiser.com", "emailto.de", "emailwarden.com",
    "ephemail.net", "etranquil.com", "etranquil.net", "etranquil.org",
    "wegwerfmail.de", "wegwerfmail.net", "wegwerfmail.org",
    "zehnminutenmail.de", "spamtrap.ro", "spamfree24.org",
    "spamfree.eu", "spam.la", "spamspot.com",
    "mt2009.com", "mt2014.com", "neverbox.com",
    "sendspamhere.com", "sharedmailbox.org",
    "spamgob.com", "spamherelots.com", "spamhereplease.com",
    "spamthisplease.com", "tempe-mail.com",
    "digitalsanctuary.com", "dingbone.com",
    "dontsendmespam.de", "dumpandfuck.com",
}


def _is_blocked_email(email: str) -> bool:
    """Return True if the email domain is in the disposable-email blocklist."""
    try:
        domain = email.strip().lower().split("@", 1)[1]
        return domain in _BLOCKED_EMAIL_DOMAINS
    except IndexError:
        return True  # malformed — block it


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
    # Block disposable / temp email addresses
    if _is_blocked_email(payload.email):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Temporary or disposable email addresses are not allowed. Please use a real email.",
        )

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

    # Determine role for dashboard routing
    role = "freelancer" if user.subscription_status == "freelancer" else "admin"

    return TokenResponse(
        access_token=access_token,
        expires_in=expires_in,
        remember_me=payload.remember_me,
        role=role,
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


# ── Freelancer: Request dashboard access ──────────────────────────────────────

import threading
import httpx as _httpx

_RESEND_API_KEY   = os.getenv("RESEND_API_KEY", "")
_ALERT_EMAIL      = os.getenv("FEEDBACK_ALERT_EMAIL", "")
_FROM_EMAIL       = os.getenv("FEEDBACK_FROM_EMAIL", "AI Workflow <onboarding@resend.dev>")


class FreelancerAccessRequest(BaseModel):
    name:     str
    email:    str
    password: str


def _notify_admin_of_request(name: str, email: str) -> None:
    """Fire-and-forget: send Resend email to admin when a freelancer requests access."""
    if not _RESEND_API_KEY or not _ALERT_EMAIL:
        logger.info("Resend not configured — skipping freelancer request notification.")
        return

    def _send():
        try:
            html = f"""
            <html><body style="font-family:sans-serif;background:#f5f5f5;padding:24px;">
              <div style="max-width:600px;margin:0 auto;background:#fff;border-radius:10px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.1);">
                <div style="background:#1e293b;padding:20px 24px;color:#fff;">
                  <h2 style="margin:0;font-size:18px;">🔑 New Freelancer Access Request</h2>
                  <p style="margin:4px 0 0;opacity:0.6;font-size:13px;">AI Workflow Coordinator — Admin Dashboard</p>
                </div>
                <div style="padding:24px;">
                  <table style="width:100%;border-collapse:collapse;font-size:14px;">
                    <tr><td style="padding:8px 0;color:#64748b;width:100px;">Name</td><td style="padding:8px 0;font-weight:600;">{name}</td></tr>
                    <tr><td style="padding:8px 0;color:#64748b;">Email</td><td style="padding:8px 0;">{email}</td></tr>
                  </table>
                  <p style="margin-top:20px;font-size:13px;color:#64748b;">
                    Go to the <strong>Freelancer Access</strong> tab in your admin dashboard to approve or deny this request.
                  </p>
                </div>
              </div>
            </body></html>
            """
            resp = _httpx.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {_RESEND_API_KEY}", "Content-Type": "application/json"},
                json={
                    "from":    _FROM_EMAIL,
                    "to":      [_ALERT_EMAIL],
                    "subject": f"🔑 Freelancer access request from {name}",
                    "html":    html,
                },
                timeout=10,
            )
            if resp.status_code >= 400:
                logger.warning("Resend freelancer notification failed: %s", resp.text)
            else:
                logger.info("Freelancer access notification sent to %s", _ALERT_EMAIL)
        except Exception as exc:
            logger.warning("Could not send freelancer notification email: %s", exc)

    threading.Thread(target=_send, daemon=True).start()


@router.post(
    "/request-freelancer-access",
    status_code=status.HTTP_201_CREATED,
    summary="Freelancer submits an access request",
)
def request_freelancer_access(
    payload: FreelancerAccessRequest,
    db: Session = Depends(get_db),
) -> dict:
    """
    Freelancer fills in name + email + password on the dashboard.
    Saves a pending FreelancerRequest row and emails the admin.
    No user account is created yet — admin must approve first.
    """
    from app.crud import hash_password

    if len(payload.password) < 6:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Password must be at least 6 characters.",
        )

    # Block if already submitted or already a user
    existing_req = db.query(FreelancerRequest).filter_by(email=payload.email.lower()).first()
    if existing_req:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A request from this email already exists. Please wait for admin approval.",
        )

    existing_user = crud.get_user_by_email(db, payload.email)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists. Please log in instead.",
        )

    req = FreelancerRequest(
        name=payload.name.strip(),
        email=payload.email.strip().lower(),
        password_hash=hash_password(payload.password),
        status="pending",
    )
    db.add(req)
    db.commit()

    logger.info("Freelancer access request created: email=%s", req.email)
    _notify_admin_of_request(req.name, req.email)

    return {"message": "Access request submitted. The admin will review and notify you."}


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

    card_on_file = bool(getattr(current_user, "ls_customer_id", None))

    # Exempt users (admin/owner) — never show billing wall
    if current_user.subscription_status == "exempt":
        return {"status": "exempt", "show_wall": False, "card_on_file": True}

    # Active subscription
    if current_user.subscription_status == "active":
        return {"status": "active", "show_wall": False, "card_on_file": True}

    # Still in trial
    if current_user.subscription_status == "trialing" and current_user.trial_ends_at:
        trial_end = current_user.trial_ends_at
        if trial_end.tzinfo is None:
            trial_end = trial_end.replace(tzinfo=timezone.utc)
        if trial_end > now:
            days_left = (trial_end - now).days
            # New users (no card yet) see the trial/plan screen first
            show_trial_setup = not card_on_file
            return {
                "status":      "trialing",
                "show_wall":   show_trial_setup,
                "card_on_file": card_on_file,
                "days_left":   days_left,
                "trial_ends_at": trial_end.isoformat(),
            }

    # Trial expired or cancelled or past_due
    return {
        "status":    current_user.subscription_status,
        "show_wall": True,
        "card_on_file": card_on_file,
        "trial_ends_at": current_user.trial_ends_at.isoformat() if current_user.trial_ends_at else None,
    }
