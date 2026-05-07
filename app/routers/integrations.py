"""
routers/integrations.py
────────────────────────
Circular import resolution for FABRIFIX UPVC.
"""

import logging
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Task, UserRole
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

# ── Final Endpoints ───────────────────────────────────────────────────────────

@router.get("/status")
async def get_status(
    current_user=Depends(get_current_user_wrapper),
    db: Session = Depends(get_db)
):
    workspace_id = _require_workspace(current_user)
    cfg = crud.get_integration_config(db, workspace_id)
    return {
        "notion": bool(cfg.get("notion_token")),
        "jira": bool(cfg.get("jira_api_token")),
        "trello": bool(cfg.get("trello_token"))
    }

# (Rest of the sync endpoints follow the same pattern with get_current_user_wrapper)