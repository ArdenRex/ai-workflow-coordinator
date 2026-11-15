"""Application factory for Aceden AI OS."""
import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.agents.starter import build_agent_registry
from app.security.throttle import Throttle
from app.api import agent_runs, ai, approvals, auth, capabilities, credentials, dashboard, health, memory, plans, monitoring, policy, workflows, workspaces
from app.config import Settings, get_settings
from app.logging_config import configure_logging, request_id_ctx
from app.runtime import build_runtime

SECURITY_HEADERS = {"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer",
                    "Cache-Control": "no-store", "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'"}

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    registry, connectors = build_runtime(settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        connectors.close()

    app = FastAPI(
        lifespan=lifespan,
        title=settings.app_name,
        version=__version__,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",      # 14.5: the schema lists every route; not public in production
    )

    app.state.tool_registry = registry
    app.state.trusted_proxy_count = settings.trusted_proxy_count
    app.state.auth_throttle = Throttle(max_failures=settings.auth_max_failed_logins, window_seconds=settings.auth_lockout_window_seconds,
                                       max_requests_per_minute=settings.auth_max_requests_per_minute)
    app.state.agent_registry = build_agent_registry(registry)

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        token = request_id_ctx.set(rid)
        try:
            declared = request.headers.get("content-length", "")
            if declared.isdigit() and int(declared) > settings.max_request_bytes:        # 14.1: refuse oversized bodies up front
                response = JSONResponse(status_code=413, content={"detail": "Request too large"})
            else:
                response = await call_next(request)
        finally:
            request_id_ctx.reset(token)
        response.headers["x-request-id"] = rid
        for name, value in SECURITY_HEADERS.items():       # 14.1: defaults for every response; a route may set its own stricter value
            if name == "Content-Security-Policy" and request.url.path.startswith("/docs"):
                continue                                    # Swagger UI (development only) needs scripts; docs are off in production
            response.headers.setdefault(name, value)
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_failed(request: Request, exc: RequestValidationError):
        # 14.4: the default 422 echoes the submitted input, which can be a password or a credential secret. Return where and why only.
        errors = [{"loc": list(e.get("loc", ())), "msg": str(e.get("msg", "Invalid value")), "type": str(e.get("type", "value_error"))}
                  for e in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": errors})

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        # Never leak internals to clients; details go to logs only.
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(workspaces.router)
    app.include_router(credentials.router)
    app.include_router(ai.router)
    app.include_router(agent_runs.router)
    app.include_router(plans.router)
    app.include_router(approvals.router)
    app.include_router(memory.router)
    app.include_router(workflows.router)
    app.include_router(capabilities.router)
    app.include_router(policy.router)
    app.include_router(monitoring.router)
    app.include_router(dashboard.overview_router)
    app.include_router(dashboard.router)
    return app


app = create_app()
