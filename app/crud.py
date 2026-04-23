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

    Segment 2: if a workspace_id is provided, the priority engine rules
    are applied before saving. Import is done inline to avoid circular imports.
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
    """
    List tasks with optional filters.
    Returns (total_count, tasks_page) tuple for pagination.
    """
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


# ─── Workspace CRUD ──────────────────────────────────────────────────────────

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
    """
    Return all High/Critical tasks in this workspace that are still
    unstarted (to_do or pending). Used by Segment 3 scheduler.
    """
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

def get_tasks_due_today_for_user(
    db: Session,
    owner_id: int,
) -> list[Task]:
    """
    Return all active (to_do / in_progress) tasks assigned to owner_id
    whose deadline falls on today (UTC date). Used by the daily rollup job
    to build each user's personal DM.
    """
    today: date = datetime.now(timezone.utc).date()

    stmt = (
        select(Task)
        .where(
            Task.owner_id == owner_id,
            Task.status.in_([TaskStatus.to_do, TaskStatus.in_progress]),
            # deadline is stored as DATE — cast-free comparison works for both
            # date and datetime columns because SQLAlchemy handles it.
            Task.deadline == today,
        )
        .order_by(Task.priority.desc(), Task.created_at.asc())
    )
    return list(db.scalars(stmt).all())


def get_all_active_users_with_tasks_due_today(db: Session) -> list[User]:
    """
    Return every User who has at least one active task due today.
    Used to fan out the daily rollup DMs without scanning all users.
    """
    today: date = datetime.now(timezone.utc).date()

    # Subquery: distinct owner_ids that have a task due today
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
            User.slack_user_id.isnot(None),  # must have Slack to receive DM
            User.is_active == True,
        )
    )
    return list(db.scalars(stmt).all())


def get_overdue_high_priority_tasks_for_workspace(
    db: Session,
    workspace_id: int,
) -> list[Task]:
    """
    Return all High/Critical tasks in the workspace that are still active
    AND whose deadline is strictly before today (i.e. overdue).
    Used to build the manager's team overdue summary DM.
    """
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
    """
    Return all distinct workspace IDs that have at least one active user.
    Used by the manager rollup loop to iterate workspaces.
    """
    stmt = (
        select(Workspace.id)
        .order_by(Workspace.id.asc())
    )
    return list(db.scalars(stmt).all())


def get_managers_for_workspace(db: Session, workspace_id: int) -> list[User]:
    """
    Return all users in the workspace with role = architect or manager
    who have a Slack user ID set (so we can DM them).
    """
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
