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

Auth: current user must be an Architect.
Credentials live in WorkspaceSettings.integration_config (JSON column).
"""

import logging
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

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
from app import crud

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/integrations", tags=["Integrations"])


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


def _fetch_tasks(db: Session, workspace_id: int, task_ids: Optional[list[int]]) -> list[Task]:
    from sqlalchemy import select
    q = db.query(Task).filter(Task.workspace_id == workspace_id)
    if task_ids:
        q = q.filter(Task.id.in_(task_ids))
    tasks = q.all()
    if not tasks:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No tasks found for the given criteria.",
        )
    return tasks


def _priority_label(priority) -> str:
    return priority.value if hasattr(priority, "value") else str(priority)


def _status_label(s) -> str:
    v = s.value if hasattr(s, "value") else str(s)
    return v.replace("_", " ").title()


# ── Notion ─────────────────────────────────────────────────────────────────────

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
                payload["properties"]["Assignee"] = {
                    "rich_text": [{"text": {"content": task.assignee}}]
                }
            if task.deadline:
                payload["properties"]["Due"] = {"date": {"start": task.deadline}}
            try:
                resp = await client.post("https://api.notion.com/v1/pages", headers=headers, json=payload)
                if resp.status_code in (200, 201):
                    d = resp.json()
                    results.append(TaskSyncResult(task_id=task.id, success=True, external_id=d.get("id"), external_url=d.get("url")))
                else:
                    err = resp.json().get("message", resp.text[:200])
                    results.append(TaskSyncResult(task_id=task.id, success=False, error=f"Notion {resp.status_code}: {err}"))
            except httpx.RequestError as exc:
                results.append(TaskSyncResult(task_id=task.id, success=False, error=f"Network error: {exc}"))
    return results


# ── Jira ───────────────────────────────────────────────────────────────────────

_JIRA_PRIORITY = {"critical": "Highest", "high": "High", "medium": "Medium", "low": "Low"}


async def _push_to_jira(base_url: str, email: str, api_token: str, project_key: str, tasks: list[Task]) -> list[TaskSyncResult]:
    results: list[TaskSyncResult] = []
    api = base_url.rstrip("/") + "/rest/api/3"
    async with httpx.AsyncClient(timeout=15.0, auth=(email, api_token)) as client:
        for task in tasks:
            title = task.title or task.task_description or f"Task #{task.id}"
            priority_str = _priority_label(task.priority).lower()
            payload: dict[str, Any] = {
                "fields": {
                    "project":   {"key": project_key},
                    "summary":   title,
                    "issuetype": {"name": "Task"},
                    "priority":  {"name": _JIRA_PRIORITY.get(priority_str, "Medium")},
                }
            }
            if task.task_description and task.task_description != task.title:
                payload["fields"]["description"] = {
                    "type": "doc", "version": 1,
                    "content": [{"type": "paragraph", "content": [{"type": "text", "text": task.task_description}]}],
                }
            if task.deadline:
                payload["fields"]["duedate"] = task.deadline
            try:
                resp = await client.post(
                    f"{api}/issue",
                    json=payload,
                    headers={"Accept": "application/json", "Content-Type": "application/json"},
                )
                if resp.status_code in (200, 201):
                    d = resp.json()
                    key = d.get("key", "")
                    results.append(TaskSyncResult(task_id=task.id, success=True, external_id=key, external_url=f"{base_url.rstrip('/')}/browse/{key}"))
                else:
                    results.append(TaskSyncResult(task_id=task.id, success=False, error=f"Jira {resp.status_code}: {resp.text[:300]}"))
            except httpx.RequestError as exc:
                results.append(TaskSyncResult(task_id=task.id, success=False, error=f"Network error: {exc}"))
    return results


# ── Trello ─────────────────────────────────────────────────────────────────────

_TRELLO_COLORS = {"critical": "red", "high": "orange", "medium": "yellow", "low": "green"}


async def _push_to_trello(api_key: str, token: str, list_id: str, tasks: list[Task]) -> list[TaskSyncResult]:
    results: list[TaskSyncResult] = []
    base = "https://api.trello.com/1"
    async with httpx.AsyncClient(timeout=15.0) as client:
        for task in tasks:
            title = task.title or task.task_description or f"Task #{task.id}"
            priority_str = _priority_label(task.priority).lower()
            params: dict[str, Any] = {"key": api_key, "token": token, "idList": list_id, "name": title}
            if task.deadline:
                params["due"] = task.deadline + "T23:59:59Z"
            desc_parts = []
            if task.assignee:
                desc_parts.append(f"Assignee: {task.assignee}")
            if task.task_description and task.task_description != task.title:
                desc_parts.append(task.task_description)
            if desc_parts:
                params["desc"] = "\n".join(desc_parts)
            try:
                resp = await client.post(f"{base}/cards", params=params)
                if resp.status_code in (200, 201):
                    d = resp.json()
                    card_id = d.get("id", "")
                    # Add priority label (non-fatal)
                    try:
                        await client.post(f"{base}/cards/{card_id}/labels", params={
                            "key": api_key, "token": token,
                            "color": _TRELLO_COLORS.get(priority_str, "yellow"),
                            "name": priority_str.capitalize(),
                        })
                    except Exception:
                        pass
                    results.append(TaskSyncResult(task_id=task.id, success=True, external_id=card_id, external_url=d.get("url")))
                else:
                    results.append(TaskSyncResult(task_id=task.id, success=False, error=f"Trello {resp.status_code}: {resp.text[:300]}"))
            except httpx.RequestError as exc:
                results.append(TaskSyncResult(task_id=task.id, success=False, error=f"Network error: {exc}"))
    return results


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/status", response_model=IntegrationStatusResponse)
async def get_integration_status(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Returns which integrations are fully configured for the workspace."""
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
    """Save or update integration credentials. Only provided keys are updated."""
    _require_architect(current_user)
    workspace_id = _require_workspace(current_user)
    updated = crud.save_integration_config(db, workspace_id, body.model_dump(exclude_none=True))
    return {"message": "Integration config saved.", "configured_keys": list(updated.keys())}


@router.post("/notion/sync", response_model=IntegrationSyncResponse)
async def sync_to_notion(
    body: IntegrationSyncRequest,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Push tasks to a Notion database."""
    _require_architect(current_user)
    workspace_id = _require_workspace(current_user)
    cfg = crud.get_integration_config(db, workspace_id)
    token = cfg.get("notion_token", "").strip()
    database_id = cfg.get("notion_database_id", "").strip()
    if not token or not database_id:
        raise HTTPException(status_code=422, detail="Notion not configured. Save notion_token and notion_database_id via PUT /integrations/config first.")
    tasks = _fetch_tasks(db, workspace_id, body.task_ids or None)
    results = await _push_to_notion(token, database_id, tasks)
    succeeded = sum(1 for r in results if r.success)
    return IntegrationSyncResponse(integration="notion", total=len(results), succeeded=succeeded, failed=len(results) - succeeded, results=results)


@router.post("/jira/sync", response_model=IntegrationSyncResponse)
async def sync_to_jira(
    body: IntegrationSyncRequest,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Push tasks to a Jira project."""
    _require_architect(current_user)
    workspace_id = _require_workspace(current_user)
    cfg = crud.get_integration_config(db, workspace_id)
    base_url = cfg.get("jira_base_url", "").strip()
    email = cfg.get("jira_email", "").strip()
    api_token = cfg.get("jira_api_token", "").strip()
    project_key = cfg.get("jira_project_key", "").strip()
    if not all([base_url, email, api_token, project_key]):
        raise HTTPException(status_code=422, detail="Jira not fully configured. Required: jira_base_url, jira_email, jira_api_token, jira_project_key.")
    tasks = _fetch_tasks(db, workspace_id, body.task_ids or None)
    results = await _push_to_jira(base_url, email, api_token, project_key, tasks)
    succeeded = sum(1 for r in results if r.success)
    return IntegrationSyncResponse(integration="jira", total=len(results), succeeded=succeeded, failed=len(results) - succeeded, results=results)


@router.post("/trello/sync", response_model=IntegrationSyncResponse)
async def sync_to_trello(
    body: IntegrationSyncRequest,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Push tasks to a Trello board list."""
    _require_architect(current_user)
    workspace_id = _require_workspace(current_user)
    cfg = crud.get_integration_config(db, workspace_id)
    api_key = cfg.get("trello_api_key", "").strip()
    token = cfg.get("trello_token", "").strip()
    list_id = cfg.get("trello_list_id", "").strip()
    if not all([api_key, token, list_id]):
        raise HTTPException(status_code=422, detail="Trello not fully configured. Required: trello_api_key, trello_token, trello_list_id.")
    tasks = _fetch_tasks(db, workspace_id, body.task_ids or None)
    results = await _push_to_trello(api_key, token, list_id, tasks)
    succeeded = sum(1 for r in results if r.success)
    return IntegrationSyncResponse(integration="trello", total=len(results), succeeded=succeeded, failed=len(results) - succeeded, results=results)
