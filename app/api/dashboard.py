"""Operations dashboard (Step 13.8): one combined read-only endpoint plus a static page that reads it.

GET /workspaces/{id}/monitoring/overview?window_seconds=...   summary + health + alerts in one response (audit:read).
GET /dashboard                                               the static page. It contains no data and no secrets; the browser sends the user's
                                                             own bearer token to the overview endpoint, so access control is the API's.
The page is three fixed files (no framework, no build, no external requests) served with a strict CSP: scripts and styles only from this origin,
no inline script, no framing. Assets are read from a fixed allowlist, never from a request path.
"""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.identity.context import WorkspaceContext, require_permission
from app.monitoring.alerts import AlertReport, evaluate
from app.monitoring.health import HealthReport, HealthService
from app.monitoring.service import ALLOWED_WINDOWS, DEFAULT_WINDOW, MonitoringService, MonitoringSummary

ASSET_DIR = Path(__file__).resolve().parent.parent / "monitoring" / "dashboard_assets"
ASSETS = {"index.html": "text/html; charset=utf-8", "dashboard.css": "text/css; charset=utf-8", "dashboard.js": "text/javascript; charset=utf-8"}
HEADERS = {
    "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer", "Cache-Control": "no-store",
}

router = APIRouter(tags=["dashboard"])
overview_router = APIRouter(prefix="/workspaces/{workspace_id}/monitoring", tags=["monitoring"])


class Overview(BaseModel):
    window_seconds: int
    generated_at: str
    summary: MonitoringSummary
    health: HealthReport
    alerts: AlertReport


@overview_router.get("/overview", response_model=Overview)
def overview(window_seconds: int = DEFAULT_WINDOW, ctx: WorkspaceContext = Depends(require_permission("audit:read")),
             db: Session = Depends(get_db)) -> Overview:
    if window_seconds not in ALLOWED_WINDOWS:
        raise HTTPException(422, {"code": "invalid_window", "message": "window_seconds must be 3600, 86400 or 604800"})
    s = MonitoringService(db).summary(ctx.workspace.id, window_seconds)
    h = HealthService(db).report(ctx.workspace.id, window_seconds)
    return Overview(window_seconds=window_seconds, generated_at=h.generated_at, summary=s, health=h, alerts=evaluate(s, h))


def _asset(name: str) -> Response:
    return Response((ASSET_DIR / name).read_bytes(), media_type=ASSETS[name].split(";")[0], headers=HEADERS)


@router.get("/dashboard", include_in_schema=False)
def page() -> Response:
    return _asset("index.html")


@router.get("/dashboard/dashboard.css", include_in_schema=False)
def css() -> Response:
    return _asset("dashboard.css")


@router.get("/dashboard/dashboard.js", include_in_schema=False)
def js() -> Response:
    return _asset("dashboard.js")
