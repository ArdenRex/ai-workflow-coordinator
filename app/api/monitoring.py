"""Workspace monitoring endpoint (Step 13.1). Read-only, humans only, content-free.

GET /workspaces/{id}/monitoring/summary?window_seconds=3600|86400|604800   what ran, what failed, what is waiting (default one day).
GET /workspaces/{id}/monitoring/health?window_seconds=...                  connection health, agent runs and workflow runs (13.2).
GET /workspaces/{id}/monitoring/alerts?window_seconds=...                  which fixed alert rules are firing now (13.7).
Needs `audit:read` (admin and owner). Another workspace's data is never included; errors are fixed text.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.identity.context import WorkspaceContext, require_permission
from app.monitoring.alerts import AlertReport, AlertService
from app.monitoring.health import HealthReport, HealthService
from app.monitoring.service import ALLOWED_WINDOWS, DEFAULT_WINDOW, MonitoringService, MonitoringSummary

router = APIRouter(prefix="/workspaces/{workspace_id}/monitoring", tags=["monitoring"])


@router.get("/summary", response_model=MonitoringSummary)
def summary(window_seconds: int = DEFAULT_WINDOW, ctx: WorkspaceContext = Depends(require_permission("audit:read")),
            db: Session = Depends(get_db)) -> MonitoringSummary:
    if window_seconds not in ALLOWED_WINDOWS:
        raise HTTPException(422, {"code": "invalid_window", "message": "window_seconds must be 3600, 86400 or 604800"})
    return MonitoringService(db).summary(ctx.workspace.id, window_seconds)


@router.get("/health", response_model=HealthReport)
def health(window_seconds: int = DEFAULT_WINDOW, ctx: WorkspaceContext = Depends(require_permission("audit:read")),
           db: Session = Depends(get_db)) -> HealthReport:
    if window_seconds not in ALLOWED_WINDOWS:
        raise HTTPException(422, {"code": "invalid_window", "message": "window_seconds must be 3600, 86400 or 604800"})
    return HealthService(db).report(ctx.workspace.id, window_seconds)


@router.get("/alerts", response_model=AlertReport)
def alerts(window_seconds: int = DEFAULT_WINDOW, ctx: WorkspaceContext = Depends(require_permission("audit:read")),
           db: Session = Depends(get_db)) -> AlertReport:
    if window_seconds not in ALLOWED_WINDOWS:
        raise HTTPException(422, {"code": "invalid_window", "message": "window_seconds must be 3600, 86400 or 604800"})
    return AlertService(db).report(ctx.workspace.id, window_seconds)
