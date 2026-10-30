"""
whatsapp_connect.py
-------------------
Server side of "Connect WhatsApp" (Meta Embedded Signup). The browser runs the
Meta popup and hands us three things; this module turns them into a connected
number:

  1. code             one-time code from FB.login → exchanged here for a
                      business access token (needs the app secret, so it can
                      only happen on the server)
  2. waba_id          the customer's WhatsApp Business Account id
  3. phone_number_id  the number they picked (may be missing when an existing
                      WhatsApp Business app number is connected — we look it up)

Steps in connect_whatsapp():
  exchange code → confirm the number really belongs to that WABA → refuse if
  another user already owns it → register it on the Cloud API if it's a brand
  new number (skipped for coexistence numbers) → subscribe our app to the
  WABA's webhooks → save on the User row.

All Meta calls go through _client() so tests can swap in a fake transport.
Error text shown to the user is deliberately generic; Meta's raw error goes to
the logs only (it can contain ids, and must never contain tokens).
"""

import logging
import re
import secrets
from typing import Optional

import httpx

from app.config import get_settings
from app.models import User

logger = logging.getLogger(__name__)

GRAPH_ROOT = "https://graph.facebook.com"
_ID_RE = re.compile(r"^\d{5,32}$")      # Meta ids are numeric; blocks path tricks like "../x"


class WhatsAppConnectError(Exception):
    """An error whose message is safe to show to the end user."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=20.0)


def _base() -> str:
    return f"{GRAPH_ROOT}/{get_settings().whatsapp_graph_version}"


def _enabled() -> bool:
    s = get_settings()
    return bool(
        s.whatsapp_app_id and s.whatsapp_config_id
        and s.whatsapp_app_secret.get_secret_value() and s.whatsapp_verify_token
    )


async def _graph(method: str, path: str, *, token: Optional[str] = None,
                 params: Optional[dict] = None, json_body: Optional[dict] = None) -> dict:
    """One Graph API call. Raises WhatsAppConnectError(502) on any failure."""
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        async with _client() as client:
            resp = await client.request(method, f"{_base()}{path}", headers=headers,
                                        params=params, json=json_body)
    except httpx.HTTPError as exc:
        logger.error("Graph %s %s network error: %s", method, path, type(exc).__name__)
        raise WhatsAppConnectError("Could not reach WhatsApp. Please try again.", 502)

    try:
        data = resp.json()
    except ValueError:
        data = {}
    if resp.status_code >= 400 or (isinstance(data, dict) and "error" in data):
        err = data.get("error", {}) if isinstance(data, dict) else {}
        logger.error("Graph %s %s failed (%s): code=%s message=%s",
                     method, path, resp.status_code, err.get("code"), err.get("message"))
        raise WhatsAppConnectError("WhatsApp rejected the request. Please try connecting again.", 502)
    return data if isinstance(data, dict) else {}


# ── Individual Graph calls ───────────────────────────────────────────────────

async def exchange_code(code: str) -> str:
    s = get_settings()
    data = await _graph("GET", "/oauth/access_token", params={
        "client_id": s.whatsapp_app_id,
        "client_secret": s.whatsapp_app_secret.get_secret_value(),
        "code": code,
    })
    token = data.get("access_token")
    if not token:
        raise WhatsAppConnectError("WhatsApp did not return an access token. Please try again.", 502)
    return token


async def list_phone_numbers(token: str, waba_id: str) -> list[dict]:
    data = await _graph("GET", f"/{waba_id}/phone_numbers", token=token,
                        params={"fields": "id,display_phone_number,verified_name"})
    return data.get("data") or []


async def get_phone_info(token: str, phone_number_id: str) -> dict:
    """Best effort — returns {} if Meta rejects the extra fields."""
    try:
        return await _graph("GET", f"/{phone_number_id}", token=token,
                            params={"fields": "display_phone_number,platform_type,is_on_biz_app"})
    except WhatsAppConnectError:
        return {}


async def subscribe_waba(token: str, waba_id: str) -> None:
    await _graph("POST", f"/{waba_id}/subscribed_apps", token=token)


async def unsubscribe_waba(token: str, waba_id: str) -> None:
    await _graph("DELETE", f"/{waba_id}/subscribed_apps", token=token)


async def register_number(token: str, phone_number_id: str, pin: str) -> None:
    await _graph("POST", f"/{phone_number_id}/register", token=token,
                 json_body={"messaging_product": "whatsapp", "pin": pin})


# ── Connect / disconnect ─────────────────────────────────────────────────────

async def connect_whatsapp(db, user: User, code: str, waba_id: str,
                           phone_number_id: Optional[str]) -> dict:
    if not _enabled():
        raise WhatsAppConnectError("WhatsApp connect is not enabled on this server.", 503)
    if not user.workspace_id:
        raise WhatsAppConnectError("Finish setting up your workspace before connecting WhatsApp.", 400)
    if not code or not code.strip():
        raise WhatsAppConnectError("Missing authorization code.", 400)
    if not _ID_RE.match(waba_id or ""):
        raise WhatsAppConnectError("Invalid WhatsApp Business Account id.", 400)
    if phone_number_id is not None and not _ID_RE.match(phone_number_id):
        raise WhatsAppConnectError("Invalid phone number id.", 400)

    token = await exchange_code(code.strip())

    # Only numbers the token can actually see under this WABA are acceptable —
    # this is what stops a user claiming a phone_number_id that isn't theirs.
    numbers = await list_phone_numbers(token, waba_id)
    by_id = {n.get("id"): n for n in numbers if n.get("id")}
    if not by_id:
        raise WhatsAppConnectError("No WhatsApp number was found on that account.", 400)

    if phone_number_id:
        if phone_number_id not in by_id:
            raise WhatsAppConnectError("That number does not belong to the connected account.", 403)
        chosen = phone_number_id
    elif len(by_id) == 1:
        chosen = next(iter(by_id))
    else:
        # Coexistence reports only the WABA. Prefer the number that is on the
        # WhatsApp Business app; otherwise fall back to the first one.
        chosen = next(iter(by_id))
        for pid in by_id:
            if (await get_phone_info(token, pid)).get("is_on_biz_app") is True:
                chosen = pid
                break

    owner = (
        db.query(User)
        .filter(User.whatsapp_phone_number_id == chosen, User.id != user.id)
        .first()
    )
    if owner:
        raise WhatsAppConnectError("That WhatsApp number is already connected to another account.", 409)

    info = await get_phone_info(token, chosen)
    coexistence = info.get("is_on_biz_app") is True
    already_cloud = info.get("platform_type") == "CLOUD_API"
    if not coexistence and not already_cloud:
        pin = get_settings().whatsapp_registration_pin
        if not re.fullmatch(r"\d{6}", pin or ""):
            raise WhatsAppConnectError(
                "This new number needs registering, but WHATSAPP_REGISTRATION_PIN (6 digits) "
                "is not set on the server.", 503)
        await register_number(token, chosen, pin)

    await subscribe_waba(token, waba_id)

    display = (info.get("display_phone_number")
               or by_id[chosen].get("display_phone_number") or "")
    user.whatsapp_connected = True
    user.whatsapp_phone_number_id = chosen
    user.whatsapp_waba_id = waba_id
    user.whatsapp_display_number = display[:32] or None
    user.whatsapp_access_token = token
    db.add(user)
    db.commit()
    logger.info("WhatsApp connected for user_id=%s phone_number_id=%s coexistence=%s",
                user.id, chosen, coexistence)
    return {"connected": True, "display_number": user.whatsapp_display_number,
            "coexistence": coexistence}


async def disconnect_whatsapp(db, user: User) -> None:
    # Best effort: stop Meta sending this account's messages to us. Whether or
    # not that succeeds, the local connection is cleared.
    if user.whatsapp_access_token and user.whatsapp_waba_id and _ID_RE.match(user.whatsapp_waba_id):
        try:
            await unsubscribe_waba(user.whatsapp_access_token, user.whatsapp_waba_id)
        except WhatsAppConnectError:
            logger.warning("WhatsApp unsubscribe failed for user_id=%s; clearing locally anyway", user.id)
    user.whatsapp_connected = False
    user.whatsapp_phone_number_id = None
    user.whatsapp_waba_id = None
    user.whatsapp_display_number = None
    user.whatsapp_access_token = None
    db.add(user)
    db.commit()
    logger.info("WhatsApp disconnected for user_id=%s", user.id)
