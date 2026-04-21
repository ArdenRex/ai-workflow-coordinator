"""
routers/slack.py
─────────────────────────────────────────────────────────────────────────────
Mounts the Slack Bolt ASGI handler at POST /slack/events.
Also handles Slack OAuth install flow at /auth/install and /auth/slack/callback.
"""
import logging
import os

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from app.slack_bot import slack_handler

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Slack"])

# ── Env vars ───────────────────────────────────────────────────────────────────
SLACK_CLIENT_ID     = os.getenv("SLACK_CLIENT_ID", "")
SLACK_CLIENT_SECRET = os.getenv("SLACK_CLIENT_SECRET", "")
BACKEND_URL         = os.getenv("BACKEND_URL", "https://ai-workflow-coordinator-api-production.up.railway.app")
FRONTEND_URL        = os.getenv("FRONTEND_URL", "").rstrip("/")

# Scopes your bot needs — must match what is configured in api.slack.com/apps
SLACK_SCOPES = "app_mentions:read,chat:write,channels:history,users:read"

# Fixed redirect URI — must exactly match what is saved in Slack App dashboard
REDIRECT_URI = f"{BACKEND_URL}/auth/slack/callback"


# ── Slack Events (Bolt handler) ────────────────────────────────────────────────
@router.post(
    "/slack/events",
    status_code=200,
    summary="Slack Events API webhook",
    include_in_schema=True,
)
async def slack_events(request: Request) -> Response:
    """
    Receives all Slack Events API payloads.
    Signature verification, URL verification challenge, and event
    dispatching are all handled automatically by SlackRequestHandler.
    """
    logger.debug("Slack event received: %s %s", request.method, request.url.path)
    return await slack_handler.handle(request)


# ── OAuth Step 1: redirect user to Slack's permission screen ──────────────────
@router.get(
    "/auth/install",
    summary="Begin Slack OAuth install flow",
    include_in_schema=True,
)
async def slack_install():
    """
    Frontend 'Add to Slack' button calls GET /auth/install.
    This redirects the user to Slack's OAuth authorization page.
    After the user approves, Slack redirects to /auth/slack/callback.
    """
    if not SLACK_CLIENT_ID:
        return JSONResponse(
            {"error": "SLACK_CLIENT_ID is not configured on the server."},
            status_code=500,
        )

    url = (
        "https://slack.com/oauth/v2/authorize"
        f"?client_id={SLACK_CLIENT_ID}"
        f"&scope={SLACK_SCOPES}"
        f"&redirect_uri={REDIRECT_URI}"
    )
    logger.info("Redirecting to Slack OAuth: %s", url)
    return RedirectResponse(url)


# ── OAuth Step 2: Slack redirects here after user approves ────────────────────
@router.get(
    "/auth/slack/callback",
    summary="Slack OAuth callback",
    include_in_schema=True,
)
async def slack_oauth_callback(code: str = None, error: str = None):
    """
    Slack redirects here after the user approves (or denies) the install.
    Exchanges the temporary code for a permanent bot token.
    Then redirects the user back to the frontend dashboard.
    """
    # User denied the install
    if error:
        logger.warning("Slack OAuth denied by user: %s", error)
        return RedirectResponse(f"{FRONTEND_URL}?slack=cancelled")

    if not code:
        return JSONResponse({"error": "Missing code from Slack."}, status_code=400)

    # Exchange the temporary code for an access token
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://slack.com/api/oauth.v2.access",
            data={
                "client_id":     SLACK_CLIENT_ID,
                "client_secret": SLACK_CLIENT_SECRET,
                "code":          code,
                "redirect_uri":  REDIRECT_URI,
            },
        )

    data = response.json()

    if not data.get("ok"):
        logger.error("Slack OAuth token exchange failed: %s", data)
        return RedirectResponse(f"{FRONTEND_URL}?slack=error")

    # ── Token received ─────────────────────────────────────────────────────────
    # For MVP: log the workspace name (token logged partially for security)
    # For multi-tenant SaaS: save token to a `workspaces` DB table instead
    team_name = data.get("team", {}).get("name", "unknown")
    token_preview = data.get("access_token", "")[:10] + "..."
    logger.info(
        "Slack OAuth success | workspace=%s | token_preview=%s",
        team_name, token_preview,
    )

    # Redirect back to frontend dashboard with success flag
    return RedirectResponse(f"{FRONTEND_URL}?slack=success")
