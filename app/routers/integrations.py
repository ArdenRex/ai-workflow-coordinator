"""
routers/integrations.py
────────────────────────
Segment 11 — Notion, Jira, and Trello API integrations.

Endpoints:
  GET  /integrations/status           Which integrations are configured
  PUT  /integrations/config           Save / update credentials
  POST /integrations/notion/sync      Push tasks → Notion database
  POST /integrations/jira/sync        Push tasks → Jira project
  POST /integrations/trello/sync      Push tasks → Trello board list

Auth: Current user must be an Architect.
Credentials live in WorkspaceSettings.integration_config (JSON column).
"""

import logging
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import crud
from app.database import get_db
from app.models import Task, UserRole
from app.routers.auth import get_current_user
from app.schemas import (
    IntegrationConfig,
    IntegrationStatusResponse,
    IntegrationSyncRequest,
    IntegrationSyncResponse,
    TaskSyncResult,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/integrations", tags=["Integrations"])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _require_architect(current_user):
    """Utility to restrict integration management to Architect roles."""
    if current_user.role != UserRole.architect:
        logger.warning("Unauthorized access attempt: user_id=%d role=%s", current_user.id, current_user.role)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Architects can manage workspace integrations.",
        )


def _require_workspace(current_user) -> int:
    """Ensure the user is associated with a workspace."""
    if not current_user.workspace_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no workspace associated. Please join a workspace first.",
        )
    return current_user.workspace_id


def _fetch_tasks(db: Session, workspace_id: int, task_ids: Optional[list[int]]) -> list[Task]:
    """Retrieves tasks from the database, filtered by IDs if provided."""
    query = db.query(Task).filter(Task.workspace_id == workspace_id)
    if task_ids:
        query = query.filter(Task.id.in_(task_ids))
    
    tasks = query.all()
    if not tasks:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No tasks found for the given criteria.",
        )
    return tasks


def _priority_label(priority) -> str:
    """Standardizes priority labels for external API payloads."""
    return str(priority.value if hasattr(priority, "value") else priority)


def _status_label(s) -> str:
    """Converts internal status to human-readable format (e.g., 'in_progress' -> 'In Progress')."""
    val = str(s.value if hasattr(s, "value") else s)
    return val.replace("_", " ").title()


# ── Notion Integration ────────────────────────────────────────────────────────

async def _push_to_notion(token: str, database_id: str, tasks: list[Task]) -> list[TaskSyncResult]:
    results: list[TaskSyncResult] = []
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }
    
    async with httpx.AsyncClient(timeout=15.0) as client:
        for task in tasks:
            title = task.title or task.task_description or f"Task #{task.id}"
            payload: dict[str, Any] = {
                "parent": {"database_id": database_id},
                "properties": {
                    "Name":     {"title":  [{"text": {"content": title}}]},
                    "Status":   {"select": {"name": _status_label(task.status)}},
                    "Priority": {"select": {"name": _priority_label(task.priority).capitalize()}},
                },
            }
            
            if task.assignee:
                payload["properties"]["Assignee"] = {"rich_text": [{"text": {"content": task.assignee}}]}
            if task.deadline:
                # Notion expects ISO date strings
                payload["properties"]["Due"] = {"date": {"start": str(task.deadline)}}

            try:
                resp = await client.post("https://api.notion.com/v1/pages", headers=headers, json=payload)
                if resp.status_code in (200, 201):
                    data = resp.json()
                    results.append(TaskSyncResult(
                        task_id=task.id, 
                        success=True, 
                        external_id=data.get("id"), 
                        external_url=data.get("url")
                    ))
                else:
                    err_data = resp.json()
                    err_msg = err_data.get("message", f"Notion API Error {resp.status_code}")
                    results.append(TaskSyncResult(task_id=task.id, success=False, error=err_msg))
            except Exception as exc:
                logger.error("Notion sync failed for task_id=%d: %s", task.id, exc)
                results.append(TaskSyncResult(task_id=task.id, success=False, error=f"Network error: {str(exc)}"))
    
    return results


# ── Jira Integration ──────────────────────────────────────────────────────────

_JIRA_PRIORITY_MAP = {"critical": "Highest", "high": "High", "medium": "Medium", "low": "Low"}

async def _push_to_jira(base_url: str, email: str, api_token: str, project_key: str, tasks: list[Task]) -> list[TaskSyncResult]:
    results: list[TaskSyncResult] = []
    api_endpoint = f"{base_url.rstrip('/')}/rest/api/3/issue"
    
    async with httpx.AsyncClient(timeout=15.0, auth=(email, api_token)) as client:
        for task in tasks:
            title = task.title or task.task_description or f"Task #{task.id}"
            priority_key = _priority_label(task.priority).lower()
            
            payload: dict[str, Any] = {
                "fields": {
                    "project":   {"key": project_key},
                    "summary":   title,
                    "issuetype": {"name": "Task"},
                    "priority":  {"name": _JIRA_PRIORITY_MAP.get(priority_key, "Medium")},
                }
            }
            
            if task.task_description and task.task_description != task.title:
                payload["fields"]["description"] = {
                    "type": "doc", "version": 1,
                    "content": [{"type": "paragraph", "content": [{"type": "text", "text": task.task_description}]}],
                }
            if task.deadline:
                payload["fields"]["duedate"] = str(task.deadline)

            try:
                resp = await client.post(api_endpoint, json=payload)
                if resp.status_code in (200, 201):
                    data = resp.json()
                    key = data.get("key", "")
                    results.append(TaskSyncResult(
                        task_id=task.id, 
                        success=True, 
                        external_id=key, 
                        external_url=f"{base_url.rstrip('/')}/browse/{key}"
                    ))
                else:
                    results.append(TaskSyncResult(task_id=task.id, success=False, error=f"Jira Error {resp.status_code}: {resp.text[:200]}"))
            except Exception as exc:
                results.append(TaskSyncResult(task_id=task.id, success=False, error=f"Network error: {str(exc)}"))
                
    return results


# ── Trello Integration ────────────────────────────────────────────────────────

_TRELLO_COLOR_MAP = {"critical": "red", "high": "orange", "medium": "yellow", "low": "green"}

async def _push_to_trello(api_key: str, token: str, list_id: str, tasks: list[Task]) -> list[TaskSyncResult]:
    results: list[TaskSyncResult] = []
    base_url = "https://api.trello.com/1"
    
    async with httpx.AsyncClient(timeout=15.0) as client:
        for task in tasks:
            title = task.title or task.task_description or f"Task #{task.id}"
            priority_key = _priority_label(task.priority).lower()
            
            params: dict[str, Any] = {"key": api_key, "token": token, "idList": list_id, "name": title}
            if task.deadline:
                params["due"] = f"{task.deadline}T23:59:59Z"
            
            desc_parts = []
            if task.assignee: desc_parts.append(f"Assignee: {task.assignee}")
            if task.task_description and task.task_description != task.title:
                desc_parts.append(task.task_description)
            if desc_parts:
                params["desc"] = "\n".join(desc_parts)

            try:
                resp = await client.post(f"{base_url}/cards", params=params)
                if resp.status_code in (200, 201):
                    data = resp.json()
                    card_id = data.get("id", "")
                    # Add priority label as a secondary, non-blocking request
                    try:
                        await client.post(f"{base_url}/cards/{card_id}/labels", params={
                            "key": api_key, "token": token,
                            "color": _TRELLO_COLOR_MAP.get(priority_key, "yellow"),
                            "name": priority_key.capitalize(),
                        })
                    except Exception:
                        pass
                    results.append(TaskSyncResult(task_id=task.id, success=True, external_id=card_id, external_url=data.get("url")))
                else:
                    results.append(TaskSyncResult(task_id=task.id, success=False, error=f"Trello Error {resp.status_code}"))
            except Exception as exc:
                results.append(TaskSyncResult(task_id=task.id, success=False, error=str(exc)))
                
    return results


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/status", response_model=IntegrationStatusResponse)
async def get_integration_status(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Returns connectivity status for Notion, Jira, and Trello integrations."""
    _require_architect(current_user)
    workspace_id = _require_workspace(current_user)
    cfg = crud.get_integration_config(db, workspace_id)
    
    return IntegrationStatusResponse(
        notion_configured=bool(cfg.get("notion_token") and cfg.get("notion_database_id")),
        jira_configured=bool(cfg.get("jira_base_url") and cfg.get("jira_email") and cfg.get("jira_api_token") and cfg.get("jira_project_key")),
        trello_configured=bool(cfg.get("trello_api_key") and cfg.get("trello_token") and cfg.get("trello_list_id")),
    )


@router.put("/config", response_model=dict)
async def save_integration_config(
    body: IntegrationConfig,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Updates integration credentials. Only provided keys are modified."""
    _require_architect(current_user)
    workspace_id = _require_workspace(current_user)
    updated = crud.save_integration_config(db, workspace_id, body.model_dump(exclude_none=True))
    
    logger.info("Workspace id=%d updated integration config: %s", workspace_id, list(updated.keys()))
    return {"message": "Integration config updated.", "configured_keys": list(updated.keys())}


@router.post("/notion/sync", response_model=IntegrationSyncResponse)
async def sync_to_notion(
    body: IntegrationSyncRequest,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Pushes tasks to a configured Notion database."""
    _require_architect(current_user)
    workspace_id = _require_workspace(current_user)
    cfg = crud.get_integration_config(db, workspace_id)
    
    token = cfg.get("notion_token", "").strip()
    db_id = cfg.get("notion_database_id", "").strip()
    
    if not token or not db_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Notion is not configured.")
    
    tasks = _fetch_tasks(db, workspace_id, body.task_ids)
    results = await _push_to_notion(token, db_id, tasks)
    
    succeeded = sum(1 for r in results if r.success)
    return IntegrationSyncResponse(
        integration="notion", 
        total=len(results), 
        succeeded=succeeded, 
        failed=len(results) - succeeded, 
        results=results
    )


@router.post("/jira/sync", response_model=IntegrationSyncResponse)
async def sync_to_jira(
    body: IntegrationSyncRequest,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Pushes tasks to a configured Jira project."""
    _require_architect(current_user)
    workspace_id = _require_workspace(current_user)
    cfg = crud.get_integration_config(db, workspace_id)
    
    base_url = cfg.get("jira_base_url", "").strip()
    email    = cfg.get("jira_email", "").strip()
    token    = cfg.get("jira_api_token", "").strip()
    proj     = cfg.get("jira_project_key", "").strip()
    
    if not all([base_url, email, token, proj]):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Jira is not fully configured.")
    
    tasks = _fetch_tasks(db, workspace_id, body.task_ids)
    results = await _push_to_jira(base_url, email, token, proj, tasks)
    
    succeeded = sum(1 for r in results if r.success)
    return IntegrationSyncResponse(
        integration="jira", 
        total=len(results), 
        succeeded=succeeded, 
        failed=len(results) - succeeded, 
        results=results
    )


@router.post("/trello/sync", response_model=IntegrationSyncResponse)
async def sync_to_trello(
    body: IntegrationSyncRequest,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Pushes tasks to a configured Trello board list."""
    _require_architect(current_user)
    workspace_id = _require_workspace(current_user)
    cfg = crud.get_integration_config(db, workspace_id)
    
    api_key = cfg.get("trello_api_key", "").strip()
    token   = cfg.get("trello_token", "").strip()
    list_id = cfg.get("trello_list_id", "").strip()
    
    if not all([api_key, token, list_id]):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Trello is not fully configured.")
    
    tasks = _fetch_tasks(db, workspace_id, body.task_ids)
    results = await _push_to_trello(api_key, token, list_id, tasks)
    
    succeeded = sum(1 for r in results if r.success)
    return IntegrationSyncResponse(
        integration="trello", 
        total=len(results), 
        succeeded=succeeded, 
        failed=len(results) - succeeded, 
        results=results
    )