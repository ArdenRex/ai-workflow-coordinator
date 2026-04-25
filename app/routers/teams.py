"""
app/routers/teams.py
─────────────────────
Microsoft Teams integration — Segment 9.

Endpoints:
  POST /teams/webhook          — receive Activity payloads from Bot Framework
  GET  /teams/status           — connection status + configured channels
  PUT  /teams/config           — save tenant ID + bot credentials
  DELETE /teams/config         — disconnect Teams
  GET  /teams/channels         — list registered Teams channels
  POST /teams/channels         — register a Teams channel to receive task updates
  DELETE /teams/channels/{cid} — unregister a channel

Bot setup (one-time, in Azure portal):
  1. Create a Bot resource → enable "Microsoft Teams" channel
  2. Copy App ID + App Secret → set as TEAMS_APP_ID / TEAMS_APP_SECRET in Railway
  3. Set messaging endpoint to: https://your-backend.railway.app/teams/webhook
"""

import hashlib
import hmac
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Task, TaskStatus, User, UserRole
from app.routers.auth import get_current_user
from app.schemas import (
    TeamsConfigUpdate,
    TeamsConfigResponse,
    TeamsChannelCreate,
    TeamsChannelResponse,
    TeamsStatusResponse,
)
from app import crud

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/teams", tags=["Teams"])

# ── DB dependency ─────────────────────────────────────────────────────────────

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Bot Framework token validation ────────────────────────────────────────────

TEAMS_APP_ID     = os.getenv("TEAMS_APP_ID", "")
TEAMS_APP_SECRET = os.getenv("TEAMS_APP_SECRET", "")
BOT_FRAMEWORK_TOKEN_URL = (
    "https://login.microsoftonline.com/botframework.com/oauth2/v2.0/token"
)

async def _get_bot_token() -> str:
    """Obtain a Bot Framework access token for sending proactive messages."""
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            BOT_FRAMEWORK_TOKEN_URL,
            data={
                "grant_type":    "client_credentials",
                "client_id":     TEAMS_APP_ID,
                "client_secret": TEAMS_APP_SECRET,
                "scope":         "https://api.botframework.com/.default",
            },
        )
        r.raise_for_status()
        return r.json()["access_token"]


# ── Webhook ───────────────────────────────────────────────────────────────────

@router.post("/webhook", include_in_schema=False)
async def teams_webhook(request: Request):
    """
    Receive Activity payloads from the Bot Framework / Teams.
    Handles:
      - message activities mentioning the bot (task creation)
      - conversationUpdate (members added — bot installed in channel)
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    activity_type = body.get("type", "")
    logger.info("Teams webhook | type=%s", activity_type)

    if activity_type == "message":
        await _handle_message(body)
    elif activity_type == "conversationUpdate":
        await _handle_conversation_update(body)

    # Bot Framework always expects 200 OK
    return {"status": "ok"}


async def _handle_message(activity: dict):
    """Parse a Teams message, extract a task command, persist it."""
    text_raw: str = activity.get("text", "") or ""
    # Strip HTML tags that Teams injects for @-mentions
    text = re.sub(r"<[^>]+>", "", text_raw).strip()

    # Only handle messages that mention the bot ("create task …")
    if not re.search(r"create\s+task", text, re.IGNORECASE):
        # Echo help message back
        await _reply(activity, (
            "👋 Hi! I can create tasks for you.\n\n"
            "Try: **create task** [**@assignee**] _task title_\n\n"
            "Example: `create task @sarah finish the Q3 report by Friday`"
        ))
        return

    # Extract assignee and title
    title_match = re.search(
        r"create\s+task\s+(?:@(\S+)\s+)?(.+)", text, re.IGNORECASE
    )
    if not title_match:
        await _reply(activity, "⚠️ Couldn't parse that. Try: `create task @assignee title`")
        return

    assignee_handle = title_match.group(1)
    title           = title_match.group(2).strip()

    from app.database import SessionLocal
    db = SessionLocal()
    try:
        # Resolve workspace from Teams tenant ID
        tenant_id: str = (
            activity.get("channelData", {}).get("tenant", {}).get("id", "") or ""
        )
        ws_settings = crud.get_workspace_settings_by_teams_tenant(db, tenant_id)
        workspace_id = ws_settings.workspace_id if ws_settings else None

        new_task = Task(
            title            = title,
            task_description = title,
            assignee         = assignee_handle,
            status           = TaskStatus.to_do,
            workspace_id     = workspace_id,
            source_message   = text,
        )
        db.add(new_task)
        db.commit()
        db.refresh(new_task)
        logger.info(
            "Teams task created | id=%s title=%r assignee=%r",
            new_task.id, title, assignee_handle,
        )
        msg = (
            f"✅ Task **{title}** (id: {new_task.id}) "
            + (f"assigned to **{assignee_handle}**" if assignee_handle else "")
            + " added to **To Do**."
        )
        await _reply(activity, msg)
    except Exception as exc:
        db.rollback()
        logger.error("Teams task creation failed: %s", exc, exc_info=True)
        await _reply(activity, f"⚠️ Sorry, couldn't create that task. ({exc})")
    finally:
        db.close()


async def _handle_conversation_update(activity: dict):
    """Welcome message when the bot is added to a Teams channel."""
    members_added = activity.get("membersAdded", [])
    bot_id = activity.get("recipient", {}).get("id", "")
    if any(m.get("id") == bot_id for m in members_added):
        await _reply(
            activity,
            "👋 **AI Workflow Coordinator** is connected to this channel!\n\n"
            "Mention me with `create task` to create tasks directly from Teams.\n"
            "Example: `@bot create task @alice finish the slide deck`",
        )


async def _reply(activity: dict, text: str):
    """Send a reply activity back to Teams via Bot Connector Service."""
    service_url = activity.get("serviceUrl", "").rstrip("/")
    conversation_id = activity.get("conversation", {}).get("id", "")
    if not service_url or not conversation_id:
        logger.warning("Teams _reply: missing serviceUrl or conversation ID")
        return

    if not TEAMS_APP_ID or not TEAMS_APP_SECRET:
        logger.warning("TEAMS_APP_ID / TEAMS_APP_SECRET not configured — skipping reply")
        return

    try:
        token = await _get_bot_token()
        reply_url = f"{service_url}/v3/conversations/{conversation_id}/activities"
        payload = {
            "type":         "message",
            "from":         activity.get("recipient", {}),
            "conversation": activity.get("conversation", {}),
            "recipient":    activity.get("from", {}),
            "text":         text,
            "textFormat":   "markdown",
        }
        if activity_id := activity.get("id"):
            reply_url = f"{service_url}/v3/conversations/{conversation_id}/activities/{activity_id}"

        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                reply_url,
                json=payload,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            )
            r.raise_for_status()
    except Exception as exc:
        logger.error("Teams reply failed: %s", exc, exc_info=True)


# ── Status ────────────────────────────────────────────────────────────────────

@router.get("/status", response_model=TeamsStatusResponse)
def get_teams_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return whether Teams is configured for this workspace."""
    if not current_user.workspace_id:
        raise HTTPException(status_code=404, detail="No workspace found.")
    config = crud.get_teams_config(db, current_user.workspace_id)
    channels = crud.list_teams_channels(db, current_user.workspace_id)
    return TeamsStatusResponse(
        connected          = bool(config.get("teams_tenant_id")),
        tenant_id          = config.get("teams_tenant_id"),
        bot_configured     = bool(TEAMS_APP_ID and TEAMS_APP_SECRET),
        webhook_url        = f"{os.getenv('BACKEND_URL', '')}/teams/webhook",
        channel_count      = len(channels),
    )


# ── Config ────────────────────────────────────────────────────────────────────

@router.put("/config", response_model=TeamsConfigResponse)
def save_teams_config(
    payload: TeamsConfigUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Save Teams tenant ID (Architect only)."""
    if current_user.role not in (UserRole.architect,):
        raise HTTPException(status_code=403, detail="Only Architects can configure Teams.")
    if not current_user.workspace_id:
        raise HTTPException(status_code=404, detail="No workspace found.")
    saved = crud.save_teams_config(
        db,
        current_user.workspace_id,
        tenant_id=payload.tenant_id,
    )
    return TeamsConfigResponse(
        tenant_id=saved.get("teams_tenant_id"),
        updated=True,
    )


@router.delete("/config", status_code=204)
def disconnect_teams(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Disconnect Teams (Architect only)."""
    if current_user.role not in (UserRole.architect,):
        raise HTTPException(status_code=403, detail="Only Architects can disconnect Teams.")
    if not current_user.workspace_id:
        raise HTTPException(status_code=404, detail="No workspace found.")
    crud.save_teams_config(db, current_user.workspace_id, tenant_id=None, clear=True)


# ── Channels ──────────────────────────────────────────────────────────────────

@router.get("/channels", response_model=list[TeamsChannelResponse])
def list_channels(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not current_user.workspace_id:
        raise HTTPException(status_code=404, detail="No workspace found.")
    return crud.list_teams_channels(db, current_user.workspace_id)


@router.post("/channels", response_model=TeamsChannelResponse, status_code=201)
def register_channel(
    payload: TeamsChannelCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Register a Teams channel to receive proactive task notifications."""
    if current_user.role not in (UserRole.architect,):
        raise HTTPException(status_code=403, detail="Only Architects can register channels.")
    if not current_user.workspace_id:
        raise HTTPException(status_code=404, detail="No workspace found.")
    return crud.create_teams_channel(
        db,
        workspace_id     = current_user.workspace_id,
        channel_id       = payload.channel_id,
        channel_name     = payload.channel_name,
        service_url      = payload.service_url,
        conversation_id  = payload.conversation_id,
    )


@router.delete("/channels/{channel_db_id}", status_code=204)
def unregister_channel(
    channel_db_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role not in (UserRole.architect,):
        raise HTTPException(status_code=403, detail="Only Architects can remove channels.")
    if not current_user.workspace_id:
        raise HTTPException(status_code=404, detail="No workspace found.")
    deleted = crud.delete_teams_channel(db, channel_db_id, current_user.workspace_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Channel not found.")
