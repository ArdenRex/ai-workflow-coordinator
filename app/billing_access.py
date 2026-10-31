"""
billing_access.py
-----------------
Server-side enforcement of "no access after the trial unless you pay (or the
admin lets you in)".

Before this existed the paywall was frontend-only: GET /auth/billing-status
told the React app to show a billing screen, but every other API endpoint kept
working for anyone holding a login token. Now every authenticated request goes
through billing_gate() (registered once, app-wide, in main.py) and a blocked
user gets HTTP 402 Payment Required.

Who is allowed (mirrors what the frontend already does):
  - admins (emails in ADMIN_EMAILS)                      -> always
  - subscription_status "exempt"  (admin panel override) -> always
  - subscription_status "freelancer"                     -> always
  - subscription_status "active"  (paid)                 -> yes
  - subscription_status "trialing" and trial not ended   -> yes
Everyone else is blocked: an ended trial, "cancelled", "past_due", or any
unknown status (fail closed).

Blocked users can still reach what they need to log in, see the billing screen
and pay: /auth/* (login, me, billing-status, logout, refresh, ...) and
/billing/*. The two integration areas that live under /auth (/auth/gmail,
/auth/whatsapp) are blocked like everything else.

The gate only acts when the request carries a valid login. Requests with no or
an invalid token are untouched (the route's own auth answers 401), and so are
webhooks from Slack/Polar/WhatsApp, which authenticate by signature instead.

Entry points that don't use a login apply the same rule themselves, through
is_user_blocked() / is_user_id_blocked(): public API keys (402), the Slack,
Teams, WhatsApp and email bots (task not created), the Gmail poller, and the
reminder/rollup scheduler jobs. Each bills the user it already attributes the
task to (the sender, or the workspace owner).
"""

import logging
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth import get_current_user_optional
from app.database import get_db
from app.models import User

logger = logging.getLogger(__name__)

ADMIN_EMAILS = [e.strip().lower() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip()]

ALWAYS_ALLOWED_STATUSES = {"exempt", "freelancer", "active"}

# Paths a blocked user must still be able to reach.
_OPEN_PREFIXES = ("/auth/", "/billing/")
# ...except these, which are product features that merely live under /auth.
_BLOCKED_UNDER_AUTH = ("/auth/gmail", "/auth/whatsapp")

PAYMENT_REQUIRED_MESSAGE = (
    "Your free trial has ended. Please subscribe to keep using the app."
)


def _is_admin(user: User) -> bool:
    return bool(user.email) and user.email.lower() in ADMIN_EMAILS


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def start_trial_clock_if_missing(db: Session, user: User, now: Optional[datetime] = None) -> None:
    """
    A "trialing" user with no end date (older Slack sign-ups) would otherwise
    be treated as an ended trial. Give them a fresh 7 days, exactly as
    GET /auth/billing-status does.
    """
    if user.subscription_status == "trialing" and not user.trial_ends_at:
        from datetime import timedelta
        from app.routers.auth import TRIAL_DAYS   # local import: avoids a circular import at startup

        user.trial_ends_at = (now or datetime.now(timezone.utc)) + timedelta(days=TRIAL_DAYS)
        db.commit()
        db.refresh(user)


def is_billing_blocked(user: User, now: Optional[datetime] = None) -> bool:
    """True if this user must pay (or be exempted by an admin) before using the app."""
    if _is_admin(user):
        return False
    st = user.subscription_status
    if st in ALWAYS_ALLOWED_STATUSES:
        return False
    if st == "trialing" and user.trial_ends_at:
        return _aware(user.trial_ends_at) <= (now or datetime.now(timezone.utc))
    return True   # ended trial, cancelled, past_due, trialing with no end date, unknown


def is_user_blocked(db: Session, user: User) -> bool:
    """is_billing_blocked() for non-HTTP callers (bots, pollers, schedulers): starts the trial clock if missing first."""
    start_trial_clock_if_missing(db, user)
    return is_billing_blocked(user)


def is_user_id_blocked(db: Session, user_id: Optional[int]) -> bool:
    """
    Same, by user id. No user to bill (None / deleted) -> False: usage that can't
    be tied to anyone is left as it was rather than newly broken.
    """
    if not user_id:
        return False
    user = db.get(User, user_id)
    return bool(user) and is_user_blocked(db, user)


def _route_path(request: Request) -> str:
    route = request.scope.get("route")
    return getattr(route, "path", None) or request.url.path


def is_open_for_blocked_users(path: str) -> bool:
    if path.startswith(_BLOCKED_UNDER_AUTH):
        return False
    return path.startswith(_OPEN_PREFIXES)


def billing_gate(
    request: Request,
    user: Optional[User] = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
) -> None:
    """App-wide dependency: 402 for a blocked, logged-in user on any non-open route."""
    if user is None:
        return                                   # not logged in -> the route's own auth decides
    if is_open_for_blocked_users(_route_path(request)):
        return
    start_trial_clock_if_missing(db, user)
    if is_billing_blocked(user):
        logger.info("Billing gate: 402 for user_id=%s status=%s path=%s",
                    user.id, user.subscription_status, _route_path(request))
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=PAYMENT_REQUIRED_MESSAGE,
        )
