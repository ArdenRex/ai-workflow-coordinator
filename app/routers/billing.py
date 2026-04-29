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
import os
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi import status as http_status
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["Billing"])

# ── Lemon Squeezy config ──────────────────────────────────────────────────────
LS_API_KEY      = os.getenv("LEMONSQUEEZY_API_KEY", "")
LS_STORE_ID     = os.getenv("LEMONSQUEEZY_STORE_ID", "")
LS_VARIANT_ID   = os.getenv("LEMONSQUEEZY_VARIANT_ID", "")   # $20/month plan variant
LS_WEBHOOK_SECRET = os.getenv("LEMONSQUEEZY_WEBHOOK_SECRET", "")
FRONTEND_URL    = os.getenv("FRONTEND_URL", "").rstrip("/")

LS_API_BASE = "https://api.lemonsqueezy.com/v1"

LS_HEADERS = {
    "Authorization": f"Bearer {LS_API_KEY}",
    "Accept":        "application/vnd.api+json",
    "Content-Type":  "application/vnd.api+json",
}


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
    The user is redirected here to enter their card details.
    After payment, LS redirects back to the dashboard.
    """
    if not all([LS_API_KEY, LS_STORE_ID, LS_VARIANT_ID]):
        # Test mode — simulate webhook by updating user directly in DB
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
            "checkout_url": f"{FRONTEND_URL}?billing=success",
            "test_mode": True,
        }

    try:
        payload = {
            "data": {
                "type": "checkouts",
                "attributes": {
                    "checkout_data": {
                        "email":        current_user.email,
                        "name":         current_user.name,
                        "custom": {
                            "user_id": str(current_user.id),
                        },
                    },
                    "checkout_options": {
                        "embed": False,
                    },
                    "product_options": {
                        "redirect_url":          f"{FRONTEND_URL}?billing=success",
                        "receipt_thank_you_note": "Welcome to AI Workflow Coordinator! Your 7-day trial has ended and your subscription is now active.",
                    },
                },
                "relationships": {
                    "store": {
                        "data": {"type": "stores", "id": str(LS_STORE_ID)},
                    },
                    "variant": {
                        "data": {"type": "variants", "id": str(LS_VARIANT_ID)},
                    },
                },
            }
        }

        response = httpx.post(
            f"{LS_API_BASE}/checkouts",
            headers=LS_HEADERS,
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
        logger.info("Checkout created for user_id=%d", current_user.id)

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
    """Returns the URL where the user can manage their subscription."""
    if not current_user.ls_customer_id:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="No billing account found. Please complete checkout first.",
        )

    if not LS_API_KEY:
        return {"portal_url": f"{FRONTEND_URL}?billing=portal_test"}

    try:
        response = httpx.get(
            f"{LS_API_BASE}/customers/{current_user.ls_customer_id}",
            headers=LS_HEADERS,
            timeout=10,
        )
        data = response.json()
        portal_url = data.get("data", {}).get("attributes", {}).get("urls", {}).get("customer_portal")
        return {"portal_url": portal_url or FRONTEND_URL}
    except Exception as exc:
        logger.warning("Portal URL fetch failed: %s", exc)
        return {"portal_url": FRONTEND_URL}


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
      subscription_created   → status = active, store customer/subscription IDs
      subscription_updated   → update status
      subscription_cancelled → status = cancelled
      subscription_expired   → status = cancelled
      subscription_payment_failed → status = past_due
    """
    body = await request.body()

    # Verify webhook signature
    if LS_WEBHOOK_SECRET:
        expected = hmac.new(
            LS_WEBHOOK_SECRET.encode(),
            body,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, x_signature):
            logger.warning("LS webhook signature mismatch")
            raise HTTPException(
                status_code=http_status.HTTP_401_UNAUTHORIZED,
                detail="Invalid webhook signature.",
            )

    try:
        event = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event_name = event.get("meta", {}).get("event_name", "")
    data       = event.get("data", {})
    attributes = data.get("attributes", {})
    custom     = event.get("meta", {}).get("custom_data", {})

    user_id         = custom.get("user_id")
    ls_customer_id  = str(attributes.get("customer_id", ""))
    ls_sub_id       = str(data.get("id", ""))
    ls_status       = attributes.get("status", "")

    logger.info("LS webhook: event=%s user_id=%s status=%s", event_name, user_id, ls_status)

    # Map LS status to our status
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
        logger.warning("LS webhook missing user_id in custom_data")
        return {"received": True}

    try:
        user = db.query(User).filter(User.id == int(user_id)).first()
        if not user:
            logger.warning("LS webhook: user_id=%s not found", user_id)
            return {"received": True}

        # Don't touch exempt accounts
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
            "User id=%d subscription updated to %s via LS webhook",
            user.id, user.subscription_status,
        )

    except Exception as exc:
        db.rollback()
        logger.exception("LS webhook DB error: %s", exc)

    return {"received": True}
