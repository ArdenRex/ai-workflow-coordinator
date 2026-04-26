"""
routers/tasks.py
────────────────
GET    /tasks                  →  list all tasks (with optional filters)
GET    /tasks/{id}             →  get a single task
PATCH  /tasks/{id}/status      →  update task status
DELETE /tasks/{id}             →  delete a task
GET    /tasks/{id}/share-link  →  get the public share URL for a task  [Segment 8]
GET    /share/{token}          →  public view of a task (no auth)       [Segment 8]
POST   /tasks/ping-overdue     →  manually trigger overdue ping job (Segment 3)
POST   /tasks/daily-rollup     →  manually trigger daily rollup job (Segment 4)
"""

import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status
from fastapi.responses import HTMLResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import crud
from app.database import get_db
from app.models import Priority, TaskStatus
from app.schemas import TaskListResponse, TaskResponse, TaskStatusUpdate

logger = logging.getLogger(__name__)

FRONTEND_URL = os.getenv("FRONTEND_URL", "").rstrip("/")

router = APIRouter(
    prefix="/tasks",
    tags=["Tasks"],
)


@router.get(
    "",
    response_model=TaskListResponse,
    summary="List all tasks",
)
def list_tasks(
    status: Optional[TaskStatus] = Query(default=None),
    assignee: Optional[str] = Query(default=None),
    priority: Optional[Priority] = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> TaskListResponse:
    try:
        total, tasks = crud.list_tasks(
            db,
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


# ── Segment 10: Ownership graph endpoint ──────────────────────────────────────

@router.get(
    "/graph",
    summary="Get ownership graph data",
    description="Returns task counts grouped by assignee for the ownership graph view.",
)
def get_ownership_graph(
    workspace_id: Optional[int] = Query(default=None),
    owner_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    try:
        data = crud.get_ownership_graph(db, workspace_id=workspace_id, owner_id=owner_id)
    except Exception as exc:
        logger.exception("Error fetching ownership graph: %s", exc)
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database error. Please retry.",
        ) from exc
    return data


@router.get(
    "/{task_id}",
    response_model=TaskResponse,
    summary="Get a task by ID",
)
def get_task(
    task_id: int,
    db: Session = Depends(get_db),
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
    return task


@router.patch(
    "/{task_id}/status",
    response_model=TaskResponse,
    summary="Update a task's status",
)
def update_task_status(
    task_id: int,
    update: TaskStatusUpdate,
    db: Session = Depends(get_db),
) -> TaskResponse:
    if task_id <= 0:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="task_id must be a positive integer.",
        )
    try:
        task = crud.update_task_status(db, task_id, update)
    except SQLAlchemyError as exc:
        logger.exception("DB error updating task %d status: %s", task_id, exc)
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database error. Please retry.",
        ) from exc
    if not task:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=f"Task #{task_id} not found.",
        )
    return task


@router.delete(
    "/{task_id}",
    status_code=http_status.HTTP_204_NO_CONTENT,
    summary="Delete a task",
)
def delete_task(
    task_id: int,
    db: Session = Depends(get_db),
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
    try:
        db.delete(task)
        db.commit()
        logger.info("Deleted task id=%d", task_id)
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
    description="Returns the shareable public URL for this task. No auth required to VIEW the link.",
)
def get_share_link(
    task_id: int,
    db: Session = Depends(get_db),
) -> dict:
    """
    Returns the share URL for the task.
    The URL points to the frontend public task view page.
    Format: https://your-app.vercel.app/t/<share_token>
    """
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


# ── Segment 8: Public task view (no auth) ────────────────────────────────────
# This is mounted on a SEPARATE router prefix so it lives at /share/{token}
# not /tasks/share/{token}. It is registered in main.py separately.

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
    """
    Public endpoint — anyone with the link can view the task.
    Returns enough info to render the public task card:
      title, priority, status, assignee, deadline, created_at.
    Does NOT return internal fields like source_message, owner_id, workspace_id.
    Includes a signup_url so visitors can click "Join" and create an account.
    """
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
        "id":           task.id,
        "title":        task.title,
        "priority":     task.priority,
        "priority_emoji": priority_emoji,
        "status":       task.status,
        "status_label": status_label,
        "assignee":     task.assignee,
        "deadline":     task.deadline,
        "created_at":   task.created_at.isoformat() if task.created_at else None,
        "signup_url":   signup_url,
    }


# ── Segment 3: Manual overdue ping trigger ────────────────────────────────────

@router.post(
    "/ping-overdue",
    summary="Manually trigger overdue task pings",
    status_code=http_status.HTTP_200_OK,
)
def trigger_ping_overdue():
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
def trigger_daily_rollup():
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
