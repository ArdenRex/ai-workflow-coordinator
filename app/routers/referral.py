"""
app/routers/referral.py
────────────────────────
Freelancer referral tracking system.

PUBLIC (no auth needed):
  GET  /referral/resolve/{code}     → Validate a referral code (used by signup page)

FREELANCER (token required, subscription_status == "freelancer"):
  GET  /referral/my-stats           → Personal stats: total / trial / paid / cancelled

ADMIN only:
  GET  /referral/freelancers        → List all freelancers with stats
  POST /referral/freelancers        → Create a new freelancer + generate their unique link
  PATCH /referral/freelancers/{id}  → Update name / label / active status
  DELETE /referral/freelancers/{id} → Deactivate a freelancer (soft delete)
  GET  /referral/overview           → Aggregated stats: weekly / monthly / quarterly
"""

import logging
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, case
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import Freelancer, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/referral", tags=["Referral"])

ADMIN_EMAILS = [e.strip().lower() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip()]
FRONTEND_URL  = os.getenv("FRONTEND_URL", "").rstrip("/")


# ── Guards ────────────────────────────────────────────────────────────────────

def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.email.lower() not in ADMIN_EMAILS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access only.")
    return current_user


def require_freelancer(current_user: User = Depends(get_current_user)) -> User:
    is_admin      = current_user.email.lower() in ADMIN_EMAILS
    is_freelancer = current_user.subscription_status == "freelancer"
    if not is_admin and not is_freelancer:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Freelancer access only.",
        )
    return current_user


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class FreelancerCreate(BaseModel):
    name:  str      = Field(..., min_length=2, max_length=255)
    email: EmailStr
    label: Optional[str] = Field(None, max_length=255)


class FreelancerUpdate(BaseModel):
    name:      Optional[str]  = Field(None, min_length=2, max_length=255)
    label:     Optional[str]  = Field(None, max_length=255)
    is_active: Optional[bool] = None


class FreelancerOut(BaseModel):
    id:            int
    name:          str
    email:         str
    referral_code: str
    referral_link: str
    invite_link:   str = ""
    slug:          Optional[str] = None
    label:         Optional[str]
    is_active:     bool
    created_at:    datetime

    # Live stats (populated by query, not ORM fields)
    total:     int = 0
    trialing:  int = 0
    paid:      int = 0
    cancelled: int = 0

    model_config = {"from_attributes": True}


class ResolveOut(BaseModel):
    valid:         bool
    freelancer_id: Optional[int]  = None
    name:          Optional[str]  = None
    referral_code: Optional[str]  = None


class MyStatsOut(BaseModel):
    freelancer_id: int
    name:          str
    referral_code: str
    referral_link: str
    invite_link:   str = ""   # populated by my-stats-by-code; empty for JWT route
    total:         int
    trialing:      int
    paid:          int
    cancelled:     int


class OverviewOut(BaseModel):
    period:    str   # "weekly" | "monthly" | "quarterly"
    rows: list[dict]  # [{freelancer, total, trialing, paid, cancelled}]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_link(code: str) -> str:
    return f"{FRONTEND_URL}/register?ref={code}"


def _make_slug(name: str) -> str:
    """Convert a freelancer name to a URL-friendly slug. e.g. 'John Doe' → 'john-doe'"""
    slug = name.strip().lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug


def _stats_for_code(db: Session, code: str) -> dict:
    """Return {total, trialing, paid, cancelled} for a given referral code."""
    rows = (
        db.query(
            User.subscription_status,
            func.count(User.id).label("cnt"),
        )
        .filter(User.referred_by_code == code)
        .group_by(User.subscription_status)
        .all()
    )
    out = {"total": 0, "trialing": 0, "paid": 0, "cancelled": 0}
    for status_val, cnt in rows:
        out["total"] += cnt
        if status_val in ("trialing",):
            out["trialing"] += cnt
        elif status_val in ("active", "exempt"):
            out["paid"] += cnt
        elif status_val in ("cancelled",):
            out["cancelled"] += cnt
    return out


def _stats_for_code_since(db: Session, code: str, since: datetime) -> dict:
    """Like _stats_for_code but only counts users created on or after `since`."""
    rows = (
        db.query(
            User.subscription_status,
            func.count(User.id).label("cnt"),
        )
        .filter(
            User.referred_by_code == code,
            User.created_at >= since,
        )
        .group_by(User.subscription_status)
        .all()
    )
    out = {"total": 0, "trialing": 0, "paid": 0, "cancelled": 0}
    for status_val, cnt in rows:
        out["total"] += cnt
        if status_val in ("trialing",):
            out["trialing"] += cnt
        elif status_val in ("active", "exempt"):
            out["paid"] += cnt
        elif status_val in ("cancelled",):
            out["cancelled"] += cnt
    return out


def _freelancer_out(f: Freelancer, db: Session) -> FreelancerOut:
    stats = _stats_for_code(db, f.referral_code)
    slug = f.slug or _make_slug(f.name)
    return FreelancerOut(
        id=f.id,
        name=f.name,
        email=f.email,
        referral_code=f.referral_code,
        referral_link=_make_link(f.referral_code),
        invite_link=f"{FRONTEND_URL}/invite/{slug}",
        slug=slug,
        label=f.label,
        is_active=f.is_active,
        created_at=f.created_at,
        **stats,
    )


# ── PUBLIC: resolve a referral code ──────────────────────────────────────────

@router.get(
    "/resolve/{code}",
    response_model=ResolveOut,
    summary="Check if a referral code is valid (called during signup)",
)
def resolve_referral_code(code: str, db: Session = Depends(get_db)) -> ResolveOut:
    """
    Frontend calls this when a user lands on /register?ref=CODE.
    Returns the freelancer name so the signup page can show 'Referred by John'.
    """
    freelancer = (
        db.query(Freelancer)
        .filter(Freelancer.referral_code == code, Freelancer.is_active == True)
        .first()
    )
    if not freelancer:
        return ResolveOut(valid=False)
    return ResolveOut(
        valid=True,
        freelancer_id=freelancer.id,
        name=freelancer.name,
        referral_code=freelancer.referral_code,
    )


@router.get(
    "/resolve-slug/{slug}",
    response_model=ResolveOut,
    summary="Resolve an /invite/:slug link to a referral code (public)",
)
def resolve_referral_slug(slug: str, db: Session = Depends(get_db)) -> ResolveOut:
    """
    Frontend calls this when a user lands on /invite/john-doe.
    Looks up the freelancer by slug and returns their referral code
    so the frontend can redirect to /register?ref=CODE.
    """
    freelancer = (
        db.query(Freelancer)
        .filter(Freelancer.slug == slug, Freelancer.is_active == True)
        .first()
    )
    if not freelancer:
        return ResolveOut(valid=False)
    return ResolveOut(
        valid=True,
        freelancer_id=freelancer.id,
        name=freelancer.name,
        referral_code=freelancer.referral_code,
    )



# ── FREELANCER DASHBOARD: stats by referral_code (no JWT needed) ─────────────
#
# The freelancer dashboard (separate Vercel deployment) authenticates using
# only a slug + local password. It never creates a User account so it cannot
# get a JWT. This endpoint lets the dashboard fetch stats by passing the
# referral_code directly as the Bearer token — read-only, no mutations.

@router.get(
    "/my-stats-by-code",
    response_model=MyStatsOut,
    summary="Freelancer dashboard — fetch own stats using referral_code as Bearer token",
)
def my_stats_by_code(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> MyStatsOut:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing authorization header.")
    code = authorization.split(" ", 1)[1].strip()
    if not code:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Empty referral code.")

    freelancer = (
        db.query(Freelancer)
        .filter(Freelancer.referral_code == code, Freelancer.is_active == True)
        .first()
    )
    if not freelancer:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or inactive referral code.")

    stats = _stats_for_code(db, freelancer.referral_code)
    slug = freelancer.slug or _make_slug(freelancer.name)
    return MyStatsOut(
        freelancer_id=freelancer.id,
        name=freelancer.name,
        referral_code=freelancer.referral_code,
        referral_link=_make_link(freelancer.referral_code),
        invite_link=f"{FRONTEND_URL}/invite/{slug}",
        **stats,
    )

# ── FREELANCER: my own stats ──────────────────────────────────────────────────

@router.get(
    "/my-stats",
    response_model=MyStatsOut,
    summary="Freelancer views their own referral stats",
)
def my_stats(
    current_user: User = Depends(require_freelancer),
    db: Session = Depends(get_db),
) -> MyStatsOut:
    """
    Freelancers (subscription_status == 'freelancer') call this to see
    how many users they referred and each user's subscription status.
    Admins can also call this — it looks up the freelancer record by email.
    """
    freelancer = (
        db.query(Freelancer)
        .filter(Freelancer.email == current_user.email.lower())
        .first()
    )
    if not freelancer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No freelancer profile found for your account. Contact your admin.",
        )

    stats = _stats_for_code(db, freelancer.referral_code)
    return MyStatsOut(
        freelancer_id=freelancer.id,
        name=freelancer.name,
        referral_code=freelancer.referral_code,
        referral_link=_make_link(freelancer.referral_code),
        **stats,
    )


# ── ADMIN: list all freelancers ───────────────────────────────────────────────

@router.get(
    "/freelancers",
    response_model=list[FreelancerOut],
    summary="Admin — list all freelancers with live stats",
)
def list_freelancers(
    active_only: bool = Query(False, description="If true, only return active freelancers"),
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[FreelancerOut]:
    q = db.query(Freelancer)
    if active_only:
        q = q.filter(Freelancer.is_active == True)
    freelancers = q.order_by(Freelancer.created_at.desc()).all()
    return [_freelancer_out(f, db) for f in freelancers]


# ── ADMIN: create a freelancer ────────────────────────────────────────────────

@router.post(
    "/freelancers",
    response_model=FreelancerOut,
    status_code=status.HTTP_201_CREATED,
    summary="Admin — add a new freelancer and generate their referral link",
)
def create_freelancer(
    payload: FreelancerCreate,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> FreelancerOut:
    existing = db.query(Freelancer).filter(Freelancer.email == payload.email.lower()).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A freelancer with email {payload.email} already exists.",
        )

    # Generate a short, memorable referral code
    code = secrets.token_urlsafe(6).upper()[:8]
    # Ensure uniqueness (extremely unlikely collision but let's be safe)
    while db.query(Freelancer).filter(Freelancer.referral_code == code).first():
        code = secrets.token_urlsafe(6).upper()[:8]

    # Generate a URL-friendly slug from the name, ensure uniqueness
    base_slug = _make_slug(payload.name)
    slug = base_slug
    counter = 2
    while db.query(Freelancer).filter(Freelancer.slug == slug).first():
        slug = f"{base_slug}-{counter}"
        counter += 1

    freelancer = Freelancer(
        name=payload.name.strip(),
        email=payload.email.strip().lower(),
        referral_code=code,
        slug=slug,
        label=payload.label,
        is_active=True,
    )
    db.add(freelancer)
    db.commit()
    db.refresh(freelancer)

    logger.info(
        "Freelancer created: id=%d email=%s code=%s",
        freelancer.id, freelancer.email, freelancer.referral_code,
    )
    return _freelancer_out(freelancer, db)


# ── ADMIN: update a freelancer ────────────────────────────────────────────────

@router.patch(
    "/freelancers/{freelancer_id}",
    response_model=FreelancerOut,
    summary="Admin — update freelancer name, label, or active status",
)
def update_freelancer(
    freelancer_id: int,
    payload: FreelancerUpdate,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> FreelancerOut:
    freelancer = db.query(Freelancer).filter(Freelancer.id == freelancer_id).first()
    if not freelancer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Freelancer not found.")

    if payload.name      is not None: freelancer.name      = payload.name.strip()
    if payload.label     is not None: freelancer.label     = payload.label
    if payload.is_active is not None: freelancer.is_active = payload.is_active

    db.commit()
    db.refresh(freelancer)
    return _freelancer_out(freelancer, db)


# ── ADMIN: deactivate a freelancer ────────────────────────────────────────────

@router.delete(
    "/freelancers/{freelancer_id}",
    summary="Admin — deactivate a freelancer (soft delete)",
)
def deactivate_freelancer(
    freelancer_id: int,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    freelancer = db.query(Freelancer).filter(Freelancer.id == freelancer_id).first()
    if not freelancer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Freelancer not found.")

    freelancer.is_active = False
    db.commit()
    logger.info("Freelancer deactivated: id=%d email=%s", freelancer.id, freelancer.email)
    return {"deactivated": True, "id": freelancer_id}


# ── ADMIN: overview (weekly / monthly / quarterly) ────────────────────────────

@router.get(
    "/overview",
    response_model=OverviewOut,
    summary="Admin — referral stats broken down by period per freelancer",
)
def referral_overview(
    period: str = Query("monthly", description="weekly | monthly | quarterly"),
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> OverviewOut:
    now = datetime.now(timezone.utc)
    period_map = {
        "weekly":    timedelta(weeks=1),
        "monthly":   timedelta(days=30),
        "quarterly": timedelta(days=90),
    }
    if period not in period_map:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="period must be one of: weekly, monthly, quarterly",
        )
    since = now - period_map[period]

    freelancers = db.query(Freelancer).order_by(Freelancer.name).all()
    rows = []
    for f in freelancers:
        stats = _stats_for_code_since(db, f.referral_code, since)
        rows.append({
            "freelancer_id":   f.id,
            "freelancer_name": f.name,
            "referral_code":   f.referral_code,
            "referral_link":   _make_link(f.referral_code),
            "label":           f.label,
            "is_active":       f.is_active,
            **stats,
        })

    # Sort by total desc
    rows.sort(key=lambda r: r["total"], reverse=True)
    return OverviewOut(period=period, rows=rows)
