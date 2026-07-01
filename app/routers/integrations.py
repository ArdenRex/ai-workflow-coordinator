"""
routers/integrations.py
────────────────────────
Circular import resolution for FABRIFIX UPVC.
"""

import logging
import base64
from typing import Any, Optional
import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Priority, Task, TaskStatus, UserRole
from app.schemas import (
    IntegrationConfig,
    IntegrationImportRequest,
    IntegrationImportResponse,
    ImportedTaskResult,
)
from app import crud

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/integrations", tags=["Integrations"])

# ── CIRCULAR IMPORT WRAPPER ───────────────────────────────────────────────────
def get_current_user_wrapper(*args, **kwargs):
    """Dynamically imports auth to break dependency loop at startup."""
    from app.routers.auth import get_current_user
    return get_current_user(*args, **kwargs)

# ── Helper functions for logic ────────────────────────────────────────────────

def _require_architect(current_user):
    if current_user.role != UserRole.architect:
        raise HTTPException(status_code=403, detail="Architect role required.")

def _require_workspace(current_user):
    if not current_user.workspace_id:
        raise HTTPException(status_code=400, detail="No workspace found.")
    return current_user.workspace_id

# ── Trello helpers ─────────────────────────────────────────────────────────────

TRELLO_API_BASE = "https://api.trello.com/1"


async def _fetch_trello_cards(api_key: str, token: str, list_id: str, limit: int) -> list[dict]:
    """
    Fetch cards from a Trello list. Raises HTTPException on auth/network errors.
    """
    params = {
        "key": api_key,
        "token": token,
        "fields": "name,desc,due,dueComplete,shortUrl,closed",
        "limit": limit,
    }
    url = f"{TRELLO_API_BASE}/lists/{list_id}/cards"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, params=params)
    except httpx.RequestError as exc:
        logger.error("Trello request failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail="Could not reach Trello. Please try again.")

    if resp.status_code == 401:
        raise HTTPException(status_code=400, detail="Trello rejected the API key/token. Double-check your credentials.")
    if resp.status_code == 404:
        raise HTTPException(status_code=400, detail="Trello list not found. Check the list ID.")
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Trello API error ({resp.status_code}).")

    return resp.json()


# ── Notion helpers ─────────────────────────────────────────────────────────────

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


async def _fetch_notion_pages(token: str, database_id: str, limit: int) -> list[dict]:
    """
    Query a Notion database and return its pages. Raises HTTPException on
    auth/network errors.
    """
    url = f"{NOTION_API_BASE}/databases/{database_id}/query"
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }
    body = {"page_size": min(max(limit, 1), 100)}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, headers=headers, json=body)
    except httpx.RequestError as exc:
        logger.error("Notion request failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail="Could not reach Notion. Please try again.")

    if resp.status_code == 401:
        raise HTTPException(status_code=400, detail="Notion rejected the integration token. Double-check it.")
    if resp.status_code == 404:
        raise HTTPException(status_code=400, detail="Notion database not found. Check the database ID and make sure it's shared with your integration.")
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Notion API error ({resp.status_code}).")

    return resp.json().get("results", [])


def _notion_title(props: dict) -> Optional[str]:
    """Notion databases can name their title property anything, so find it by type."""
    for prop in props.values():
        if prop.get("type") == "title":
            parts = prop.get("title", [])
            text = "".join(p.get("plain_text", "") for p in parts).strip()
            return text or None
    return None


def _notion_rich_text(props: dict, preferred_names: tuple[str, ...] = ()) -> Optional[str]:
    """Best-effort description lookup among rich_text properties."""
    candidates = [(k, v) for k, v in props.items() if v.get("type") == "rich_text"]
    for name in preferred_names:
        for key, val in candidates:
            if key.strip().lower() == name:
                text = "".join(p.get("plain_text", "") for p in val.get("rich_text", [])).strip()
                if text:
                    return text
    for _, val in candidates:
        text = "".join(p.get("plain_text", "") for p in val.get("rich_text", [])).strip()
        if text:
            return text
    return None


def _notion_date(props: dict) -> Optional[str]:
    for prop in props.values():
        if prop.get("type") == "date":
            d = prop.get("date")
            if d and d.get("start"):
                return d["start"]
    return None


def _notion_assignee(props: dict) -> Optional[str]:
    for prop in props.values():
        if prop.get("type") == "people":
            people = prop.get("people", [])
            if people:
                return people[0].get("name") or people[0].get("id")
    return None


_NOTION_STATUS_MAP = {
    "done": TaskStatus.completed, "complete": TaskStatus.completed, "completed": TaskStatus.completed, "closed": TaskStatus.completed,
    "in progress": TaskStatus.in_progress, "in_progress": TaskStatus.in_progress, "doing": TaskStatus.in_progress, "active": TaskStatus.active,
    "cancelled": TaskStatus.cancelled, "canceled": TaskStatus.cancelled, "won't do": TaskStatus.cancelled,
    "pending": TaskStatus.pending, "blocked": TaskStatus.pending, "waiting": TaskStatus.pending,
}


def _notion_status(props: dict) -> TaskStatus:
    for prop in props.values():
        if prop.get("type") in ("status", "select"):
            sel = prop.get(prop["type"])
            if sel and sel.get("name"):
                return _NOTION_STATUS_MAP.get(sel["name"].strip().lower(), TaskStatus.to_do)
    return TaskStatus.to_do


# ── Jira helpers ───────────────────────────────────────────────────────────────

def _jira_auth_header(email: str, api_token: str) -> dict:
    raw = f"{email}:{api_token}".encode("utf-8")
    encoded = base64.b64encode(raw).decode("ascii")
    return {"Authorization": f"Basic {encoded}", "Accept": "application/json"}


async def _fetch_jira_issues(base_url: str, email: str, api_token: str, project_key: str, limit: int) -> list[dict]:
    """
    Fetch issues from a Jira Cloud project via JQL search. Raises
    HTTPException on auth/network errors.
    """
    url = f"{base_url}/rest/api/3/search"
    params = {
        "jql": f"project={project_key} ORDER BY created DESC",
        "maxResults": min(max(limit, 1), 100),
        "fields": "summary,description,duedate,assignee,status",
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=_jira_auth_header(email, api_token), params=params)
    except httpx.RequestError as exc:
        logger.error("Jira request failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail="Could not reach Jira. Please try again.")

    if resp.status_code == 401:
        raise HTTPException(status_code=400, detail="Jira rejected the email/API token. Double-check your credentials.")
    if resp.status_code == 404:
        raise HTTPException(status_code=400, detail="Jira project not found. Check the project key and base URL.")
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Jira API error ({resp.status_code}).")

    return resp.json().get("issues", [])


def _adf_to_text(node) -> Optional[str]:
    """
    Jira's v3 API returns descriptions as Atlassian Document Format (a nested
    JSON structure), not plain text. Walk it and pull out the text content.
    """
    if not node:
        return None
    parts: list[str] = []

    def walk(n):
        if isinstance(n, dict):
            if n.get("type") == "text":
                parts.append(n.get("text", ""))
            for child in n.get("content", []) or []:
                walk(child)
            if n.get("type") in ("paragraph", "heading"):
                parts.append("\n")
        elif isinstance(n, list):
            for item in n:
                walk(item)

    walk(node)
    text = "".join(parts).strip()
    return text or None


_JIRA_STATUS_MAP = {
    "done": TaskStatus.completed, "closed": TaskStatus.completed, "resolved": TaskStatus.completed,
    "in progress": TaskStatus.in_progress, "in review": TaskStatus.in_progress,
    "to do": TaskStatus.to_do, "open": TaskStatus.to_do, "backlog": TaskStatus.to_do, "selected for development": TaskStatus.to_do,
    "blocked": TaskStatus.pending, "on hold": TaskStatus.pending,
    "cancelled": TaskStatus.cancelled, "canceled": TaskStatus.cancelled, "won't do": TaskStatus.cancelled,
}


def _jira_status(status_name: Optional[str]) -> TaskStatus:
    if not status_name:
        return TaskStatus.to_do
    return _JIRA_STATUS_MAP.get(status_name.strip().lower(), TaskStatus.to_do)


# ── Final Endpoints ───────────────────────────────────────────────────────────

@router.post("/trello/import", response_model=IntegrationImportResponse)
async def import_from_trello(
    payload: IntegrationImportRequest,
    current_user=Depends(get_current_user_wrapper),
    db: Session = Depends(get_db),
):
    """
    Pull cards from a Trello list and create them as tasks on the board.
    Cards already imported previously are skipped, not duplicated.
    """
    _require_architect(current_user)
    workspace_id = _require_workspace(current_user)

    cfg = crud.get_integration_config(db, workspace_id)
    api_key = cfg.get("trello_api_key")
    token = cfg.get("trello_token")
    list_id = payload.source_id or cfg.get("trello_list_id")

    if not api_key or not token:
        raise HTTPException(status_code=400, detail="Trello isn't configured yet. Save your API key and token first.")
    if not list_id:
        raise HTTPException(status_code=400, detail="No Trello list ID configured. Save one or pass source_id.")

    cards = await _fetch_trello_cards(api_key, token, list_id, payload.limit or 50)

    results: list[ImportedTaskResult] = []
    imported = skipped = failed = 0

    for card in cards:
        card_id = card.get("id")
        title = (card.get("name") or "").strip()

        if not card_id or not title:
            failed += 1
            results.append(ImportedTaskResult(
                external_id=card_id or "unknown", title=title or "(untitled)",
                imported=False, error="Card missing an ID or name.",
            ))
            continue

        existing = crud.find_imported_task(db, workspace_id, "trello", card_id)
        if existing:
            skipped += 1
            results.append(ImportedTaskResult(
                external_id=card_id, title=title, imported=False,
                task_id=existing.id, skipped_reason="already imported",
            ))
            continue

        try:
            task = crud.create_task_from_import(
                db=db,
                workspace_id=workspace_id,
                service="trello",
                external_id=card_id,
                title=title,
                description=card.get("desc") or None,
                deadline=card.get("due") or None,
                priority=Priority.medium,
                status=TaskStatus.completed if card.get("dueComplete") else TaskStatus.to_do,
            )
            imported += 1
            results.append(ImportedTaskResult(
                external_id=card_id, title=title, imported=True, task_id=task.id,
            ))
        except Exception as exc:
            db.rollback()
            logger.error("Failed to import Trello card %s: %s", card_id, exc, exc_info=True)
            failed += 1
            results.append(ImportedTaskResult(
                external_id=card_id, title=title, imported=False, error="Could not save task.",
            ))

    return IntegrationImportResponse(
        integration="trello",
        total_found=len(cards),
        imported=imported,
        skipped=skipped,
        failed=failed,
        results=results,
    )


@router.post("/notion/import", response_model=IntegrationImportResponse)
async def import_from_notion(
    payload: IntegrationImportRequest,
    current_user=Depends(get_current_user_wrapper),
    db: Session = Depends(get_db),
):
    """
    Pull pages from a Notion database and create them as tasks on the board.
    Pages already imported previously are skipped, not duplicated.
    Property names are matched by type (title/date/people/status/select), so
    this works regardless of how the Notion database's columns are named.
    """
    _require_architect(current_user)
    workspace_id = _require_workspace(current_user)

    cfg = crud.get_integration_config(db, workspace_id)
    token = cfg.get("notion_token")
    database_id = payload.source_id or cfg.get("notion_database_id")

    if not token:
        raise HTTPException(status_code=400, detail="Notion isn't configured yet. Save your integration token first.")
    if not database_id:
        raise HTTPException(status_code=400, detail="No Notion database ID configured. Save one or pass source_id.")

    pages = await _fetch_notion_pages(token, database_id, payload.limit or 50)

    results: list[ImportedTaskResult] = []
    imported = skipped = failed = 0

    for page in pages:
        page_id = page.get("id")
        props = page.get("properties", {}) or {}
        title = _notion_title(props)

        if not page_id or not title:
            failed += 1
            results.append(ImportedTaskResult(
                external_id=page_id or "unknown", title=title or "(untitled)",
                imported=False, error="Page missing an ID or title property.",
            ))
            continue

        existing = crud.find_imported_task(db, workspace_id, "notion", page_id)
        if existing:
            skipped += 1
            results.append(ImportedTaskResult(
                external_id=page_id, title=title, imported=False,
                task_id=existing.id, skipped_reason="already imported",
            ))
            continue

        try:
            task = crud.create_task_from_import(
                db=db,
                workspace_id=workspace_id,
                service="notion",
                external_id=page_id,
                title=title,
                description=_notion_rich_text(props, ("description", "notes", "details")),
                deadline=_notion_date(props),
                assignee=_notion_assignee(props),
                priority=Priority.medium,
                status=_notion_status(props),
            )
            imported += 1
            results.append(ImportedTaskResult(
                external_id=page_id, title=title, imported=True, task_id=task.id,
            ))
        except Exception as exc:
            db.rollback()
            logger.error("Failed to import Notion page %s: %s", page_id, exc, exc_info=True)
            failed += 1
            results.append(ImportedTaskResult(
                external_id=page_id, title=title, imported=False, error="Could not save task.",
            ))

    return IntegrationImportResponse(
        integration="notion",
        total_found=len(pages),
        imported=imported,
        skipped=skipped,
        failed=failed,
        results=results,
    )


@router.post("/jira/import", response_model=IntegrationImportResponse)
async def import_from_jira(
    payload: IntegrationImportRequest,
    current_user=Depends(get_current_user_wrapper),
    db: Session = Depends(get_db),
):
    """
    Pull issues from a Jira Cloud project and create them as tasks on the
    board. Issues already imported previously are skipped, not duplicated.
    """
    _require_architect(current_user)
    workspace_id = _require_workspace(current_user)

    cfg = crud.get_integration_config(db, workspace_id)
    base_url = cfg.get("jira_base_url")
    email = cfg.get("jira_email")
    api_token = cfg.get("jira_api_token")
    project_key = payload.source_id or cfg.get("jira_project_key")

    if not base_url or not email or not api_token:
        raise HTTPException(status_code=400, detail="Jira isn't configured yet. Save your base URL, email, and API token first.")
    if not project_key:
        raise HTTPException(status_code=400, detail="No Jira project key configured. Save one or pass source_id.")

    issues = await _fetch_jira_issues(base_url, email, api_token, project_key, payload.limit or 50)

    results: list[ImportedTaskResult] = []
    imported = skipped = failed = 0

    for issue in issues:
        external_id = issue.get("key") or issue.get("id")
        fields = issue.get("fields", {}) or {}
        title = (fields.get("summary") or "").strip()

        if not external_id or not title:
            failed += 1
            results.append(ImportedTaskResult(
                external_id=external_id or "unknown", title=title or "(untitled)",
                imported=False, error="Issue missing a key or summary.",
            ))
            continue

        existing = crud.find_imported_task(db, workspace_id, "jira", external_id)
        if existing:
            skipped += 1
            results.append(ImportedTaskResult(
                external_id=external_id, title=title, imported=False,
                task_id=existing.id, skipped_reason="already imported",
            ))
            continue

        assignee_field = fields.get("assignee") or {}
        status_field = fields.get("status") or {}

        try:
            task = crud.create_task_from_import(
                db=db,
                workspace_id=workspace_id,
                service="jira",
                external_id=external_id,
                title=title,
                description=_adf_to_text(fields.get("description")),
                deadline=fields.get("duedate"),
                assignee=assignee_field.get("displayName"),
                priority=Priority.medium,
                status=_jira_status(status_field.get("name")),
            )
            imported += 1
            results.append(ImportedTaskResult(
                external_id=external_id, title=title, imported=True, task_id=task.id,
            ))
        except Exception as exc:
            db.rollback()
            logger.error("Failed to import Jira issue %s: %s", external_id, exc, exc_info=True)
            failed += 1
            results.append(ImportedTaskResult(
                external_id=external_id, title=title, imported=False, error="Could not save task.",
            ))

    return IntegrationImportResponse(
        integration="jira",
        total_found=len(issues),
        imported=imported,
        skipped=skipped,
        failed=failed,
        results=results,
    )


@router.get("/status")
async def get_status(
    current_user=Depends(get_current_user_wrapper),
    db: Session = Depends(get_db)
):
    workspace_id = _require_workspace(current_user)
    cfg = crud.get_integration_config(db, workspace_id)
    return {
        "notion_configured": bool(cfg.get("notion_token") and cfg.get("notion_database_id")),
        "jira_configured": bool(cfg.get("jira_api_token") and cfg.get("jira_base_url") and cfg.get("jira_project_key")),
        "trello_configured": bool(cfg.get("trello_token") and cfg.get("trello_api_key") and cfg.get("trello_list_id")),
    }


@router.put("/config")
async def update_config(
    payload: IntegrationConfig,
    current_user=Depends(get_current_user_wrapper),
    db: Session = Depends(get_db),
):
    """
    Save (merge) integration credentials for the current user's workspace.
    Only Architects can manage integration credentials, since they're
    workspace-wide secrets. Blank fields are ignored, not saved.
    """
    _require_architect(current_user)
    workspace_id = _require_workspace(current_user)

    incoming = payload.model_dump(exclude_none=True)
    if not incoming:
        raise HTTPException(status_code=400, detail="No credential fields supplied.")

    cfg = crud.save_integration_config(db, workspace_id, incoming)
    return {
        "notion_configured": bool(cfg.get("notion_token") and cfg.get("notion_database_id")),
        "jira_configured": bool(cfg.get("jira_api_token") and cfg.get("jira_base_url") and cfg.get("jira_project_key")),
        "trello_configured": bool(cfg.get("trello_token") and cfg.get("trello_api_key") and cfg.get("trello_list_id")),
    }

# All three import integrations (Trello / Notion / Jira) are complete. Frontend UI update pending.
