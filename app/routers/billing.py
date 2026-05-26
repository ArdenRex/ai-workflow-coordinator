"""
routers/billing.py  —  Segment 15
────────────────────────────────────
POST /billing/checkout        →  create Dodo Payments checkout URL
POST /billing/webhook         →  handle Dodo subscription lifecycle events
GET  /billing/portal          →  get customer portal URL
POST /billing/cancel          →  cancel active subscription
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

DODO_API_BASE = "https://api.dodopayments.com"


def _dodo_headers() -> dict:
    """Build Dodo Payments auth headers from current settings."""
    settings = get_settings()
    return {
        "Authorization": f"Bearer {settings.dodo_api_key}",
        "Content-Type":  "application/json",
        "Accept":        "application/json",
    }


def _dodo_configured() -> bool:
    s = get_settings()
    return bool(s.dodo_api_key and s.dodo_product_id)


# ── Checkout ──────────────────────────────────────────────────────────────────

@router.post(
    "/checkout",
    summary="Create a Dodo Payments checkout URL for the current user",
)
def create_checkout(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """
    Creates a Dodo Payments hosted checkout URL.
    The user is redirected to Dodo to enter their real card details.
    After payment Dodo redirects back to the dashboard.
    """
    settings = get_settings()
    frontend_url = settings.frontend_url.rstrip("/")

    if not _dodo_configured():
        # Test / dev mode — mark user active immediately so you can test the flow
        logger.warning("Dodo Payments not configured — simulating subscription in test mode")
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
            "product_id": settings.dodo_product_id,
            "payment_link": True,
            "customer": {
                "email": current_user.email,
                "name":  current_user.name or current_user.email,
            },
            "metadata": {
                "user_id": str(current_user.id),
            },
            "success_url": f"{frontend_url}?billing=success",
            "cancel_url":  frontend_url,
        }

        response = httpx.post(
            f"{DODO_API_BASE}/subscriptions",
            headers=_dodo_headers(),
            json=payload,
            timeout=15,
        )

        if response.status_code not in (200, 201):
            logger.error("Dodo checkout failed: %d %s", response.status_code, response.text)
            raise HTTPException(
                status_code=http_status.HTTP_502_BAD_GATEWAY,
                detail="Payment provider error. Please try again.",
            )

        data = response.json()
        checkout_url = data.get("payment_link") or data.get("checkout_url", "")
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
    summary="Get Dodo Payments customer portal URL",
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

    if not settings.dodo_api_key:
        return {"portal_url": f"{frontend_url}?billing=portal_test"}

    try:
        response = httpx.get(
            f"{DODO_API_BASE}/customers/{current_user.ls_customer_id}/portal",
            headers=_dodo_headers(),
            timeout=10,
        )
        data = response.json()
        portal_url = data.get("url") or data.get("portal_url") or frontend_url
        return {"portal_url": portal_url}
    except Exception as exc:
        logger.warning("Portal URL fetch failed: %s", exc)
        return {"portal_url": frontend_url}


# ── Cancel subscription ───────────────────────────────────────────────────────

@router.post(
    "/cancel",
    summary="Cancel the current user's active Dodo Payments subscription",
)
def cancel_subscription(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """
    Cancels the user's active subscription via the Dodo Payments API.
    The subscription remains active until the end of the billing period,
    then Dodo fires subscription.cancelled which sets status = 'cancelled'.
    In test / dev mode (no Dodo key) we immediately mark status = 'cancelled'.
    """
    settings = get_settings()

    if not current_user.ls_subscription_id:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="No active subscription found.",
        )

    if current_user.subscription_status in ("cancelled", "exempt"):
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="Subscription is already cancelled or not applicable.",
        )

    # ── Test / dev mode ───────────────────────────────────────────────────────
    if not settings.dodo_api_key:
        logger.warning("Dodo Payments not configured — simulating cancellation in test mode")
        try:
            current_user.subscription_status = "cancelled"
            db.commit()
            db.refresh(current_user)
            logger.info("Test mode: user_id=%d subscription cancelled", current_user.id)
        except Exception as exc:
            db.rollback()
            logger.warning("Test mode cancel DB update failed: %s", exc)
        return {"cancelled": True, "test_mode": True, "message": "Subscription cancelled (test mode)."}

    # ── Live mode — call Dodo DELETE /subscriptions/{id} ─────────────────────
    try:
        response = httpx.delete(
            f"{DODO_API_BASE}/subscriptions/{current_user.ls_subscription_id}",
            headers=_dodo_headers(),
            timeout=15,
        )

        if response.status_code not in (200, 204):
            logger.error(
                "Dodo cancel failed: %d %s", response.status_code, response.text
            )
            raise HTTPException(
                status_code=http_status.HTTP_502_BAD_GATEWAY,
                detail="Payment provider error. Please try again or contact support.",
            )

        logger.info(
            "Subscription cancelled via Dodo for user_id=%d sub_id=%s",
            current_user.id, current_user.ls_subscription_id,
        )
        return {
            "cancelled": True,
            "test_mode": False,
            "message": "Your subscription has been cancelled. Access continues until the end of the billing period.",
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Cancel subscription error: %s", exc)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not cancel subscription. Please try again.",
        )


# ── Webhook ───────────────────────────────────────────────────────────────────

@router.post(
    "/webhook",
    summary="Dodo Payments webhook — handles subscription lifecycle events",
    status_code=http_status.HTTP_200_OK,
)
async def dodo_webhook(
    request: Request,
    webhook_id: str = Header(default="", alias="webhook-id"),
    webhook_timestamp: str = Header(default="", alias="webhook-timestamp"),
    webhook_signature: str = Header(default="", alias="webhook-signature"),
    db: Session = Depends(get_db),
) -> dict:
    """
    Handles these Dodo events:
      subscription.active          → status = active
      subscription.on_trial        → status = trialing
      subscription.paused          → status = past_due
      subscription.cancelled       → status = cancelled
      subscription.failed          → status = past_due
      payment.succeeded            → status = active
      payment.failed               → status = past_due
    """
    settings = get_settings()
    body = await request.body()

    # ── Verify HMAC-SHA256 signature (Dodo standard verification) ─────────────
    if settings.dodo_webhook_secret:
        try:
            signed_content = f"{webhook_id}.{webhook_timestamp}.{body.decode('utf-8')}"
            expected = hmac.new(
                settings.dodo_webhook_secret.encode(),
                signed_content.encode(),
                hashlib.sha256,
            ).hexdigest()
            # Dodo sends comma-separated signatures (v1,<hash>)
            sigs = [s.split(",")[-1] for s in webhook_signature.split(" ") if s]
            if not any(hmac.compare_digest(expected, sig) for sig in sigs):
                logger.warning("Dodo webhook signature mismatch — possible spoofed request")
                raise HTTPException(
                    status_code=http_status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid webhook signature.",
                )
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning("Webhook signature verification error: %s", exc)

    try:
        event = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload.")

    event_type = event.get("type", "") or event.get("event_type", "")
    data       = event.get("data", {})
    metadata   = data.get("metadata", {}) or event.get("metadata", {})

    user_id        = metadata.get("user_id")
    dodo_customer  = str(data.get("customer_id", "") or data.get("customer", {}).get("id", ""))
    dodo_sub_id    = str(data.get("id", "") or data.get("subscription_id", ""))
    dodo_status    = data.get("status", "")

    logger.info(
        "Dodo webhook received | event=%s user_id=%s status=%s",
        event_type, user_id, dodo_status,
    )

    # Dodo status → our DB status
    STATUS_MAP = {
        "active":    "active",
        "on_trial":  "trialing",
        "trialing":  "trialing",
        "paused":    "past_due",
        "past_due":  "past_due",
        "unpaid":    "past_due",
        "failed":    "past_due",
        "cancelled": "cancelled",
        "expired":   "cancelled",
    }

    if not user_id:
        logger.warning("Dodo webhook missing user_id in metadata — skipping")
        return {"received": True}

    try:
        user = db.query(User).filter(User.id == int(user_id)).first()
        if not user:
            logger.warning("Dodo webhook: user_id=%s not found in DB", user_id)
            return {"received": True}

        if user.subscription_status == "exempt":
            return {"received": True}

        if event_type in (
            "subscription.active", "subscription.on_trial",
            "subscription.created", "subscription.updated", "subscription.resumed",
        ):
            user.subscription_status = STATUS_MAP.get(dodo_status, "active")
            user.ls_customer_id      = dodo_customer or user.ls_customer_id
            user.ls_subscription_id  = dodo_sub_id or user.ls_subscription_id

        elif event_type in ("subscription.cancelled", "subscription.expired"):
            user.subscription_status = "cancelled"

        elif event_type in ("subscription.failed", "payment.failed"):
            user.subscription_status = "past_due"

        elif event_type in ("payment.succeeded", "subscription_payment_success"):
            user.subscription_status = "active"
            user.ls_customer_id      = dodo_customer or user.ls_customer_id
            user.ls_subscription_id  = dodo_sub_id or user.ls_subscription_id

        db.commit()
        logger.info(
            "User id=%d subscription → %s (event: %s)",
            user.id, user.subscription_status, event_type,
        )

    except Exception as exc:
        db.rollback()
        logger.exception("Dodo webhook DB error for user_id=%s: %s", user_id, exc)

    return {"received": True}
