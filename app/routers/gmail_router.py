"""
routers/gmail_router.py
─────────────────────────────────────────────────────────────────────────────
Per-user Gmail OAuth ("Connect Gmail" button) — the Gmail equivalent of
routers/slack.py's /auth/install + /auth/slack/callback, except this is
per-user rather than per-workspace, so tokens are saved on the User row
(see app.gmail_bot for the polling side of this feature).

Setup (Google Cloud Console):
  1. Create/select a project → enable the "Gmail API".
  2. OAuth consent screen → External → add scope
     https://www.googleapis.com/auth/gmail.readonly → add yourself as a
     test user (or publish the app once you're past testing).
  3. Credentials → Create OAuth client ID → Web application → add this
     exact redirect URI:
       https://<your-backend>/auth/gmail/callback
  4. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in your backend .env.

Frontend flow: "Connect Gmail" button calls
  GET /auth/gmail/install?token=<the user's JWT access token>
(the JWT has to travel as a query param here, not a header, because this is
a full-page browser redirect to Google — there's no way to attach an
Authorization header to that navigation).
"""
import logging
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth import decode_token, get_current_user
from app.config import get_settings
from app.database import get_db
from app.models import User

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Gmail"])

# In-memory CSRF-state → user_id map, one-time use, expires after 10 minutes.
# Mirrors the _oauth_states set in routers/slack.py, extended to also carry
# which of our users is connecting (Slack's flow doesn't need this since it
# isn't tied to a specific user).
_oauth_states: dict[str, tuple[int, float]] = {}
_STATE_TTL_SECONDS = 600

BACKEND_URL  = os.getenv("BACKEND_URL", "").rstrip("/")
FRONTEND_URL = os.getenv("FRONTEND_URL", "").rstrip("/")
REDIRECT_URI = f"{BACKEND_URL}/auth/gmail/callback"

GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"


def _cleanup_expired_states() -> None:
    now = time.time()
    expired = [s for s, (_, ts) in _oauth_states.items() if now - ts > _STATE_TTL_SECONDS]
    for s in expired:
        _oauth_states.pop(s, None)


# ── OAuth Step 1: redirect user to Google's permission screen ─────────────────
@router.get("/auth/gmail/install", summary="Begin Gmail OAuth connect flow", include_in_schema=True)
async def gmail_install(token: str, db: Session = Depends(get_db)):
    settings = get_settings()
    if not settings.google_client_id:
        return JSONResponse({"error": "GOOGLE_CLIENT_ID is not configured on the server."}, status_code=500)

    # The JWT arrives as a query param (see module docstring) — decode it the
    # same way get_current_user does for normal header-based requests.
    payload = decode_token(token)
    if payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type.")
    try:
        user_id = int(payload.get("sub"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token subject.")

    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found.")

    _cleanup_expired_states()
    state = secrets.token_urlsafe(32)
    _oauth_states[state] = (user_id, time.time())

    params = {
        "client_id":     settings.google_client_id,
        "redirect_uri":  REDIRECT_URI,
        "response_type": "code",
        "scope":         GMAIL_SCOPE,
        "access_type":   "offline",   # required to get a refresh_token
        "prompt":        "consent",   # forces refresh_token on repeat connects too
        "state":         state,
    }
    url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"
    logger.info("Redirecting user_id=%s to Google OAuth", user_id)
    return RedirectResponse(url)


# ── OAuth Step 2: Google redirects here after the user approves ───────────────
@router.get("/auth/gmail/callback", summary="Gmail OAuth callback", include_in_schema=True)
async def gmail_oauth_callback(code: str = None, error: str = None, state: str = None, db: Session = Depends(get_db)):
    if error:
        logger.warning("Gmail OAuth denied by user: %s", error)
        return RedirectResponse(f"{FRONTEND_URL}?gmail=cancelled")

    _cleanup_expired_states()
    entry = _oauth_states.pop(state, None) if state else None
    if not entry:
        logger.warning("Gmail OAuth invalid or missing state token")
        return RedirectResponse(f"{FRONTEND_URL}?gmail=error")
    user_id, _ = entry

    if not code:
        return RedirectResponse(f"{FRONTEND_URL}?gmail=error")

    settings = get_settings()
    async with httpx.AsyncClient() as client:
        token_resp = await client.post("https://oauth2.googleapis.com/token", data={
            "client_id":     settings.google_client_id,
            "client_secret": settings.google_client_secret.get_secret_value(),
            "code":          code,
            "redirect_uri":  REDIRECT_URI,
            "grant_type":    "authorization_code",
        })
    token_data = token_resp.json()

    if token_resp.status_code != 200 or "access_token" not in token_data:
        logger.error("Gmail OAuth token exchange failed: %s", token_data)
        return RedirectResponse(f"{FRONTEND_URL}?gmail=error")

    # Fetch the connected address so the UI can show *which* Gmail is linked
    async with httpx.AsyncClient() as client:
        profile_resp = await client.get(
            "https://gmail.googleapis.com/gmail/v1/users/me/profile",
            headers={"Authorization": f"Bearer {token_data['access_token']}"},
        )
    gmail_email = profile_resp.json().get("emailAddress", "") if profile_resp.status_code == 200 else ""

    user = db.get(User, user_id)
    if not user:
        logger.error("Gmail OAuth callback: user_id=%s no longer exists", user_id)
        return RedirectResponse(f"{FRONTEND_URL}?gmail=error")

    user.gmail_connected  = True
    user.gmail_email      = gmail_email or user.gmail_email
    user.gmail_access_token = token_data["access_token"]
    # Google only returns refresh_token on the FIRST consent (or when
    # prompt=consent forces it, which /auth/gmail/install always sets) —
    # only overwrite if we actually got one, so a token refresh call never
    # accidentally wipes a previously stored refresh_token.
    if token_data.get("refresh_token"):
        user.gmail_refresh_token = token_data["refresh_token"]
    user.gmail_token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(token_data.get("expires_in", 3600)))
    db.add(user)
    db.commit()

    logger.info("Gmail connected for user_id=%s (%s)", user_id, gmail_email)
    return RedirectResponse(f"{FRONTEND_URL}?gmail=success")


# ── Status + disconnect (normal authenticated JSON endpoints) ─────────────────
@router.get("/auth/gmail/status", summary="Current user's Gmail connection status", include_in_schema=True)
async def gmail_status(current_user: User = Depends(get_current_user)):
    return {
        "connected": bool(current_user.gmail_connected),
        "email": current_user.gmail_email if current_user.gmail_connected else None,
    }


@router.post("/auth/gmail/disconnect", summary="Disconnect Gmail", include_in_schema=True)
async def gmail_disconnect(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    current_user.gmail_connected = False
    current_user.gmail_access_token = None
    current_user.gmail_refresh_token = None
    current_user.gmail_token_expires_at = None
    db.add(current_user)
    db.commit()
    logger.info("Gmail disconnected for user_id=%s", current_user.id)
    return {"status": "disconnected"}
