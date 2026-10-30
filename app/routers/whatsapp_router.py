"""
routers/whatsapp_router.py
─────────────────────────────────────────────────────────────────────────────
WhatsApp Business webhook (Meta Cloud API). See app/whatsapp_bot.py for what
happens to the messages.

Meta setup (developers.facebook.com → your app → WhatsApp → Configuration):
  1. Callback URL:  https://<your-backend>/webhooks/whatsapp
  2. Verify token:  the exact value of WHATSAPP_VERIFY_TOKEN in your .env
  3. Subscribe to the webhook fields:  messages
     (and smb_message_echoes if you want messages the owner sends from the
      WhatsApp Business app on a coexistence number to be considered too)
  4. Set WHATSAPP_APP_SECRET in .env to your Meta app's App Secret.

"Connect WhatsApp" button (Embedded Signup) additionally needs:
  WHATSAPP_APP_ID           your Meta app's App ID
  WHATSAPP_CONFIG_ID        Embedded Signup configuration id (Meta: Facebook Login
                            for Business -> Configurations)
  WHATSAPP_REGISTRATION_PIN 6 digits; only used for brand-new numbers
  WHATSAPP_GRAPH_VERSION    optional, default v23.0
The button stays hidden until the first four are set.

Security: every POST is signed by Meta (X-Hub-Signature-256, HMAC-SHA256 of
the raw body with the App Secret). Unsigned or wrongly-signed requests are
rejected, and if WHATSAPP_APP_SECRET isn't configured the endpoint refuses
everything rather than accepting unverified traffic.
"""
import hashlib
import hmac
import json
import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import whatsapp_connect
from app.auth import get_current_user
from app.config import get_settings
from app.database import get_db
from app.models import User
from app.whatsapp_bot import handle_webhook_payload

logger = logging.getLogger(__name__)
router = APIRouter(tags=["WhatsApp"])


def verify_signature(raw_body: bytes, header: Optional[str], app_secret: str) -> bool:
    """True if `header` ("sha256=<hex>") is the valid HMAC-SHA256 of raw_body."""
    if not header or not header.startswith("sha256=") or not app_secret:
        return False
    expected = hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header[len("sha256="):])


# ── Meta's one-time webhook verification handshake ───────────────────────────
@router.get("/webhooks/whatsapp", summary="WhatsApp webhook verification (Meta)", include_in_schema=True)
async def whatsapp_verify(
    hub_mode: Optional[str] = Query(default=None, alias="hub.mode"),
    hub_verify_token: Optional[str] = Query(default=None, alias="hub.verify_token"),
    hub_challenge: Optional[str] = Query(default=None, alias="hub.challenge"),
):
    settings = get_settings()
    if not settings.whatsapp_verify_token:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not enabled.")
    if (
        hub_mode == "subscribe"
        and hub_challenge is not None
        and hub_verify_token is not None
        and hmac.compare_digest(hub_verify_token, settings.whatsapp_verify_token)
    ):
        return PlainTextResponse(hub_challenge)
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Verification failed.")


# ── Incoming messages ────────────────────────────────────────────────────────
@router.post("/webhooks/whatsapp", summary="WhatsApp incoming messages (Meta)", include_in_schema=True)
async def whatsapp_receive(request: Request, background: BackgroundTasks):
    settings = get_settings()
    app_secret = settings.whatsapp_app_secret.get_secret_value()
    if not app_secret:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not enabled.")

    raw = await request.body()
    if not verify_signature(raw, request.headers.get("X-Hub-Signature-256"), app_secret):
        logger.warning("WhatsApp webhook rejected: bad or missing signature")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature.")

    try:
        payload = json.loads(raw)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON.")

    # Answer 200 immediately (Meta retries slow/failed webhooks) and do the
    # AI work after the response is sent.
    background.add_task(handle_webhook_payload, payload)
    return {"status": "received"}


# ── "Connect WhatsApp" (Meta Embedded Signup) — normal authenticated endpoints ─
class WhatsAppConnectRequest(BaseModel):
    code: str
    waba_id: str
    phone_number_id: Optional[str] = None


@router.get("/auth/whatsapp/config", summary="Public settings the Connect WhatsApp button needs")
async def whatsapp_config(current_user: User = Depends(get_current_user)):
    s = get_settings()
    return {
        "enabled": whatsapp_connect._enabled(),
        "app_id": s.whatsapp_app_id if whatsapp_connect._enabled() else None,
        "config_id": s.whatsapp_config_id if whatsapp_connect._enabled() else None,
        "graph_version": s.whatsapp_graph_version,
    }


@router.get("/auth/whatsapp/status", summary="Current user's WhatsApp connection status")
async def whatsapp_status(current_user: User = Depends(get_current_user)):
    return {
        "enabled": whatsapp_connect._enabled(),
        "connected": bool(current_user.whatsapp_connected),
        "display_number": current_user.whatsapp_display_number if current_user.whatsapp_connected else None,
    }


@router.post("/auth/whatsapp/connect", summary="Finish Connect WhatsApp (after Embedded Signup)")
async def whatsapp_connect_endpoint(
    body: WhatsAppConnectRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return await whatsapp_connect.connect_whatsapp(
            db, current_user, body.code, body.waba_id, body.phone_number_id)
    except whatsapp_connect.WhatsAppConnectError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)


@router.post("/auth/whatsapp/disconnect", summary="Disconnect WhatsApp")
async def whatsapp_disconnect(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await whatsapp_connect.disconnect_whatsapp(db, current_user)
    return {"status": "disconnected"}
