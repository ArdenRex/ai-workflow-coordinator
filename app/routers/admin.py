"""
app/routers/admin.py
────────────────────
Super-admin dashboard endpoints.
Only accessible to emails listed in ADMIN_EMAILS env var.

GET /admin/metrics          → Full platform metrics snapshot
GET /admin/users            → Paginated user list with filters
GET /admin/workspaces       → All workspaces with member + task counts
GET /admin/revenue          → Revenue breakdown (monthly / quarterly / yearly)
GET /admin/feedback         → All feedback/bug reports
GET /admin/users/{id}       → Single user detail + actions
PATCH /admin/users/{id}     → Update subscription_status / is_active
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, extract, select, distinct
from sqlalchemy.orm import Session

from app import crud
from app.auth import get_current_user
from app.database import get_db
from app.models import (
    Feedback, FeedbackStatus, Task, TaskStatus, User,
    UserRole, Workspace, Priority,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["Admin"])

ADMIN_EMAILS = [e.strip().lower() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip()]


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.email.lower() not in ADMIN_EMAILS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access only.")
    return current_user


# ── GET /admin/metrics ────────────────────────────────────────────────────────

@router.get("/metrics", summary="Full platform metrics snapshot")
def get_metrics(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> dict:
    now = datetime.now(timezone.utc)

    # ── User counts ──
    total_users     = db.scalar(select(func.count()).select_from(User)) or 0
    active_users    = db.scalar(select(func.count()).where(User.is_active == True)) or 0
    trialing        = db.scalar(select(func.count()).where(User.subscription_status == "trialing")) or 0
    paid            = db.scalar(select(func.count()).where(User.subscription_status == "active")) or 0
    cancelled_subs  = db.scalar(select(func.count()).where(User.subscription_status == "cancelled")) or 0
    exempt          = db.scalar(select(func.count()).where(User.subscription_status == "exempt")) or 0

    # Trial expired (trialing AND trial_ends_at < now)
    trial_expired = db.scalar(
        select(func.count()).where(
            User.subscription_status == "trialing",
            User.trial_ends_at < now,
        )
    ) or 0

    # New users this week
    week_ago = now - timedelta(days=7)
    new_this_week = db.scalar(
        select(func.count()).where(User.created_at >= week_ago)
    ) or 0

    # New users this month
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    new_this_month = db.scalar(
        select(func.count()).where(User.created_at >= month_start)
    ) or 0

    # ── Role breakdown ──
    role_counts = {}
    for role in UserRole:
        count = db.scalar(select(func.count()).where(User.role == role)) or 0
        role_counts[role.value] = count

    # ── Workspace counts ──
    total_workspaces = db.scalar(select(func.count()).select_from(Workspace)) or 0

    # Workspaces with at least 1 task
    active_workspaces = db.scalar(
        select(func.count(distinct(Task.workspace_id))).where(Task.workspace_id.isnot(None))
    ) or 0

    # ── Task counts ──
    total_tasks     = db.scalar(select(func.count()).select_from(Task)) or 0
    completed_tasks = db.scalar(select(func.count()).where(Task.status == TaskStatus.completed)) or 0
    critical_tasks  = db.scalar(
        select(func.count()).where(
            Task.priority == Priority.critical,
            Task.status.in_([TaskStatus.to_do, TaskStatus.in_progress, TaskStatus.pending]),
        )
    ) or 0
    tasks_today = db.scalar(
        select(func.count()).where(Task.created_at >= now.replace(hour=0, minute=0, second=0, microsecond=0))
    ) or 0

    # ── Feedback counts ──
    total_feedback  = db.scalar(select(func.count()).select_from(Feedback)) or 0
    open_bugs       = db.scalar(
        select(func.count()).where(
            Feedback.status == FeedbackStatus.new,
        )
    ) or 0

    # ── Revenue (based on paid users — $29/mo per paid user as placeholder) ──
    # Replace PRICE_PER_USER with your actual plan price
    PRICE_PER_USER = float(os.getenv("PLAN_PRICE_USD", "29"))

    # Monthly cohorts for last 12 months
    monthly_revenue = []
    for i in range(11, -1, -1):
        month_dt = (now.replace(day=1) - timedelta(days=i * 28)).replace(day=1)
        month_paid = db.scalar(
            select(func.count()).where(
                User.subscription_status == "active",
                extract("year",  User.created_at) == month_dt.year,
                extract("month", User.created_at) == month_dt.month,
            )
        ) or 0
        monthly_revenue.append({
            "month": month_dt.strftime("%b %Y"),
            "new_paid": month_paid,
            "revenue": round(month_paid * PRICE_PER_USER, 2),
        })

    mrr  = round(paid * PRICE_PER_USER, 2)
    arr  = round(mrr * 12, 2)

    # Quarterly
    q_start_month = ((now.month - 1) // 3) * 3 + 1
    quarter_start = now.replace(month=q_start_month, day=1, hour=0, minute=0, second=0, microsecond=0)
    quarterly_new_paid = db.scalar(
        select(func.count()).where(
            User.subscription_status == "active",
            User.created_at >= quarter_start,
        )
    ) or 0
    qrr = round(paid * PRICE_PER_USER * 3, 2)

    # ── Signup trend (last 30 days by day) ──
    signup_trend = []
    for i in range(29, -1, -1):
        day = (now - timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day + timedelta(days=1)
        count = db.scalar(
            select(func.count()).where(
                User.created_at >= day,
                User.created_at < day_end,
            )
        ) or 0
        signup_trend.append({"date": day.strftime("%b %d"), "signups": count})

    return {
        "users": {
            "total": total_users,
            "active": active_users,
            "new_this_week": new_this_week,
            "new_this_month": new_this_month,
            "trialing": trialing,
            "trial_expired": trial_expired,
            "paid": paid,
            "cancelled": cancelled_subs,
            "exempt": exempt,
            "by_role": role_counts,
        },
        "workspaces": {
            "total": total_workspaces,
            "active": active_workspaces,
        },
        "tasks": {
            "total": total_tasks,
            "completed": completed_tasks,
            "critical_open": critical_tasks,
            "created_today": tasks_today,
            "completion_rate": round((completed_tasks / total_tasks * 100) if total_tasks else 0, 1),
        },
        "feedback": {
            "total": total_feedback,
            "open": open_bugs,
        },
        "revenue": {
            "plan_price": PRICE_PER_USER,
            "mrr": mrr,
            "arr": arr,
            "qrr": qrr,
            "monthly_breakdown": monthly_revenue,
        },
        "signup_trend": signup_trend,
        "generated_at": now.isoformat(),
    }


# ── GET /admin/users ──────────────────────────────────────────────────────────

@router.get("/users", summary="All users with filters")
def list_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    status_filter: Optional[str] = Query(None, alias="status"),
    role_filter: Optional[str] = Query(None, alias="role"),
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> dict:
    stmt = select(User)
    if status_filter:
        stmt = stmt.where(User.subscription_status == status_filter)
    if role_filter:
        stmt = stmt.where(User.role == role_filter)
    if search:
        stmt = stmt.where(
            User.email.ilike(f"%{search}%") | User.name.ilike(f"%{search}%")
        )

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    users = list(db.scalars(stmt.order_by(User.created_at.desc()).offset(skip).limit(limit)).all())

    now = datetime.now(timezone.utc)

    return {
        "total": total,
        "users": [
            {
                "id": u.id,
                "name": u.name,
                "email": u.email,
                "role": u.role.value,
                "subscription_status": u.subscription_status,
                "is_active": u.is_active,
                "workspace_id": u.workspace_id,
                "trial_ends_at": u.trial_ends_at.isoformat() if u.trial_ends_at else None,
                "trial_expired": (u.trial_ends_at < now) if u.trial_ends_at else False,
                "created_at": u.created_at.isoformat() if u.created_at else None,
                "ls_customer_id": u.ls_customer_id,
                "ls_subscription_id": u.ls_subscription_id,
            }
            for u in users
        ],
    }


# ── PATCH /admin/users/{id} ───────────────────────────────────────────────────

@router.patch("/users/{user_id}", summary="Update user subscription or active status")
def update_user(
    user_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> dict:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    allowed = {"subscription_status", "is_active", "trial_ends_at"}
    for key, val in payload.items():
        if key in allowed:
            if key == "trial_ends_at" and val:
                val = datetime.fromisoformat(val)
            setattr(user, key, val)

    db.commit()
    db.refresh(user)
    return {"ok": True, "user_id": user_id, "updated": list(payload.keys())}


# ── GET /admin/workspaces ─────────────────────────────────────────────────────

@router.get("/workspaces", summary="All workspaces with stats")
def list_workspaces(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> dict:
    workspaces = list(db.scalars(
        select(Workspace).order_by(Workspace.created_at.desc()).offset(skip).limit(limit)
    ).all())
    total = db.scalar(select(func.count()).select_from(Workspace)) or 0

    result = []
    for ws in workspaces:
        member_count = db.scalar(select(func.count()).where(User.workspace_id == ws.id)) or 0
        task_count   = db.scalar(select(func.count()).where(Task.workspace_id == ws.id)) or 0
        owner = db.get(User, ws.owner_id) if ws.owner_id else None
        result.append({
            "id": ws.id,
            "name": ws.name,
            "owner_email": owner.email if owner else None,
            "member_count": member_count,
            "task_count": task_count,
            "is_active": ws.is_active if hasattr(ws, "is_active") else True,
            "created_at": ws.created_at.isoformat() if ws.created_at else None,
        })

    return {"total": total, "workspaces": result}


# ── PATCH /admin/workspaces/{id} ──────────────────────────────────────────────

@router.patch("/workspaces/{workspace_id}", summary="Enable or disable a workspace")
def update_workspace(
    workspace_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict:
    ws = db.get(Workspace, workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found.")

    # Protect the admin's own workspace from being disabled
    owner = db.get(User, ws.owner_id) if ws.owner_id else None
    if owner and owner.email.lower() in ADMIN_EMAILS:
        raise HTTPException(status_code=403, detail="Cannot disable admin workspace.")

    allowed = {"is_active", "name"}
    for key, val in payload.items():
        if key in allowed and hasattr(ws, key):
            setattr(ws, key, val)

    db.commit()
    db.refresh(ws)
    return {"ok": True, "workspace_id": workspace_id, "updated": list(payload.keys())}


# ── GET /admin/feedback ───────────────────────────────────────────────────────

@router.get("/feedback", summary="All user feedback and bug reports")
def list_feedback(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> dict:
    items = list(db.scalars(
        select(Feedback).order_by(Feedback.created_at.desc()).offset(skip).limit(limit)
    ).all())
    total = db.scalar(select(func.count()).select_from(Feedback)) or 0

    return {
        "total": total,
        "items": [
            {
                "id": f.id,
                "type": f.type.value,
                "title": f.title,
                "message": f.message,
                "status": f.status.value,
                "user_email": f.user_email,
                "user_name": f.user_name,
                "page_context": f.page_context,
                "created_at": f.created_at.isoformat() if f.created_at else None,
            }
            for f in items
        ],
    }
