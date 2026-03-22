"""
routers/tasks.py
────────────────
GET   /tasks               →  list all tasks (with optional filters)
GET   /tasks/{id}          →  get a single task
PATCH /tasks/{id}/status   →  update task status
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import crud
from app.database import get_db
from app.models import Priority, TaskStatus
from app.schemas import TaskListResponse, TaskResponse, TaskStatusUpdate

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/tasks",
    tags=["Tasks"],
)


@router.get(
    "",
    response_model=TaskListResponse,
    summary="List all tasks",
    description="Returns tasks with optional filters. Supports pagination.",
)
def list_tasks(
    status: Optional[TaskStatus] = Query(default=None, description="Filter by task status"),
    assignee: Optional[str] = Query(default=None, description="Filter by assignee name (partial match)"),
    priority: Optional[Priority] = Query(default=None, description="Filter by priority"),
    skip: int = Query(default=0, ge=0, description="Number of records to skip"),
    limit: int = Query(default=50, ge=1, le=200, description="Max records to return"),
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
    description="Valid statuses: pending, in_progress, completed, cancelled",
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
