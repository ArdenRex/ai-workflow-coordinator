"""
crud.py
───────
All database read/write operations. Keeps business logic out of route handlers.
"""

import logging
import secrets
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session
from passlib.context import CryptContext

from app.models import Priority, Task, TaskStatus, User, UserRole, Workspace
from app.schemas import ExtractedTask, TaskStatusUpdate

logger = logging.getLogger(__name__)

# ── Password hashing ──────────────────────────────────────────────────────────
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ─── Existing Task CRUD (completely unchanged) ────────────────────────────────

def create_task(
    db: Session,
    source_message: str,
    extracted: ExtractedTask,
    slack_channel_id: Optional[str] = None,
    slack_message_ts: Optional[str] = None,
    owner_id: Optional[int] = None,
    workspace_id: Optional[int] = None,
) -> Task:
    """Create and persist a new task from AI-extracted data."""
    task = Task(
        title=extracted.task,
        task_description=extracted.task,
        assignee=extracted.assignee,
        deadline=extracted.deadline,
        priority=extracted.priority or Priority.medium,
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
    """Fetch a single task by ID. Returns None if not found."""
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
    # NEW optional filters for role-based dashboard
    owner_id: Optional[int] = None,
    workspace_id: Optional[int] = None,
    team_name: Optional[str] = None,
) -> tuple[int, list[Task]]:
    """
    List tasks with optional filters.
    Role-based filtering is applied via owner_id / workspace_id / team_name.

    Returns:
        (total_count, tasks_page) tuple for pagination.
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
        # Navigator sees tasks where assignee matches their team name
        stmt = stmt.where(Task.assignee.ilike(f"%{team_name.strip()}%"))

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total: int = db.scalar(count_stmt) or 0

    stmt = stmt.order_by(Task.created_at.desc()).offset(skip).limit(limit)
    tasks: list[Task] = list(db.scalars(stmt).all())

    return total, tasks


def update_task_status(
    db: Session, task_id: int, update: TaskStatusUpdate
) -> Optional[Task]:
    """Update the status of a task. Returns None if task not found."""
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
    """
    Partial update for arbitrary task fields.
    Only updates fields explicitly passed in kwargs.
    Returns None if task not found.
    """
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
    """
    Look up a task by its originating Slack message.
    Used to deduplicate Slack event retries.
    """
    stmt = select(Task).where(
        Task.slack_channel_id == slack_channel_id,
        Task.slack_message_ts == slack_message_ts,
    )
    return db.scalars(stmt).first()


# ─── NEW: User CRUD ───────────────────────────────────────────────────────────

def get_user_by_email(db: Session, email: str) -> Optional[User]:
    """Fetch a user by email. Returns None if not found."""
    stmt = select(User).where(User.email == email.strip().lower())
    return db.scalars(stmt).first()


def get_user_by_id(db: Session, user_id: int) -> Optional[User]:
    """Fetch a user by ID. Returns None if not found."""
    return db.get(User, user_id)


def get_user_by_slack_id(db: Session, slack_user_id: str) -> Optional[User]:
    """Fetch a user by their Slack user ID. Returns None if not found."""
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
    """Create and persist a new user."""
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


def authenticate_user(
    db: Session, email: str, password: str
) -> Optional[User]:
    """
    Verify email + password.
    Returns the User if credentials are valid, None otherwise.
    """
    user = get_user_by_email(db, email)
    if not user:
        return None
    if not user.password_hash:
        # Slack-only user — cannot log in with password
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
    """Update a user's role, team, and workspace after onboarding."""
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


# ─── NEW: Workspace CRUD ──────────────────────────────────────────────────────

def create_workspace(
    db: Session,
    name: str,
    owner_id: int,
) -> Workspace:
    """Create a new workspace with a unique invite code."""
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


def get_workspace_by_invite_code(
    db: Session, invite_code: str
) -> Optional[Workspace]:
    """Fetch a workspace by its invite code. Returns None if not found."""
    stmt = select(Workspace).where(Workspace.invite_code == invite_code.strip())
    return db.scalars(stmt).first()


def get_workspace_by_id(
    db: Session, workspace_id: int
) -> Optional[Workspace]:
    """Fetch a workspace by ID. Returns None if not found."""
    return db.get(Workspace, workspace_id)
