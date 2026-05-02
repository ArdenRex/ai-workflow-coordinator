"""
routers/billing.py  —  Segment 15
────────────────────────────────────
POST /billing/checkout        →  create Lemon Squeezy checkout URL
POST /billing/webhook         →  handle LS subscription events
GET  /billing/portal          →  get customer portal URL
"""

import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi import status as http_status
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.config import get_settings
from app.database import get_db
from app.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["Billing"])

LS_API_BASE = "https://api.lemonsqueezy.com/v1"


def _ls_headers() -> dict:
    """Build Lemon Squeezy auth headers from current settings."""
    settings = get_settings()
    return {
        "Authorization": f"Bearer {settings.lemonsqueezy_api_key}",
        "Accept":        "application/vnd.api+json",
        "Content-Type":  "application/vnd.api+json",
    }


def _ls_configured() -> bool:
    s = get_settings()
    return bool(s.lemonsqueezy_api_key and s.lemonsqueezy_store_id and s.lemonsqueezy_variant_id)


# ── Checkout ──────────────────────────────────────────────────────────────────

@router.post(
    "/checkout",
    summary="Create a Lemon Squeezy checkout URL for the current user",
)
def create_checkout(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """
    Creates a Lemon Squeezy hosted checkout URL.
    The user is redirected to LS to enter their real card details.
    After payment LS redirects back to the dashboard.
    """
    settings = get_settings()
    frontend_url = settings.frontend_url.rstrip("/")

    if not _ls_configured():
        # Test / dev mode — mark user active immediately so you can test the flow
        logger.warning("Lemon Squeezy not configured — simulating subscription in test mode")
        try:
            current_user.subscription_status = "active"
            current_user.ls_customer_id      = f"test_customer_{current_user.id}"
            current_user.ls_subscription_id  = f"test_sub_{current_user.id}"
            db.commit()
            db.refresh(current_user)
            logger.info("Test mode: user_id=%d marked as active", current_user.id)
        except Exception as exc:
            db.rollback()
            logger.warning("Test mode DB update failed: %s", exc)
        return {
            "checkout_url": f"{frontend_url}?billing=success",
            "test_mode": True,
        }

    try:
        payload = {
            "data": {
                "type": "checkouts",
                "attributes": {
                    "checkout_data": {
                        "email":  current_user.email,
                        "name":   current_user.name,
                        "custom": {
                            "user_id": str(current_user.id),
                        },
                    },
                    "checkout_options": {
                        "embed": False,
                    },
                    "product_options": {
                        "redirect_url": f"{frontend_url}?billing=success",
                        "receipt_thank_you_note": (
                            "Welcome to AI Workflow Coordinator! "
                            "Your 7-day free trial is now active."
                        ),
                    },
                },
                "relationships": {
                    "store": {
                        "data": {"type": "stores", "id": str(settings.lemonsqueezy_store_id)},
                    },
                    "variant": {
                        "data": {"type": "variants", "id": str(settings.lemonsqueezy_variant_id)},
                    },
                },
            }
        }

        response = httpx.post(
            f"{LS_API_BASE}/checkouts",
            headers=_ls_headers(),
            json=payload,
            timeout=15,
        )

        if response.status_code not in (200, 201):
            logger.error("LS checkout failed: %d %s", response.status_code, response.text)
            raise HTTPException(
                status_code=http_status.HTTP_502_BAD_GATEWAY,
                detail="Payment provider error. Please try again.",
            )

        data = response.json()
        checkout_url = data["data"]["attributes"]["url"]
        logger.info("Checkout URL created for user_id=%d", current_user.id)
        return {"checkout_url": checkout_url, "test_mode": False}

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Checkout creation error: %s", exc)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not create checkout. Please try again.",
        )


# ── Customer portal ───────────────────────────────────────────────────────────

@router.get(
    "/portal",
    summary="Get Lemon Squeezy customer portal URL",
)
def get_portal(
    current_user: User = Depends(get_current_user),
) -> dict:
    """Returns the URL where the user can manage / cancel their subscription."""
    settings = get_settings()
    frontend_url = settings.frontend_url.rstrip("/")

    if not current_user.ls_customer_id:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="No billing account found. Please complete checkout first.",
        )

    if not settings.lemonsqueezy_api_key:
        return {"portal_url": f"{frontend_url}?billing=portal_test"}

    try:
        response = httpx.get(
            f"{LS_API_BASE}/customers/{current_user.ls_customer_id}",
            headers=_ls_headers(),
            timeout=10,
        )
        data = response.json()
        portal_url = (
            data.get("data", {})
                .get("attributes", {})
                .get("urls", {})
                .get("customer_portal")
        )
        return {"portal_url": portal_url or frontend_url}
    except Exception as exc:
        logger.warning("Portal URL fetch failed: %s", exc)
        return {"portal_url": frontend_url}


# ── Webhook ───────────────────────────────────────────────────────────────────

@router.post(
    "/webhook",
    summary="Lemon Squeezy webhook — handles subscription lifecycle events",
    status_code=http_status.HTTP_200_OK,
)
async def lemon_squeezy_webhook(
    request: Request,
    x_signature: str = Header(default="", alias="X-Signature"),
    db: Session = Depends(get_db),
) -> dict:
    """
    Handles these LS events:
      subscription_created        → status = active / trialing
      subscription_updated        → sync status
      subscription_resumed        → status = active
      subscription_cancelled      → status = cancelled
      subscription_expired        → status = cancelled
      subscription_payment_failed → status = past_due
      subscription_payment_success → status = active
    """
    settings = get_settings()
    body = await request.body()

    # ── Verify HMAC-SHA256 signature ──────────────────────────────────────────
    if settings.lemonsqueezy_webhook_secret:
        expected = hmac.new(
            settings.lemonsqueezy_webhook_secret.encode(),
            body,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, x_signature):
            logger.warning("LS webhook signature mismatch — possible spoofed request")
            raise HTTPException(
                status_code=http_status.HTTP_401_UNAUTHORIZED,
                detail="Invalid webhook signature.",
            )

    try:
        event = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload.")

    event_name = event.get("meta", {}).get("event_name", "")
    data       = event.get("data", {})
    attributes = data.get("attributes", {})
    custom     = event.get("meta", {}).get("custom_data", {})

    user_id        = custom.get("user_id")
    ls_customer_id = str(attributes.get("customer_id", ""))
    ls_sub_id      = str(data.get("id", ""))
    ls_status      = attributes.get("status", "")

    logger.info(
        "LS webhook received | event=%s user_id=%s ls_status=%s",
        event_name, user_id, ls_status,
    )

    # LS status → our DB status
    STATUS_MAP = {
        "active":    "active",
        "on_trial":  "trialing",
        "paused":    "past_due",
        "past_due":  "past_due",
        "unpaid":    "past_due",
        "cancelled": "cancelled",
        "expired":   "cancelled",
    }

    if not user_id:
        logger.warning("LS webhook missing user_id in custom_data — skipping")
        return {"received": True}

    try:
        user = db.query(User).filter(User.id == int(user_id)).first()
        if not user:
            logger.warning("LS webhook: user_id=%s not found in DB", user_id)
            return {"received": True}

        # Exempt accounts (e.g. your own admin) are never touched by billing
        if user.subscription_status == "exempt":
            return {"received": True}

        if event_name in ("subscription_created", "subscription_updated", "subscription_resumed"):
            user.subscription_status = STATUS_MAP.get(ls_status, "active")
            user.ls_customer_id      = ls_customer_id or user.ls_customer_id
            user.ls_subscription_id  = ls_sub_id or user.ls_subscription_id

        elif event_name in ("subscription_cancelled", "subscription_expired"):
            user.subscription_status = "cancelled"

        elif event_name == "subscription_payment_failed":
            user.subscription_status = "past_due"

        elif event_name == "subscription_payment_success":
            user.subscription_status = "active"

        db.commit()
        logger.info(
            "User id=%d subscription → %s (event: %s)",
            user.id, user.subscription_status, event_name,
        )

    except Exception as exc:
        db.rollback()
        logger.exception("LS webhook DB error for user_id=%s: %s", user_id, exc)

    return {"received": True}
