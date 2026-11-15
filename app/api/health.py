"""Liveness endpoint. No business data, no secrets."""
from fastapi import APIRouter

from app import __version__
from app.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    """Liveness: the process is up."""
    s = get_settings()
    if s.is_production:                          # 14.5: an anonymous caller learns liveness only, not the version or environment
        return {"status": "ok", "service": s.app_name}
    return {"status": "ok", "service": s.app_name, "version": __version__, "env": s.app_env}


@router.get("/ready")
def ready():
    """Readiness: dependencies (database) are reachable."""
    from fastapi.responses import JSONResponse

    from app.database import check_database

    ok = check_database()
    return JSONResponse(status_code=200 if ok else 503,
                        content={"status": "ready" if ok else "unavailable", "database": ok})
