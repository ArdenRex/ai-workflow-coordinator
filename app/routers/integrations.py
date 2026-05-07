"""
routers/integrations.py
────────────────────────
Segment 11 — Notion, Jira, and Trello API integrations.
"""

import logging
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Task, UserRole
# from app.routers.auth import get_current_user  <-- REMOVED TO BREAK CIRCULAR IMPORT
from app.schemas import (
    IntegrationConfig,
    IntegrationStatusResponse,
    IntegrationSyncRequest,
    IntegrationSyncResponse,
    TaskSyncResult,
)
from app import crud

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/integrations", tags=["Integrations"])

# ── CIRCULAR IMPORT FIX ───────────────────────────────────────────────────────
def get_current_user_wrapper(*args, **kwargs):
    """Local import wrapper to prevent circular dependency with auth.py"""
    from app.routers.auth import get_current_user
    return get_current_user(*args, **kwargs)

# ── helpers ────────────────────────────────────────────────────────────────────

def _require_architect(current_user):
    if current_user.role != UserRole.architect:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Architects can manage integrations.",
        )

def _require_workspace(current_user):
    if not current_user.workspace_id:
        raise HTTPException(status_code=400, detail="User has no workspace.")
    return current_user.workspace_id

def _fetch_tasks(db, workspace_id, task_ids):
    query = db.query(Task).filter(Task.workspace_id == workspace_id)
    if task_ids:
        query = query.filter(Task.id.in_(task_ids))
    return query.all()

# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/status", response_model=IntegrationStatusResponse)
async def get_status(
    current_user=Depends(get_current_user_wrapper),
    db: Session = Depends(get_db)
):
    workspace_id = _require_workspace(current_user)
    cfg = crud.get_integration_config(db, workspace_id)
    return IntegrationStatusResponse(
        notion_configured=bool(cfg.get("notion_api_key")),
        jira_configured=bool(cfg.get("jira_base_url")),
        trello_configured=bool(cfg.get("trello_api_key")),
    )

@router.put("/config", response_model=IntegrationStatusResponse)
async def update_config(
    body: IntegrationConfig,
    current_user=Depends(get_current_user_wrapper),
    db: Session = Depends(get_db)
):
    _require_architect(current_user)
    workspace_id = _require_workspace(current_user)
    updated_cfg = crud.update_integration_config(db, workspace_id, body.dict(exclude_unset=True))
    return IntegrationStatusResponse(
        notion_configured=bool(updated_cfg.get("notion_api_key")),
        jira_configured=bool(updated_cfg.get("jira_base_url")),
        trello_configured=bool(updated_cfg.get("trello_api_key")),
    )

@router.post("/notion/sync", response_model=IntegrationSyncResponse)
async def sync_to_notion(
    body: IntegrationSyncRequest,
    current_user=Depends(get_current_user_wrapper),
    db: Session = Depends(get_db),
):
    _require_architect(current_user)
    workspace_id = _require_workspace(current_user)
    cfg = crud.get_integration_config(db, workspace_id)
    api_key = cfg.get("notion_api_key", "").strip()
    db_id = cfg.get("notion_database_id", "").strip()
    
    if not api_key or not db_id:
        raise HTTPException(status_code=422, detail="Notion not configured.")
        
    tasks = _fetch_tasks(db, workspace_id, body.task_ids or None)
    results = await _push_to_notion(api_key, db_id, tasks)
    succeeded = sum(1 for r in results if r.success)
    return IntegrationSyncResponse(integration="notion", total=len(results), succeeded=succeeded, failed=len(results)-succeeded, results=results)

@router.post("/jira/sync", response_model=IntegrationSyncResponse)
async def sync_to_jira(
    body: IntegrationSyncRequest,
    current_user=Depends(get_current_user_wrapper),
    db: Session = Depends(get_db),
):
    _require_architect(current_user)
    workspace_id = _require_workspace(current_user)
    cfg = crud.get_integration_config(db, workspace_id)
    base_url = cfg.get("jira_base_url", "").strip()
    email = cfg.get("jira_email", "").strip()
    api_token = cfg.get("jira_api_token", "").strip()
    project_key = cfg.get("jira_project_key", "").strip()

    if not all([base_url, email, api_token, project_key]):
        raise HTTPException(status_code=422, detail="Jira not fully configured.")
    
    tasks = _fetch_tasks(db, workspace_id, body.task_ids or None)
    results = await _push_to_jira(base_url, email, api_token, project_key, tasks)
    succeeded = sum(1 for r in results if r.success)
    return IntegrationSyncResponse(integration="jira", total=len(results), succeeded=succeeded, failed=len(results)-succeeded, results=results)

@router.post("/trello/sync", response_model=IntegrationSyncResponse)
async def sync_to_trello(
    body: IntegrationSyncRequest,
    current_user=Depends(get_current_user_wrapper),
    db: Session = Depends(get_db),
):
    _require_architect(current_user)
    workspace_id = _require_workspace(current_user)
    cfg = crud.get_integration_config(db, workspace_id)
    api_key = cfg.get("trello_api_key", "").strip()
    token = cfg.get("trello_token", "").strip()
    list_id = cfg.get("trello_list_id", "").strip()

    if not all([api_key, token, list_id]):
        raise HTTPException(status_code=422, detail="Trello not fully configured.")
    
    tasks = _fetch_tasks(db, workspace_id, body.task_ids or None)
    results = await _push_to_trello(api_key, token, list_id, tasks)
    succeeded = sum(1 for r in results if r.success)
    return IntegrationSyncResponse(integration="trello", total=len(results), succeeded=succeeded, failed=len(results)-succeeded, results=results)

# ── External API Push logic (Placeholders) ─────────────────────────────────────
async def _push_to_notion(api_key, database_id, tasks):
    # logic here...
    return []

async def _push_to_jira(base_url, email, api_token, project_key, tasks):
    # logic here...
    return []

async def _push_to_trello(api_key, token, list_id, tasks):
    # logic here...
    return []