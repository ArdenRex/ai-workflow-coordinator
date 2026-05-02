"""
routers/tasks.py
────────────────
All task endpoints. Every endpoint (except public share) requires authentication.
Task visibility is scoped by role:

  architect  → all tasks in the workspace
  navigator  → team tasks (same team_name) + own tasks
  operator   → only own tasks (assigned to them)
  solo       → only own tasks

Dashboard split:
  GET /tasks/my       → Individual section: tasks where owner_id = current user
                        OR assignee matches current user's name
  GET /tasks/team     → Team section: tasks in current user's workspace,
                        filtered by role (architect sees all, navigator sees team,
                        operator/solo see own)
  GET /tasks          → Kept for backwards compatibility — same as /tasks/team

GET    /tasks/my               → Individual tasks for current user
GET    /tasks/team             → Team tasks filtered by role
GET    /tasks                  → List tasks (role-scoped, auth required)
GET    /tasks/{id}             → Get a single task (auth required)
PATCH  /tasks/{id}/status      → Update task status (auth required)
DELETE /tasks/{id}             → Delete a task (auth required)
GET    /tasks/{id}/share-link  → Get the public share URL for a task
GET    /share/{token}          → Public view of a task (no auth)
POST   /tasks/ping-overdue     → Manually trigger overdue ping job
POST   /tasks/daily-rollup     → Manually trigger daily rollup job
"""

import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import crud
from app.auth import get_current_user
from app.database import get_db
from app.models import Priority, Task, TaskStatus, User, UserRole
from app.schemas import TaskListResponse, TaskResponse, TaskStatusUpdate

logger = logging.getLogger(__name__)

FRONTEND_URL = os.getenv("FRONTEND_URL", "").rstrip("/")

router = APIRouter(
    prefix="/tasks",
    tags=["Tasks"],
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_role_scoped_tasks(
    db: Session,
    current_user: User,
    status: Optional[TaskStatus] = None,
    assignee: Optional[str] = None,
    priority: Optional[Priority] = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[int, list[Task]]:
    """
    Return tasks visible to the current user based on their role.

    architect  → all tasks in the workspace
    navigator  → tasks in the workspace where assignee matches their team_name
    operator   → only tasks assigned to them (by owner_id or assignee name)
    solo       → only tasks assigned to them (by owner_id or assignee name)
    """
    role = current_user.role
    workspace_id = current_user.workspace_id

    if not workspace_id:
        if role == UserRole.architect:
            # Architect with no workspace — show ALL tasks (including Slack-created
            # tasks that have no workspace_id or owner_id)
            from sqlalchemy import select, func
            from app.models import Task as TaskModel
            stmt = select(TaskModel)
            if status is not None:
                stmt = stmt.where(TaskModel.status == status)
            if assignee is not None:
                stmt = stmt.where(TaskModel.assignee.ilike(f"%{assignee}%"))
            if priority is not None:
                stmt = stmt.where(TaskModel.priority == priority)
            count_stmt = select(func.count()).select_from(stmt.subquery())
            total = db.scalar(count_stmt) or 0
            stmt = stmt.order_by(TaskModel.created_at.desc()).offset(skip).limit(limit)
            tasks = list(db.scalars(stmt).all())
            return total, tasks
        else:
            # Non-architect with no workspace — return only their own tasks
            return crud.list_tasks(
                db,
                status=status,
                assignee=assignee,
                priority=priority,
                skip=skip,
                limit=limit,
                owner_id=current_user.id,
            )

    if role == UserRole.architect:
        # Sees all workspace tasks
        return crud.list_tasks(
            db,
            status=status,
            assignee=assignee,
            priority=priority,
            skip=skip,
            limit=limit,
            workspace_id=workspace_id,
        )

    elif role == UserRole.navigator:
        # Sees tasks for their team (filtered by team_name) within workspace
        team = current_user.team_name
        return crud.list_tasks(
            db,
            status=status,
            assignee=assignee or team,  # if no specific assignee filter, default to team
            priority=priority,
            skip=skip,
            limit=limit,
            workspace_id=workspace_id,
            team_name=team if not assignee else None,
        )

    else:
        # operator / solo — only own tasks
        return crud.list_tasks(
            db,
            status=status,
            assignee=assignee,
            priority=priority,
            skip=skip,
            limit=limit,
            owner_id=current_user.id,
            workspace_id=workspace_id,
        )


# ── Individual tasks endpoint ─────────────────────────────────────────────────

@router.get(
    "/my",
    response_model=TaskListResponse,
    summary="Individual section — tasks assigned to the current user",
)
def list_my_tasks(
    status: Optional[TaskStatus] = Query(default=None),
    priority: Optional[Priority] = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TaskListResponse:
    """
    Returns only tasks that belong to the currently logged-in user.
    These are tasks where owner_id = current user's ID OR
    where the task assignee name matches the current user's name.
    This populates the INDIVIDUAL section of the dashboard.
    """
    try:
        total, tasks = crud.list_tasks(
            db,
            status=status,
            priority=priority,
            skip=skip,
            limit=limit,
            owner_id=current_user.id,
            workspace_id=current_user.workspace_id,
        )
        # Also pick up tasks assigned by name (e.g. created via Slack)
        # where owner_id is NULL but assignee matches the user's name
        from sqlalchemy import select, func, or_
        from app.models import Task as TaskModel

        stmt = select(TaskModel).where(
            or_(
                TaskModel.owner_id == current_user.id,
                TaskModel.assignee.ilike(f"%{current_user.name.strip()}%"),
            )
        )
        if current_user.workspace_id:
            stmt = stmt.where(TaskModel.workspace_id == current_user.workspace_id)
        if status is not None:
            stmt = stmt.where(TaskModel.status == status)
        if priority is not None:
            stmt = stmt.where(TaskModel.priority == priority)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = db.scalar(count_stmt) or 0
        stmt = stmt.order_by(TaskModel.created_at.desc()).offset(skip).limit(limit)
        tasks = list(db.scalars(stmt).all())

    except SQLAlchemyError as exc:
        logger.exception("DB error listing my tasks: %s", exc)
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database error. Please retry.",
        ) from exc

    return TaskListResponse(total=total, skip=skip, limit=limit, tasks=tasks)


# ── Team tasks endpoint ───────────────────────────────────────────────────────

@router.get(
    "/team",
    response_model=TaskListResponse,
    summary="Team section — tasks visible based on user role",
)
def list_team_tasks(
    status: Optional[TaskStatus] = Query(default=None),
    assignee: Optional[str] = Query(default=None),
    priority: Optional[Priority] = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TaskListResponse:
    """
    Returns tasks filtered by the user's role within their workspace.
    - architect → all workspace tasks
    - navigator → tasks for their team
    - operator/solo → their own tasks only
    This populates the TEAM section of the dashboard.
    """
    try:
        total, tasks = _build_role_scoped_tasks(
            db,
            current_user,
            status=status,
            assignee=assignee,
            priority=priority,
            skip=skip,
            limit=limit,
        )
    except SQLAlchemyError as exc:
        logger.exception("DB error listing team tasks: %s", exc)
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database error. Please retry.",
        ) from exc

    return TaskListResponse(total=total, skip=skip, limit=limit, tasks=tasks)


# ── Main list endpoint (backwards compat, now auth-required + role-scoped) ────

@router.get(
    "",
    response_model=TaskListResponse,
    summary="List tasks (role-scoped, auth required)",
)
def list_tasks(
    status: Optional[TaskStatus] = Query(default=None),
    assignee: Optional[str] = Query(default=None),
    priority: Optional[Priority] = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TaskListResponse:
    """
    Same as /tasks/team — role-scoped, requires authentication.
    Kept for backwards compatibility with existing frontend calls.
    """
    try:
        total, tasks = _build_role_scoped_tasks(
            db,
            current_user,
            status=status,
            assignee=assignee,
            priority=priority,
            skip=skip,
            limit=limit,
        )
    except SQLAlchemyError as exc:
        logger.exception("DB error listing tasks: %s", exc)
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database error. Please retry.",
        ) from exc

    return TaskListResponse(total=total, skip=skip, limit=limit, tasks=tasks)


# ── Segment 10: Ownership graph endpoint ─────────────────────────────────────
# ⚠️  MUST be defined BEFORE /{task_id} — FastAPI matches routes top-to-bottom,
#    so /graph would otherwise be captured by /{task_id} and fail to parse.

@router.get(
    "/graph",
    summary="Get ownership graph data",
    description="Returns task counts grouped by assignee. Scoped to the user's workspace.",
)
def get_ownership_graph(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    try:
        data = crud.get_ownership_graph(
            db,
            workspace_id=current_user.workspace_id,
            owner_id=current_user.id if current_user.role in (UserRole.operator, UserRole.solo) else None,
        )
    except Exception as exc:
        logger.exception("Error fetching ownership graph: %s", exc)
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database error. Please retry.",
        ) from exc
    return data


# ── Single task endpoints ─────────────────────────────────────────────────────

@router.get(
    "/{task_id}",
    response_model=TaskResponse,
    summary="Get a task by ID (auth required)",
)
def get_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TaskResponse:
    if task_id <= 0:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="task_id must be a positive integer.",
        )
    try:
        task = crud.get_task(db, task_id)
    except SQLAlchemyError as exc:
        logger.exception("DB error fetching task %d: %s", task_id, exc)
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database error. Please retry.",
        ) from exc
    if not task:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=f"Task #{task_id} not found.",
        )

    # Enforce visibility: operator/solo can only see their own tasks
    if current_user.role in (UserRole.operator, UserRole.solo):
        if task.owner_id != current_user.id and (
            not task.assignee or current_user.name.lower() not in task.assignee.lower()
        ):
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to view this task.",
            )

    return task


@router.patch(
    "/{task_id}/status",
    response_model=TaskResponse,
    summary="Update a task's status (auth required)",
)
def update_task_status(
    task_id: int,
    update: TaskStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TaskResponse:
    if task_id <= 0:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="task_id must be a positive integer.",
        )
    try:
        task = crud.get_task(db, task_id)
    except SQLAlchemyError as exc:
        logger.exception("DB error fetching task %d for status update: %s", task_id, exc)
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database error. Please retry.",
        ) from exc
    if not task:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=f"Task #{task_id} not found.",
        )

    # Enforce: operator/solo can only update their own tasks
    if current_user.role in (UserRole.operator, UserRole.solo):
        if task.owner_id != current_user.id and (
            not task.assignee or current_user.name.lower() not in task.assignee.lower()
        ):
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail="You can only update tasks assigned to you.",
            )

    try:
        task = crud.update_task_status(db, task_id, update)
    except SQLAlchemyError as exc:
        logger.exception("DB error updating task %d status: %s", task_id, exc)
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database error. Please retry.",
        ) from exc

    return task


@router.delete(
    "/{task_id}",
    status_code=http_status.HTTP_204_NO_CONTENT,
    summary="Delete a task (auth required)",
)
def delete_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    if task_id <= 0:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="task_id must be a positive integer.",
        )
    try:
        task = crud.get_task(db, task_id)
    except SQLAlchemyError as exc:
        logger.exception("DB error fetching task %d for delete: %s", task_id, exc)
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database error. Please retry.",
        ) from exc
    if not task:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=f"Task #{task_id} not found.",
        )

    # Enforce: only architect or task owner can delete
    if current_user.role != UserRole.architect and task.owner_id != current_user.id:
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to delete this task.",
        )

    try:
        db.delete(task)
        db.commit()
        logger.info("Deleted task id=%d by user id=%d", task_id, current_user.id)
    except SQLAlchemyError as exc:
        db.rollback()
        logger.exception("DB error deleting task %d: %s", task_id, exc)
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database error. Please retry.",
        ) from exc


# ── Segment 8: Share link endpoints ──────────────────────────────────────────

@router.get(
    "/{task_id}/share-link",
    summary="Get the public share URL for a task",
)
def get_share_link(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    if task_id <= 0:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="task_id must be a positive integer.",
        )
    task = crud.get_task(db, task_id)
    if not task:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=f"Task #{task_id} not found.",
        )
    if not task.share_token:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="This task has no share token. Please recreate it.",
        )

    share_url = f"{FRONTEND_URL}/t/{task.share_token}"
    return {
        "task_id":   task.id,
        "share_url": share_url,
        "token":     task.share_token,
    }


# ── Segment 8: Public task view (no auth) ─────────────────────────────────────

share_router = APIRouter(tags=["Public Share"])


@share_router.get(
    "/share/{token}",
    summary="Public view of a shared task",
    description="No authentication required. Returns task details for the share page.",
)
def public_task_view(
    token: str,
    db: Session = Depends(get_db),
) -> dict:
    task = crud.get_task_by_share_token(db, token)
    if not task:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Task not found or share link is invalid.",
        )

    signup_url = f"{FRONTEND_URL}?ref=share&task={token}"

    priority_emoji = {
        "critical": "🔴",
        "high":     "🟠",
        "medium":   "🟡",
        "low":      "🟢",
    }.get(task.priority.value if hasattr(task.priority, "value") else task.priority, "🟡")

    status_label = {
        "to_do":       "To Do",
        "in_progress": "In Progress",
        "completed":   "Done",
        "cancelled":   "Cancelled",
        "pending":     "Pending",
        "active":      "Active",
    }.get(task.status.value if hasattr(task.status, "value") else task.status, "To Do")

    return {
        "id":             task.id,
        "title":          task.title,
        "priority":       task.priority,
        "priority_emoji": priority_emoji,
        "status":         task.status,
        "status_label":   status_label,
        "assignee":       task.assignee,
        "deadline":       task.deadline,
        "created_at":     task.created_at.isoformat() if task.created_at else None,
        "signup_url":     signup_url,
    }


# ── Segment 3: Manual overdue ping trigger ────────────────────────────────────

@router.post(
    "/ping-overdue",
    summary="Manually trigger overdue task pings",
    status_code=http_status.HTTP_200_OK,
)
def trigger_ping_overdue(current_user: User = Depends(get_current_user)):
    try:
        from app.scheduler import run_ping_now
        summary = run_ping_now()
        return {"status": "ok", "result": summary}
    except Exception as exc:
        logger.exception("Manual ping trigger failed: %s", exc)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ping job failed: {exc}",
        )


# ── Segment 4: Manual daily rollup trigger ────────────────────────────────────

@router.post(
    "/daily-rollup",
    summary="Manually trigger the daily rollup job",
    status_code=http_status.HTTP_200_OK,
)
def trigger_daily_rollup(current_user: User = Depends(get_current_user)):
    try:
        from app.scheduler import run_daily_rollup_now
        summary = run_daily_rollup_now()
        return {"status": "ok", "result": summary}
    except Exception as exc:
        logger.exception("Manual daily rollup trigger failed: %s", exc)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Daily rollup failed: {exc}",
        )
