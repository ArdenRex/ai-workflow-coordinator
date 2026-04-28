"""
crud.py
───────
All database read/write operations. Keeps business logic out of route handlers.
"""

import logging
import secrets
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session
from passlib.context import CryptContext

from app.models import Priority, Task, TaskStatus, User, UserRole, Workspace, WorkspaceSettings
from app.schemas import ExtractedTask, TaskStatusUpdate

logger = logging.getLogger(__name__)

# ── Password hashing ──────────────────────────────────────────────────────────
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ─── Task CRUD ────────────────────────────────────────────────────────────────

def create_task(
    db: Session,
    source_message: str,
    extracted: ExtractedTask,
    slack_channel_id: Optional[str] = None,
    slack_message_ts: Optional[str] = None,
    owner_id: Optional[int] = None,
    workspace_id: Optional[int] = None,
) -> Task:
    """
    Create and persist a new task from AI-extracted data.
    Segment 2: priority engine applied if workspace_id is provided.
    Segment 8: share_token generated automatically on creation.
    """
    final_priority = extracted.priority or Priority.medium

    if workspace_id:
        try:
            from app.priority_engine import apply_priority_rules
            settings = get_workspace_settings(db, workspace_id)
            final_priority = apply_priority_rules(
                message=source_message,
                base_priority=extracted.priority or Priority.medium,
                urgency=extracted.urgency or "medium",
                slack_channel_id=slack_channel_id,
                settings=settings,
            )
        except Exception as exc:
            logger.warning("Priority engine error (non-fatal): %s", exc)

    task = Task(
        title=extracted.task,
        task_description=extracted.task,
        assignee=extracted.assignee,
        deadline=extracted.deadline,
        priority=final_priority,
        source_message=source_message,
        status=TaskStatus.to_do,
        slack_channel_id=slack_channel_id,
        slack_message_ts=slack_message_ts,
        owner_id=owner_id,
        workspace_id=workspace_id,
        share_token=secrets.token_urlsafe(12),  # ✅ Segment 8: unique share token
    )
    db.add(task)
    try:
        db.commit()
        db.refresh(task)
    except IntegrityError as exc:
        db.rollback()
        logger.error("IntegrityError creating task: %s", exc, exc_info=True)
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        logger.error("SQLAlchemyError creating task: %s", exc, exc_info=True)
        raise
    return task


def get_task(db: Session, task_id: int) -> Optional[Task]:
    if task_id <= 0:
        return None
    return db.get(Task, task_id)


# ── Segment 8: fetch task by share token ─────────────────────────────────────

def get_task_by_share_token(db: Session, token: str) -> Optional[Task]:
    """Fetch a task by its public share token. Returns None if not found."""
    stmt = select(Task).where(Task.share_token == token.strip())
    return db.scalars(stmt).first()


def list_tasks(
    db: Session,
    status: Optional[TaskStatus] = None,
    assignee: Optional[str] = None,
    priority: Optional[Priority] = None,
    skip: int = 0,
    limit: int = 50,
    owner_id: Optional[int] = None,
    workspace_id: Optional[int] = None,
    team_name: Optional[str] = None,
) -> tuple[int, list[Task]]:
    """List tasks with optional filters. Returns (total_count, tasks_page)."""
    skip = max(0, skip)
    limit = max(1, min(limit, 200))

    stmt = select(Task)

    if status is not None:
        stmt = stmt.where(Task.status == status)
    if assignee:
        stmt = stmt.where(Task.assignee.ilike(f"%{assignee.strip()}%"))
    if priority is not None:
        stmt = stmt.where(Task.priority == priority)
    if owner_id is not None:
        stmt = stmt.where(Task.owner_id == owner_id)
    if workspace_id is not None:
        stmt = stmt.where(Task.workspace_id == workspace_id)
    if team_name:
        stmt = stmt.where(Task.assignee.ilike(f"%{team_name.strip()}%"))

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total: int = db.scalar(count_stmt) or 0

    stmt = stmt.order_by(Task.created_at.desc()).offset(skip).limit(limit)
    tasks: list[Task] = list(db.scalars(stmt).all())

    return total, tasks


def update_task_status(
    db: Session, task_id: int, update: TaskStatusUpdate
) -> Optional[Task]:
    task = db.get(Task, task_id)
    if not task:
        return None
    task.status = update.status
    try:
        db.commit()
        db.refresh(task)
    except SQLAlchemyError as exc:
        db.rollback()
        logger.error("SQLAlchemyError updating task %d: %s", task_id, exc, exc_info=True)
        raise
    return task


def update_task(
    db: Session,
    task_id: int,
    **fields,
) -> Optional[Task]:
    task = db.get(Task, task_id)
    if not task:
        return None

    allowed_fields = {
        "task_description", "assignee", "deadline",
        "priority", "status", "slack_channel_id", "slack_message_ts",
    }
    for key, value in fields.items():
        if key not in allowed_fields:
            logger.warning("update_task: ignoring unknown field %r", key)
            continue
        setattr(task, key, value)

    try:
        db.commit()
        db.refresh(task)
    except SQLAlchemyError as exc:
        db.rollback()
        logger.error("SQLAlchemyError in update_task %d: %s", task_id, exc, exc_info=True)
        raise
    return task


def get_task_by_slack_ts(
    db: Session,
    slack_channel_id: str,
    slack_message_ts: str,
) -> Optional[Task]:
    stmt = select(Task).where(
        Task.slack_channel_id == slack_channel_id,
        Task.slack_message_ts == slack_message_ts,
    )
    return db.scalars(stmt).first()


# ─── User CRUD ────────────────────────────────────────────────────────────────

def get_user_by_email(db: Session, email: str) -> Optional[User]:
    stmt = select(User).where(User.email == email.strip().lower())
    return db.scalars(stmt).first()


def get_user_by_id(db: Session, user_id: int) -> Optional[User]:
    return db.get(User, user_id)


def get_user_by_slack_id(db: Session, slack_user_id: str) -> Optional[User]:
    stmt = select(User).where(User.slack_user_id == slack_user_id)
    return db.scalars(stmt).first()


def create_user(
    db: Session,
    name: str,
    email: str,
    password: Optional[str] = None,
    slack_user_id: Optional[str] = None,
    slack_team_id: Optional[str] = None,
    role: UserRole = UserRole.operator,
    team_name: Optional[str] = None,
    workspace_id: Optional[int] = None,
    trial_ends_at=None,
    subscription_status: str = "trialing",
) -> User:
    user = User(
        name=name.strip(),
        email=email.strip().lower(),
        password_hash=hash_password(password) if password else None,
        slack_user_id=slack_user_id,
        slack_team_id=slack_team_id,
        role=role,
        team_name=team_name,
        workspace_id=workspace_id,
        is_active=True,
        is_verified=False,
        trial_ends_at=trial_ends_at,
        subscription_status=subscription_status,
    )
    db.add(user)
    try:
        db.commit()
        db.refresh(user)
    except IntegrityError as exc:
        db.rollback()
        logger.error("IntegrityError creating user: %s", exc, exc_info=True)
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        logger.error("SQLAlchemyError creating user: %s", exc, exc_info=True)
        raise
    return user


def authenticate_user(db: Session, email: str, password: str) -> Optional[User]:
    user = get_user_by_email(db, email)
    if not user:
        return None
    if not user.password_hash:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def update_user_onboarding(
    db: Session,
    user_id: int,
    role: UserRole,
    team_name: Optional[str],
    workspace_id: int,
) -> Optional[User]:
    user = db.get(User, user_id)
    if not user:
        return None
    user.role = role
    user.team_name = team_name
    user.workspace_id = workspace_id
    try:
        db.commit()
        db.refresh(user)
    except SQLAlchemyError as exc:
        db.rollback()
        logger.error("SQLAlchemyError updating user onboarding %d: %s", user_id, exc, exc_info=True)
        raise
    return user


# ─── Workspace CRUD ───────────────────────────────────────────────────────────

def create_workspace(db: Session, name: str, owner_id: int) -> Workspace:
    workspace = Workspace(
        name=name.strip(),
        invite_code=secrets.token_urlsafe(8),
        owner_id=owner_id,
    )
    db.add(workspace)
    try:
        db.commit()
        db.refresh(workspace)
    except SQLAlchemyError as exc:
        db.rollback()
        logger.error("SQLAlchemyError creating workspace: %s", exc, exc_info=True)
        raise
    return workspace


def get_workspace_by_invite_code(db: Session, invite_code: str) -> Optional[Workspace]:
    stmt = select(Workspace).where(Workspace.invite_code == invite_code.strip())
    return db.scalars(stmt).first()


def get_workspace_by_id(db: Session, workspace_id: int) -> Optional[Workspace]:
    return db.get(Workspace, workspace_id)


# ─── Workspace Settings CRUD (Segment 2) ─────────────────────────────────────

def get_workspace_settings(
    db: Session,
    workspace_id: int,
) -> Optional[WorkspaceSettings]:
    stmt = select(WorkspaceSettings).where(
        WorkspaceSettings.workspace_id == workspace_id
    )
    return db.scalars(stmt).first()


def get_or_create_workspace_settings(
    db: Session,
    workspace_id: int,
) -> WorkspaceSettings:
    settings = get_workspace_settings(db, workspace_id)
    if not settings:
        settings = WorkspaceSettings(
            workspace_id=workspace_id,
            keyword_rules=[],
            high_priority_channels=[],
            drift_alert_hours=24,
        )
        db.add(settings)
        try:
            db.commit()
            db.refresh(settings)
        except SQLAlchemyError as exc:
            db.rollback()
            logger.error(
                "SQLAlchemyError creating workspace settings for workspace %d: %s",
                workspace_id, exc, exc_info=True,
            )
            raise
    return settings


def update_workspace_settings(
    db: Session,
    workspace_id: int,
    keyword_rules: Optional[list] = None,
    high_priority_channels: Optional[list] = None,
    drift_alert_hours: Optional[int] = None,
) -> WorkspaceSettings:
    settings = get_or_create_workspace_settings(db, workspace_id)

    if keyword_rules is not None:
        settings.keyword_rules = keyword_rules
    if high_priority_channels is not None:
        settings.high_priority_channels = high_priority_channels
    if drift_alert_hours is not None:
        settings.drift_alert_hours = max(1, min(168, drift_alert_hours))

    try:
        db.commit()
        db.refresh(settings)
    except SQLAlchemyError as exc:
        db.rollback()
        logger.error(
            "SQLAlchemyError updating workspace settings for workspace %d: %s",
            workspace_id, exc, exc_info=True,
        )
        raise
    return settings


def get_drifting_tasks(
    db: Session,
    workspace_id: int,
) -> list[Task]:
    stmt = (
        select(Task)
        .where(
            Task.workspace_id == workspace_id,
            Task.priority.in_([Priority.high, Priority.critical]),
            Task.status.in_([TaskStatus.to_do, TaskStatus.pending]),
        )
        .order_by(Task.created_at.asc())
    )
    return list(db.scalars(stmt).all())


# ─── Segment 4: Daily Rollup Queries ─────────────────────────────────────────

def get_tasks_due_today_for_user(db: Session, owner_id: int) -> list[Task]:
    today: date = datetime.now(timezone.utc).date()
    stmt = (
        select(Task)
        .where(
            Task.owner_id == owner_id,
            Task.status.in_([TaskStatus.to_do, TaskStatus.in_progress]),
            Task.deadline == today,
        )
        .order_by(Task.priority.desc(), Task.created_at.asc())
    )
    return list(db.scalars(stmt).all())


def get_all_active_users_with_tasks_due_today(db: Session) -> list[User]:
    today: date = datetime.now(timezone.utc).date()
    subq = (
        select(Task.owner_id)
        .where(
            Task.owner_id.isnot(None),
            Task.status.in_([TaskStatus.to_do, TaskStatus.in_progress]),
            Task.deadline == today,
        )
        .distinct()
        .subquery()
    )
    stmt = (
        select(User)
        .where(
            User.id.in_(select(subq)),
            User.slack_user_id.isnot(None),
            User.is_active == True,
        )
    )
    return list(db.scalars(stmt).all())


def get_overdue_high_priority_tasks_for_workspace(
    db: Session,
    workspace_id: int,
) -> list[Task]:
    today: date = datetime.now(timezone.utc).date()
    stmt = (
        select(Task)
        .where(
            Task.workspace_id == workspace_id,
            Task.priority.in_([Priority.high, Priority.critical]),
            Task.status.in_([TaskStatus.to_do, TaskStatus.in_progress]),
            Task.deadline < today,
            Task.deadline.isnot(None),
        )
        .order_by(Task.deadline.asc(), Task.priority.desc())
    )
    return list(db.scalars(stmt).all())


def get_all_workspace_ids(db: Session) -> list[int]:
    stmt = select(Workspace.id).order_by(Workspace.id.asc())
    return list(db.scalars(stmt).all())


def get_managers_for_workspace(db: Session, workspace_id: int) -> list[User]:
    stmt = (
        select(User)
        .where(
            User.workspace_id == workspace_id,
            User.role.in_([UserRole.architect, UserRole.manager]),
            User.slack_user_id.isnot(None),
            User.is_active == True,
        )
    )
    return list(db.scalars(stmt).all())


# ─── Segment 10: Ownership Graph Queries ─────────────────────────────────────

def get_ownership_graph(
    db: Session,
    workspace_id: Optional[int] = None,
    owner_id: Optional[int] = None,
) -> dict:
    """
    Returns task ownership data grouped by assignee/owner for the graph view.
    Each node = a person. Each entry = their task counts by status + priority.
    """
    stmt = select(Task)
    if workspace_id is not None:
        stmt = stmt.where(Task.workspace_id == workspace_id)
    if owner_id is not None:
        stmt = stmt.where(Task.owner_id == owner_id)

    tasks = list(db.scalars(stmt).all())

    # Group by assignee
    by_assignee: dict[str, dict] = {}
    for task in tasks:
        name = (task.assignee or "Unassigned").strip()
        if name not in by_assignee:
            by_assignee[name] = {
                "assignee": name,
                "total": 0,
                "to_do": 0,
                "in_progress": 0,
                "completed": 0,
                "cancelled": 0,
                "critical": 0,
                "high": 0,
                "medium": 0,
                "low": 0,
                "tasks": [],
            }
        node = by_assignee[name]
        node["total"] += 1

        status_val = task.status.value if hasattr(task.status, "value") else str(task.status)
        if status_val in node:
            node[status_val] += 1

        priority_val = task.priority.value if hasattr(task.priority, "value") else str(task.priority)
        if priority_val in node:
            node[priority_val] += 1

        node["tasks"].append({
            "id":       task.id,
            "title":    task.title or task.task_description,
            "status":   status_val,
            "priority": priority_val,
            "deadline": task.deadline.isoformat() if task.deadline else None,
            "created_at": task.created_at.isoformat() if task.created_at else None,
        })

    nodes = sorted(by_assignee.values(), key=lambda x: x["total"], reverse=True)

    return {
        "total_tasks": len(tasks),
        "total_owners": len(nodes),
        "nodes": nodes,
    }


# ─── Segment 11: Integration Config CRUD ─────────────────────────────────────

def get_integration_config(db: Session, workspace_id: int) -> dict:
    """
    Return the stored integration credentials dict for a workspace.
    Returns an empty dict if the workspace or settings don't exist.
    """
    settings = get_workspace_settings(db, workspace_id)
    if not settings:
        return {}
    return dict(settings.integration_config or {})


def save_integration_config(
    db: Session,
    workspace_id: int,
    incoming: dict,
) -> dict:
    """
    Merge `incoming` key/value pairs into the existing integration_config
    and persist.  Only supplied keys are overwritten — others are preserved.
    Returns the full updated config dict.
    """
    settings = get_or_create_workspace_settings(db, workspace_id)
    existing = dict(settings.integration_config or {})
    existing.update({k: v for k, v in incoming.items() if v is not None})
    settings.integration_config = existing
    try:
        db.commit()
        db.refresh(settings)
    except SQLAlchemyError as exc:
        db.rollback()
        logger.error(
            "SQLAlchemyError saving integration config for workspace %d: %s",
            workspace_id, exc, exc_info=True,
        )
        raise
    return dict(settings.integration_config or {})


# ─── Segment 12: Locale / i18n CRUD ──────────────────────────────────────────

def get_user_locale(db: Session, user_id: int) -> dict:
    """Return locale prefs for a user. Falls back to defaults if not set."""
    user = get_user_by_id(db, user_id)
    if not user:
        return {"language": "en", "timezone": "UTC", "currency": "USD"}
    return {
        "language": user.language or "en",
        "timezone": user.timezone or "UTC",
        "currency": user.currency or "USD",
    }


def save_user_locale(
    db: Session,
    user_id: int,
    language: Optional[str] = None,
    timezone: Optional[str] = None,
    currency: Optional[str] = None,
) -> dict:
    """Persist locale prefs for a user. Only updates supplied fields."""
    user = get_user_by_id(db, user_id)
    if not user:
        raise ValueError(f"User {user_id} not found.")
    if language is not None:
        user.language = language
    if timezone is not None:
        user.timezone = timezone
    if currency is not None:
        user.currency = currency
    try:
        db.commit()
        db.refresh(user)
    except SQLAlchemyError as exc:
        db.rollback()
        logger.error("SQLAlchemyError saving locale for user %d: %s", user_id, exc, exc_info=True)
        raise
    return {"language": user.language or "en", "timezone": user.timezone or "UTC", "currency": user.currency or "USD"}


def get_workspace_locale(db: Session, workspace_id: int) -> dict:
    """Return workspace-level locale defaults."""
    settings = get_workspace_settings(db, workspace_id)
    if not settings:
        return {"default_language": "en", "default_timezone": "UTC", "default_currency": "USD"}
    return {
        "default_language": settings.default_language or "en",
        "default_timezone": settings.default_timezone or "UTC",
        "default_currency": settings.default_currency or "USD",
    }


def save_workspace_locale(
    db: Session,
    workspace_id: int,
    default_language: Optional[str] = None,
    default_timezone: Optional[str] = None,
    default_currency: Optional[str] = None,
) -> dict:
    """Persist workspace locale defaults. Only updates supplied fields."""
    settings = get_or_create_workspace_settings(db, workspace_id)
    if default_language is not None:
        settings.default_language = default_language
    if default_timezone is not None:
        settings.default_timezone = default_timezone
    if default_currency is not None:
        settings.default_currency = default_currency
    try:
        db.commit()
        db.refresh(settings)
    except SQLAlchemyError as exc:
        db.rollback()
        logger.error("SQLAlchemyError saving workspace locale %d: %s", workspace_id, exc, exc_info=True)
        raise
    return {
        "default_language": settings.default_language or "en",
        "default_timezone": settings.default_timezone or "UTC",
        "default_currency": settings.default_currency or "USD",
    }


# ─── Segment 6: Viral Onboarding — Social Proof Stats ────────────────────────

def get_workspace_stats(db: Session, workspace_id: int) -> dict:
    """
    Returns social proof metrics for a workspace:
    - tasks created this month
    - active members (users with at least 1 task)
    - top assignee by task count
    """
    from sqlalchemy import extract
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)

    # Tasks created this month
    monthly_stmt = select(func.count()).where(
        Task.workspace_id == workspace_id,
        extract("year",  Task.created_at) == now.year,
        extract("month", Task.created_at) == now.month,
    )
    monthly_count: int = db.scalar(monthly_stmt) or 0

    # Total tasks in workspace
    total_stmt = select(func.count()).where(Task.workspace_id == workspace_id)
    total_count: int = db.scalar(total_stmt) or 0

    # Active members = distinct assignees with tasks
    from sqlalchemy import distinct
    active_stmt = select(func.count(distinct(Task.assignee))).where(
        Task.workspace_id == workspace_id,
        Task.assignee.isnot(None),
    )
    active_members: int = db.scalar(active_stmt) or 0

    # Top assignee this month
    from sqlalchemy import desc
    top_stmt = (
        select(Task.assignee, func.count().label("cnt"))
        .where(
            Task.workspace_id == workspace_id,
            Task.assignee.isnot(None),
            extract("year",  Task.created_at) == now.year,
            extract("month", Task.created_at) == now.month,
        )
        .group_by(Task.assignee)
        .order_by(desc("cnt"))
        .limit(1)
    )
    top_row = db.execute(top_stmt).first()
    top_assignee = top_row[0] if top_row else None
    top_assignee_count = top_row[1] if top_row else 0

    # Completion rate
    done_stmt = select(func.count()).where(
        Task.workspace_id == workspace_id,
        Task.status == TaskStatus.completed,
    )
    done_count: int = db.scalar(done_stmt) or 0
    completion_rate = round((done_count / total_count * 100) if total_count else 0, 1)

    return {
        "tasks_this_month":    monthly_count,
        "total_tasks":         total_count,
        "active_members":      active_members,
        "top_assignee":        top_assignee,
        "top_assignee_count":  top_assignee_count,
        "completion_rate":     completion_rate,
        "done_tasks":          done_count,
    }


def get_pending_invite(db: Session, workspace_id: int, assignee_name: str) -> Optional["PendingInvite"]:
    """Check if an invite already exists for this assignee in this workspace."""
    from app.models import PendingInvite
    stmt = select(PendingInvite).where(
        PendingInvite.workspace_id == workspace_id,
        PendingInvite.assignee_name == assignee_name,
    )
    return db.scalars(stmt).first()


def create_pending_invite(
    db: Session,
    workspace_id: int,
    assignee_name: str,
    assignee_slack_id: Optional[str],
    task_id: int,
) -> "PendingInvite":
    """Record a viral invite sent to an unregistered assignee."""
    from app.models import PendingInvite
    import secrets
    invite = PendingInvite(
        workspace_id      = workspace_id,
        assignee_name     = assignee_name,
        assignee_slack_id = assignee_slack_id,
        task_id           = task_id,
        invite_token      = secrets.token_urlsafe(16),
    )
    db.add(invite)
    try:
        db.commit()
        db.refresh(invite)
    except Exception as exc:
        db.rollback()
        logger.error("Error creating pending invite: %s", exc)
        raise
    return invite


# ─── Segment 9: Microsoft Teams CRUD ─────────────────────────────────────────

def get_teams_config(db: Session, workspace_id: int) -> dict:
    """Return Teams config keys from workspace integration_config."""
    settings = get_workspace_settings(db, workspace_id)
    if not settings:
        return {}
    cfg = dict(settings.integration_config or {})
    return {
        "teams_tenant_id": cfg.get("teams_tenant_id"),
    }


def save_teams_config(
    db: Session,
    workspace_id: int,
    tenant_id: Optional[str] = None,
    clear: bool = False,
) -> dict:
    """
    Persist Teams tenant ID into workspace integration_config.
    Pass clear=True to disconnect Teams (removes tenant_id key).
    """
    from sqlalchemy.exc import SQLAlchemyError
    settings = get_or_create_workspace_settings(db, workspace_id)
    cfg = dict(settings.integration_config or {})

    if clear:
        cfg.pop("teams_tenant_id", None)
        # Also persist to dedicated column if present
        if hasattr(settings, "teams_tenant_id"):
            settings.teams_tenant_id = None
    else:
        if tenant_id is not None:
            cfg["teams_tenant_id"] = tenant_id.strip()
            if hasattr(settings, "teams_tenant_id"):
                settings.teams_tenant_id = tenant_id.strip()

    settings.integration_config = cfg
    try:
        db.commit()
        db.refresh(settings)
    except SQLAlchemyError as exc:
        db.rollback()
        logger.error("SQLAlchemyError saving Teams config for workspace %d: %s", workspace_id, exc)
        raise
    return dict(settings.integration_config or {})


def get_workspace_settings_by_teams_tenant(
    db: Session,
    tenant_id: str,
) -> Optional["WorkspaceSettings"]:
    """Find workspace settings by Teams tenant ID."""
    if not tenant_id:
        return None
    stmt = select(WorkspaceSettings).where(
        WorkspaceSettings.teams_tenant_id == tenant_id.strip()
    )
    return db.scalars(stmt).first()


def list_teams_channels(db: Session, workspace_id: int) -> list:
    """Return all registered Teams channels for a workspace."""
    from app.models import TeamsChannel
    stmt = (
        select(TeamsChannel)
        .where(
            TeamsChannel.workspace_id == workspace_id,
            TeamsChannel.is_active == True,
        )
        .order_by(TeamsChannel.created_at.asc())
    )
    return list(db.scalars(stmt).all())


def create_teams_channel(
    db: Session,
    workspace_id: int,
    channel_id: str,
    channel_name: str,
    service_url: str,
    conversation_id: str,
) -> "TeamsChannel":
    """Register a Teams channel for proactive task notifications."""
    from app.models import TeamsChannel
    from sqlalchemy.exc import SQLAlchemyError, IntegrityError

    channel = TeamsChannel(
        workspace_id    = workspace_id,
        channel_id      = channel_id.strip(),
        channel_name    = channel_name.strip(),
        service_url     = service_url.strip(),
        conversation_id = conversation_id.strip(),
        is_active       = True,
    )
    db.add(channel)
    try:
        db.commit()
        db.refresh(channel)
    except IntegrityError as exc:
        db.rollback()
        logger.error("IntegrityError creating Teams channel: %s", exc)
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        logger.error("SQLAlchemyError creating Teams channel: %s", exc)
        raise
    return channel


def delete_teams_channel(
    db: Session,
    channel_db_id: int,
    workspace_id: int,
) -> bool:
    """Soft-delete (deactivate) a registered Teams channel. Returns True if found."""
    from app.models import TeamsChannel
    from sqlalchemy.exc import SQLAlchemyError

    channel = db.get(TeamsChannel, channel_db_id)
    if not channel or channel.workspace_id != workspace_id:
        return False
    channel.is_active = False
    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        logger.error("SQLAlchemyError deleting Teams channel %d: %s", channel_db_id, exc)
        raise
    return True


# ─── Segment 13: Public API — API Key CRUD ────────────────────────────────────

import hashlib

def _hash_key(raw_key: str) -> str:
    """SHA-256 hash of the raw key for safe storage."""
    return hashlib.sha256(raw_key.encode()).hexdigest()


def create_api_key(
    db: Session,
    workspace_id: int,
    name: str,
    created_by: Optional[int] = None,
) -> tuple[str, "ApiKey"]:
    """
    Generate a new API key.
    Returns (raw_key, ApiKey ORM object).
    The raw_key is only available at creation time — store it securely.
    """
    from app.models import ApiKey
    from sqlalchemy.exc import SQLAlchemyError

    raw_key    = f"sk_live_{secrets.token_urlsafe(32)}"
    key_hash   = _hash_key(raw_key)
    key_prefix = raw_key[:12]   # "sk_live_XXXX"

    api_key = ApiKey(
        workspace_id = workspace_id,
        name         = name.strip(),
        key_hash     = key_hash,
        key_prefix   = key_prefix,
        created_by   = created_by,
        is_active    = True,
    )
    db.add(api_key)
    try:
        db.commit()
        db.refresh(api_key)
    except SQLAlchemyError as exc:
        db.rollback()
        logger.error("SQLAlchemyError creating API key: %s", exc, exc_info=True)
        raise
    return raw_key, api_key


def get_api_key_by_value(db: Session, raw_key: str) -> Optional["ApiKey"]:
    """Look up an ApiKey by its raw value (hashes it first)."""
    from app.models import ApiKey
    key_hash = _hash_key(raw_key)
    stmt = select(ApiKey).where(ApiKey.key_hash == key_hash)
    return db.scalars(stmt).first()


def touch_api_key(db: Session, key_id: int) -> None:
    """Update last_used_at timestamp for an API key."""
    from app.models import ApiKey
    from datetime import datetime, timezone
    key = db.get(ApiKey, key_id)
    if key:
        key.last_used_at = datetime.now(timezone.utc)
        try:
            db.commit()
        except Exception:
            db.rollback()


def list_api_keys(db: Session, workspace_id: int) -> list["ApiKey"]:
    """List all active API keys for a workspace."""
    from app.models import ApiKey
    stmt = (
        select(ApiKey)
        .where(ApiKey.workspace_id == workspace_id, ApiKey.is_active == True)
        .order_by(ApiKey.created_at.desc())
    )
    return list(db.scalars(stmt).all())


def revoke_api_key(db: Session, key_id: int, workspace_id: int) -> bool:
    """Revoke (deactivate) an API key. Returns True if found."""
    from app.models import ApiKey
    key = db.get(ApiKey, key_id)
    if not key or key.workspace_id != workspace_id:
        return False
    key.is_active = False
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error("SQLAlchemyError revoking API key %d: %s", key_id, exc)
        raise
    return True
