"""
routers/billing.py
────────────────────────────────────
POST /billing/checkout        →  create Polar checkout URL
POST /billing/webhook         →  handle Polar subscription lifecycle events
GET  /billing/portal          →  get customer portal URL
POST /billing/cancel          →  cancel active subscription
"""

import base64
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
from app.notifications import notify_card_added

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["Billing"])

POLAR_API_BASE = "https://api.polar.sh/v1"


def _polar_headers() -> dict:
    """Build Polar auth headers from current settings."""
    settings = get_settings()
    return {
        "Authorization": f"Bearer {settings.polar_api_key}",
        "Content-Type":  "application/json",
        "Accept":        "application/json",
    }


def _polar_configured() -> bool:
    s = get_settings()
    return bool(s.polar_api_key and s.polar_product_id)


# ── Checkout ──────────────────────────────────────────────────────────────────

@router.post(
    "/checkout",
    summary="Create a Polar checkout URL for the current user",
)
def create_checkout(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """
    Creates a Polar hosted checkout URL.
    The user is redirected to Polar to enter their real card details.
    After payment Polar redirects back to the dashboard.
    """
    settings = get_settings()
    frontend_url = settings.frontend_url.rstrip("/")

    if not _polar_configured():
        # Test / dev mode — mark user active immediately so you can test the flow
        logger.warning("Polar not configured — simulating subscription in test mode")
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
            "product_id": settings.polar_product_id,
            "customer_email": current_user.email,
            "customer_name": current_user.name or current_user.email,
            "metadata": {
                "user_id": str(current_user.id),
            },
            "success_url": f"{frontend_url}?billing=success",
        }

        response = httpx.post(
            f"{POLAR_API_BASE}/checkouts",
            headers=_polar_headers(),
            json=payload,
            timeout=15,
            follow_redirects=True,
        )

        if response.status_code not in (200, 201):
            logger.error("Polar checkout failed: %d %s", response.status_code, response.text)
            raise HTTPException(
                status_code=http_status.HTTP_502_BAD_GATEWAY,
                detail="Payment provider error. Please try again.",
            )

        data = response.json()
        checkout_url = data.get("url") or data.get("checkout_url", "")
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
    summary="Get Polar customer portal URL",
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

    if not settings.polar_api_key:
        return {"portal_url": f"{frontend_url}?billing=portal_test"}

    try:
        response = httpx.post(
            f"{POLAR_API_BASE}/customer-sessions",
            headers=_polar_headers(),
            json={"customer_id": current_user.ls_customer_id},
            timeout=10,
        )
        data = response.json()
        portal_url = data.get("customer_portal_url") or frontend_url
        return {"portal_url": portal_url}
    except Exception as exc:
        logger.warning("Portal URL fetch failed: %s", exc)
        return {"portal_url": frontend_url}


# ── Cancel subscription ───────────────────────────────────────────────────────

@router.post(
    "/cancel",
    summary="Cancel the current user's active Polar subscription",
)
def cancel_subscription(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """
    Cancels the user's active subscription via the Polar API.
    The subscription remains active until the end of the billing period,
    then Polar fires subscription.canceled which sets status = 'cancelled'.
    In test / dev mode (no Polar key) we immediately mark status = 'cancelled'.
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
    if not settings.polar_api_key:
        logger.warning("Polar not configured — simulating cancellation in test mode")
        try:
            current_user.subscription_status = "cancelled"
            db.commit()
            db.refresh(current_user)
            logger.info("Test mode: user_id=%d subscription cancelled", current_user.id)
        except Exception as exc:
            db.rollback()
            logger.warning("Test mode cancel DB update failed: %s", exc)
        return {"cancelled": True, "test_mode": True, "message": "Subscription cancelled (test mode)."}

    # ── Live mode — call Polar DELETE /subscriptions/{id} ────────────────────
    try:
        response = httpx.delete(
            f"{POLAR_API_BASE}/subscriptions/{current_user.ls_subscription_id}",
            headers=_polar_headers(),
            timeout=15,
        )

        if response.status_code not in (200, 204):
            logger.error(
                "Polar cancel failed: %d %s", response.status_code, response.text
            )
            raise HTTPException(
                status_code=http_status.HTTP_502_BAD_GATEWAY,
                detail="Payment provider error. Please try again or contact support.",
            )

        logger.info(
            "Subscription cancelled via Polar for user_id=%d sub_id=%s",
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
    summary="Polar webhook — handles subscription lifecycle events",
    status_code=http_status.HTTP_200_OK,
)
async def polar_webhook(
    request: Request,
    webhook_id: str = Header(default="", alias="webhook-id"),
    webhook_timestamp: str = Header(default="", alias="webhook-timestamp"),
    webhook_signature: str = Header(default="", alias="webhook-signature"),
    db: Session = Depends(get_db),
) -> dict:
    """
    Handles these Polar events:
      subscription.created         → status = trialing / active
      subscription.active          → status = active
      subscription.updated         → update status from payload
      subscription.canceled        → status = cancelled
      subscription.revoked         → status = cancelled
      order.created                → status = active (renewal)
    """
    settings = get_settings()
    body = await request.body()

    # ── Verify Standard Webhooks signature (Polar uses Standard Webhooks spec) ─
    if settings.polar_webhook_secret:
        try:
            # Standard Webhooks: HMAC-SHA256, secret is base64-decoded first
            secret = settings.polar_webhook_secret
            # Strip whsec_ prefix if present
            if secret.startswith("whsec_"):
                secret = secret[len("whsec_"):]
            secret_bytes = base64.b64decode(secret) if _is_base64(secret) else secret.encode()

            signed_content = f"{webhook_id}.{webhook_timestamp}.{body.decode('utf-8')}"
            expected = base64.b64encode(
                hmac.new(secret_bytes, signed_content.encode(), hashlib.sha256).digest()
            ).decode()

            sigs = [s.split(",", 1)[-1] for s in webhook_signature.split(" ") if s]
            if not any(hmac.compare_digest(expected, sig) for sig in sigs):
                logger.warning("Polar webhook signature mismatch — possible spoofed request")
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

    event_type = event.get("type", "")
    data       = event.get("data", {})
    metadata   = data.get("metadata", {}) or {}

    user_id       = metadata.get("user_id")
    polar_customer = str(data.get("customer_id", "") or "")
    polar_sub_id   = str(data.get("id", "") or "")
    polar_status   = data.get("status", "")

    logger.info(
        "Polar webhook received | event=%s user_id=%s status=%s",
        event_type, user_id, polar_status,
    )

    # Polar status → our DB status
    STATUS_MAP = {
        "active":        "active",
        "trialing":      "trialing",
        "past_due":      "past_due",
        "unpaid":        "past_due",
        "canceled":      "cancelled",
        "cancelled":     "cancelled",
        "incomplete":    "past_due",
        "revoked":       "cancelled",
    }

    if not user_id:
        logger.warning("Polar webhook missing user_id in metadata — skipping")
        return {"received": True}

    try:
        user = db.query(User).filter(User.id == int(user_id)).first()
        if not user:
            logger.warning("Polar webhook: user_id=%s not found in DB", user_id)
            return {"received": True}

        if user.subscription_status == "exempt":
            return {"received": True}

        if event_type in (
            "subscription.created",
            "subscription.active",
            "subscription.updated",
        ):
            user.subscription_status = STATUS_MAP.get(polar_status, "active")
            user.ls_customer_id      = polar_customer or user.ls_customer_id
            user.ls_subscription_id  = polar_sub_id or user.ls_subscription_id

            # Notify only on first-time subscription creation
            if event_type == "subscription.created":
                import threading
                threading.Thread(
                    target=notify_card_added,
                    args=(user.name, user.email),
                    daemon=True,
                ).start()

        elif event_type in ("subscription.canceled", "subscription.revoked"):
            user.subscription_status = "cancelled"

        elif event_type == "order.created":
            # Renewal payment — mark active
            billing_reason = data.get("billing_reason", "")
            if billing_reason in ("subscription_cycle", "subscription_create", "purchase"):
                user.subscription_status = "active"
                user.ls_customer_id      = polar_customer or user.ls_customer_id

        db.commit()
        logger.info(
            "User id=%d subscription → %s (event: %s)",
            user.id, user.subscription_status, event_type,
        )

    except Exception as exc:
        db.rollback()
        logger.exception("Polar webhook DB error for user_id=%s: %s", user_id, exc)

    return {"received": True}


def _is_base64(s: str) -> bool:
    """Check if a string looks like valid base64."""
    try:
        base64.b64decode(s, validate=True)
        return True
    except Exception:
        return False
