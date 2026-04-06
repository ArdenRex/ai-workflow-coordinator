"""
routers/slack.py
─────────────────────────────────────────────────────────────────────────────
Mounts the Slack Bolt ASGI handler at POST /slack/events.

Slack's Events API will POST every subscribed event to this endpoint.
The SlackRequestHandler handles:
  - Signature verification   (X-Slack-Signature header)
  - URL verification          (challenge handshake on first setup)
  - Event dispatching         (routes to bolt_app event listeners)

Setup in your Slack App dashboard:
  Event Subscriptions → Request URL:
      https://your-domain.com/slack/events

After saving, Slack sends a one-time challenge POST. The handler
automatically responds with the challenge value — no extra code needed.
"""

import logging

from fastapi import APIRouter, Request
from fastapi.responses import Response

from app.slack_bot import slack_handler

import os
import httpx
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Slack"])


@router.post(
    "/slack/events",
    status_code=200,
    summary="Slack Events API webhook",
    response_description="Acknowledged by Slack Bolt handler",
    include_in_schema=True,
)
async def slack_events(request: Request) -> Response:
    """
    Receives all Slack Events API payloads.

    - Slack signature is verified automatically by SlackRequestHandler.
    - Returns HTTP 200 + challenge immediately for URL verification.
    - All other events are dispatched to bolt_app listeners asynchronously.
    - Returns HTTP 403 automatically if signature verification fails.
    """
    logger.debug(
        "Slack event received: method=%s path=%s",
        request.method,
        request.url.path,
    )
    return await slack_handler.handle(request)
@router.get("/auth/slack/callback")
async def slack_oauth_callback(code: str):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://slack.com/api/oauth.v2.access",
            data={
                "client_id": os.environ["SLACK_CLIENT_ID"],
                "client_secret": os.environ["SLACK_CLIENT_SECRET"],
                "code": code,
                "redirect_uri": "https://ai-workflow-coordinator-api-production.up.railway.app/auth/slack/callback",
            },
        )
    data = response.json()
    if data.get("ok"):
        return JSONResponse({"message": "Slack connected successfully!", "team": data.get("team", {}).get("name")})
    else:
        return JSONResponse({"error": data.get("error")}, status_code=400)
