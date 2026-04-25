"""
app/routers/public_api.py
──────────────────────────
Segment 13 — Public REST API for external tool integrations.

Allows Notion templates, Jira webhooks, Trello automations, and any
third-party tool to create, read, and update tasks programmatically.

Authentication:
  All endpoints require an API key passed in the X-API-Key header.
  Keys are workspace-scoped and created from the dashboard.

Endpoints:
  POST   /api/v1/tasks          — create a task
  GET    /api/v1/tasks          — list tasks (paginated, filterable)
  GET    /api/v1/tasks/{id}     — get a single task
  PUT    /api/v1/tasks/{id}     — update status / priority / assignee
  DELETE /api/v1/tasks/{id}     — soft-delete (cancel) a task

  GET    /api/v1/keys           — list API keys for workspace (JWT auth)
  POST   /api/v1/keys           — create a new API key (JWT auth)
  DELETE /api/v1/keys/{key_id}  — revoke a key (JWT auth)
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import ApiKey, Task, TaskStatus, Priority, UserRole, User
from app.routers.auth import get_current_user
from app.schemas import (
    PublicTaskCreate,
    PublicTaskUpdate,
    PublicTaskResponse,
    PublicTaskListResponse,
    ApiKeyCreate,
    ApiKeyResponse,
    ApiKeyCreatedResponse,
)
from app import crud

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["Public API"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def require_api_key(
    x_api_key: str = Header(..., alias="X-API-Key"),
    db: Session = Depends(get_db),
) -> ApiKey:
    if not x_api_key or not x_api_key.strip():
        raise HTTPException(status_code=401, detail="Missing X-API-Key header.")
    api_key = crud.get_api_key_by_value(db, x_api_key.strip())
    if not api_key or not api_key.is_active:
        raise HTTPException(status_code=401, detail="Invalid or revoked API key.")
    crud.touch_api_key(db, api_key.id)
    return api_key


def _task_to_response(task: Task) -> PublicTaskResponse:
    return PublicTaskResponse(
        id             = task.id,
        title          = task.title or "",
        description    = task.task_description,
        assignee       = task.assignee,
        deadline       = task.deadline,
        priority       = task.priority.value if task.priority else "medium",
        status         = task.status.value   if task.status   else "to_do",
        workspace_id   = task.workspace_id,
        source_message = task.source_message,
        created_at     = task.created_at.isoformat() if task.created_at else None,
        updated_at     = task.updated_at.isoformat() if task.updated_at else None,
    )


# ── Tasks ─────────────────────────────────────────────────────────────────────

@router.post("/tasks", response_model=PublicTaskResponse, status_code=201,
    summary="Create a task",
    description="Create a task from an external tool. Pass X-API-Key header.")
def api_create_task(
    payload: PublicTaskCreate,
    api_key: ApiKey  = Depends(require_api_key),
    db: Session      = Depends(get_db),
):
    task = Task(
        title            = payload.title.strip(),
        task_description = payload.description or payload.title.strip(),
        assignee         = payload.assignee,
        deadline         = payload.deadline,
        priority         = payload.priority or Priority.medium,
        status           = payload.status   or TaskStatus.to_do,
        workspace_id     = api_key.workspace_id,
        source_message   = f"[API] {payload.source or 'external'}",
    )
    db.add(task)
    try:
        db.commit()
        db.refresh(task)
    except Exception as exc:
        db.rollback()
        logger.error("API create_task: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create task.")
    logger.info("API task created id=%s workspace=%s", task.id, api_key.workspace_id)
    return _task_to_response(task)


@router.get("/tasks", response_model=PublicTaskListResponse,
    summary="List tasks")
def api_list_tasks(
    status:   Optional[str] = Query(None),
    assignee: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    skip:     int           = Query(0, ge=0),
    limit:    int           = Query(50, ge=1, le=200),
    api_key:  ApiKey        = Depends(require_api_key),
    db:       Session       = Depends(get_db),
):
    try:
        status_f   = TaskStatus(status)   if status   else None
        priority_f = Priority(priority)   if priority else None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    total, tasks = crud.list_tasks(
        db, status=status_f, assignee=assignee, priority=priority_f,
        skip=skip, limit=limit, workspace_id=api_key.workspace_id,
    )
    return PublicTaskListResponse(
        total=total, skip=skip, limit=limit,
        tasks=[_task_to_response(t) for t in tasks],
    )


@router.get("/tasks/{task_id}", response_model=PublicTaskResponse,
    summary="Get a task")
def api_get_task(
    task_id: int,
    api_key: ApiKey  = Depends(require_api_key),
    db: Session      = Depends(get_db),
):
    task = crud.get_task(db, task_id)
    if not task or task.workspace_id != api_key.workspace_id:
        raise HTTPException(status_code=404, detail="Task not found.")
    return _task_to_response(task)


@router.put("/tasks/{task_id}", response_model=PublicTaskResponse,
    summary="Update a task")
def api_update_task(
    task_id: int,
    payload: PublicTaskUpdate,
    api_key: ApiKey  = Depends(require_api_key),
    db: Session      = Depends(get_db),
):
    task = crud.get_task(db, task_id)
    if not task or task.workspace_id != api_key.workspace_id:
        raise HTTPException(status_code=404, detail="Task not found.")
    updates = payload.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update.")
    allowed = {"assignee", "deadline", "priority", "status", "task_description"}
    for k, v in updates.items():
        if k in allowed:
            setattr(task, k, v)
    try:
        db.commit()
        db.refresh(task)
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to update task.")
    return _task_to_response(task)


@router.delete("/tasks/{task_id}", status_code=204, summary="Cancel a task")
def api_delete_task(
    task_id: int,
    api_key: ApiKey  = Depends(require_api_key),
    db: Session      = Depends(get_db),
):
    task = crud.get_task(db, task_id)
    if not task or task.workspace_id != api_key.workspace_id:
        raise HTTPException(status_code=404, detail="Task not found.")
    task.status = TaskStatus.cancelled
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to cancel task.")


# ── API Key management (JWT auth) ─────────────────────────────────────────────

@router.get("/keys", response_model=list[ApiKeyResponse],
    summary="List API keys")
def list_api_keys(
    current_user: User    = Depends(get_current_user),
    db:           Session = Depends(get_db),
):
    if not current_user.workspace_id:
        raise HTTPException(status_code=404, detail="No workspace found.")
    return crud.list_api_keys(db, current_user.workspace_id)


@router.post("/keys", response_model=ApiKeyCreatedResponse, status_code=201,
    summary="Create API key",
    description="The full key is only shown once. Store it securely.")
def create_api_key(
    payload:      ApiKeyCreate,
    current_user: User    = Depends(get_current_user),
    db:           Session = Depends(get_db),
):
    if current_user.role not in (UserRole.architect,):
        raise HTTPException(status_code=403, detail="Only Architects can create API keys.")
    if not current_user.workspace_id:
        raise HTTPException(status_code=404, detail="No workspace found.")
    raw_key, key_obj = crud.create_api_key(
        db,
        workspace_id = current_user.workspace_id,
        name         = payload.name,
        created_by   = current_user.id,
    )
    return ApiKeyCreatedResponse(
        id           = key_obj.id,
        name         = key_obj.name,
        key          = raw_key,
        key_prefix   = key_obj.key_prefix,
        workspace_id = key_obj.workspace_id,
        is_active    = key_obj.is_active,
        created_at   = key_obj.created_at,
    )


@router.delete("/keys/{key_id}", status_code=204, summary="Revoke API key")
def revoke_api_key(
    key_id:       int,
    current_user: User    = Depends(get_current_user),
    db:           Session = Depends(get_db),
):
    if current_user.role not in (UserRole.architect,):
        raise HTTPException(status_code=403, detail="Only Architects can revoke API keys.")
    if not current_user.workspace_id:
        raise HTTPException(status_code=404, detail="No workspace found.")
    if not crud.revoke_api_key(db, key_id, current_user.workspace_id):
        raise HTTPException(status_code=404, detail="API key not found.")
