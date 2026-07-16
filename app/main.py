"""
main.py
────────
FastAPI application entry point.

Slack bot logic lives entirely in app/slack_bot.py.
This file only wires up FastAPI, routers, CORS, and the scheduler.

Environment variables required:
    SLACK_BOT_TOKEN        xoxb-…
    SLACK_SIGNING_SECRET   …
    SLACK_CLIENT_ID        …   (used only by /auth/install OAuth button)
    SLACK_CLIENT_SECRET    …   (used only by /auth/slack/callback)
    DATABASE_URL           postgresql://…
    GROQ_API_KEY            …
    APP_SECRET_KEY          …
    BACKEND_URL            https://your-railway-url.railway.app
    FRONTEND_URL           https://your-vercel-url.vercel.app
    ALLOWED_ORIGINS        (optional, comma-separated for CORS)
    SLACK_CHANNEL_ID       (optional, restrict bot to one channel)

Note on the try/except around the imports below: app.database (imported
transitively by nearly every router) builds a pydantic Settings object at
MODULE IMPORT TIME. If a required env var (DATABASE_URL, GROQ_API_KEY,
SLACK_BOT_TOKEN, SLACK_SIGNING_SECRET, APP_SECRET_KEY) is missing on
whichever platform this is deployed to, that import raises a
ValidationError before FastAPI even exists — which used to crash the
entire Python process with no usable HTTP response. On Vercel that showed
up as "Python process exited with exit status: 0" on every single
request, including the health check, with no way to tell what was wrong
short of reading logs. We now catch that here so the process always boots
and instead returns a clear diagnostic over HTTP.
"""

import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

VERSION = "1.5.1"

# ─── Safe import of everything that depends on Settings/env vars ─────────────
_startup_error: Optional[str] = None

try:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy.exc import ProgrammingError, OperationalError

    from app.routers import messages, tasks, slack as slack_router
    from app.routers import auth as auth_router
    from app.routers import workspace_settings as workspace_settings_router
    from app.routers import onboarding as onboarding_router
    from app.routers import integrations as integrations_router
    from app.routers import locale as locale_router
    from app.routers import viral as viral_router
    from app.routers import teams as teams_router
    from app.routers import public_api as public_api_router
    from app.routers import feedback as feedback_router
    from app.routers import billing as billing_router
    from app.routers import admin as admin_router
    from app.routers import referral as referral_router
    from app.routers.tasks import share_router
except Exception as exc:  # pydantic ValidationError, or any other import-time failure
    _startup_error = f"{type(exc).__name__}: {exc}"
    logger.critical(
        "Startup import failed — booting in degraded mode instead of crashing: %s",
        _startup_error,
        exc_info=True,
    )


if _startup_error:
    # ── Degraded-mode app ───────────────────────────────────────────────────
    # The process boots successfully (so Vercel never kills it outright), but
    # every route returns a clear 503 explaining exactly what's missing,
    # instead of a silent process crash with no response at all.
    app = FastAPI(
        title="AI Workflow Coordinator (degraded — config error)",
        version=VERSION,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
    async def _startup_error_handler(full_path: str = ""):
        return JSONResponse(
            status_code=503,
            content={
                "status": "config_error",
                "detail": (
                    "The API failed to start because required configuration is "
                    "missing or invalid. Check this project's Environment "
                    "Variables (Production) for: DATABASE_URL, GROQ_API_KEY, "
                    "SLACK_BOT_TOKEN, SLACK_SIGNING_SECRET, APP_SECRET_KEY."
                ),
                "error": _startup_error,
            },
        )

else:
    # ── Normal app (all imports succeeded) ──────────────────────────────────

    # ─── Helpers ────────────────────────────────────────────────────────────
    _BENIGN_MARKERS = (
        "already exists",
        "duplicatetable",
        "duplicate_table",
        "duplicatecolumn",
        "duplicateindex",
        "duplicate key value violates unique constraint",
    )

    def _is_benign_race_error(exc: Exception) -> bool:
        """
        True if this looks like a "someone else already created/stamped it" race
        from multiple cold-start instances running migrations at once —
        i.e. the schema is actually fine, not a real failure.
        """
        message = str(exc).lower()
        return any(marker in message for marker in _BENIGN_MARKERS)

    # Repo root — app/main.py -> app/ -> repo root, where alembic.ini and alembic/ live.
    _BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def _run_alembic_upgrade() -> None:
        """
        Run all Alembic migrations up to head.

        This replaces the old Base.metadata.create_all() approach. create_all()
        only ever builds tables that don't exist yet — it never applies later
        migrations (e.g. add_freelancer_slug), and on Vercel there's no
        persistent start command (unlike render.yaml's
        'alembic upgrade head && uvicorn ...') to run migrations once per
        deploy. Running this on every cold start is safe: Alembic tracks the
        applied revision in the alembic_version table, so if the schema is
        already current this is a fast no-op.
        """
        alembic_cfg = Config(os.path.join(_BASE_DIR, "alembic.ini"))
        alembic_cfg.set_main_option("script_location", os.path.join(_BASE_DIR, "alembic"))
        command.upgrade(alembic_cfg, "head")

    # ─── FastAPI lifespan ───────────────────────────────────────────────────
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("Starting up — running Alembic migrations (upgrade head)…")
        try:
            _run_alembic_upgrade()
            logger.info("Database schema is up to date.")
        except (ProgrammingError, OperationalError) as exc:
            if _is_benign_race_error(exc):
                logger.warning(
                    "Database objects already exist/stamped (likely a cold-start "
                    "race between parallel instances) — continuing startup: %s", exc
                )
            else:
                # NOTE: no sys.exit() here. Exiting the process on a migration
                # failure is exactly what produced the opaque
                # "Python process exited" crashes — better to boot, log loudly,
                # and let individual DB-touching requests fail with a real
                # error message than to kill the whole app over a migration
                # hiccup (which may be transient, e.g. a cold DB pooler).
                logger.critical("Database migration failed: %s", exc, exc_info=True)
        except Exception as exc:
            if _is_benign_race_error(exc):
                logger.warning(
                    "Database objects already exist/stamped (likely a cold-start "
                    "race between parallel instances) — continuing startup: %s", exc
                )
            else:
                logger.critical("Database migration failed: %s", exc, exc_info=True)

        yield

        logger.info("Shutting down.")

    # ─── FastAPI app ────────────────────────────────────────────────────────
    app = FastAPI(
        title       = "AI Workflow Coordinator",
        description = (
            "MVP SaaS that reads Slack messages, extracts tasks with AI, "
            "assigns them, and tracks them in a database."
        ),
        version  = VERSION,
        lifespan = lifespan,
    )

    # ── CORS ─────────────────────────────────────────────────────────────────
    _raw_origins = os.getenv("ALLOWED_ORIGINS", "")
    _extra       = [o.strip() for o in _raw_origins.split(",") if o.strip()]
    _frontend    = os.getenv("FRONTEND_URL", "").strip().rstrip("/")
    _backend     = os.getenv("BACKEND_URL",  "").strip().rstrip("/")

    ALLOWED_ORIGINS = list(filter(None, [_frontend, _backend, *_extra]))
    logger.info("CORS allowed origins (informational only, allow_origins=* below): %s", ALLOWED_ORIGINS)

    app.add_middleware(
        CORSMiddleware,
        allow_origins     = ["*"],
        allow_credentials = False,
        allow_methods     = ["*"],
        allow_headers     = ["*"],
    )

    # ── Routers ──────────────────────────────────────────────────────────────
    app.include_router(auth_router.router)                  # /auth/*
    app.include_router(messages.router)
    app.include_router(tasks.router)                        # /tasks/*
    app.include_router(share_router)                        # /share/{token}
    app.include_router(slack_router.router)                 # /slack/events + OAuth
    app.include_router(workspace_settings_router.router)    # /workspace/settings
    app.include_router(onboarding_router.router)            # /onboarding/*
    app.include_router(integrations_router.router)          # /integrations/*
    app.include_router(locale_router.router)                # /locale/*
    app.include_router(viral_router.router)                 # /viral/*
    app.include_router(teams_router.router)                 # /teams/*
    app.include_router(public_api_router.router)            # /api/v1/*
    app.include_router(feedback_router.router)              # /feedback/*
    app.include_router(billing_router.router)               # /billing/*
    app.include_router(admin_router.router)                 # /admin/*
    app.include_router(referral_router.router)              # /referral/*

    # ── Global exception handler ────────────────────────────────────────────
    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.error(
            "Unhandled exception on %s %s: %s",
            request.method, request.url, exc,
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error. Please try again later."},
        )

    # ── Health ───────────────────────────────────────────────────────────────
    @app.get("/", tags=["Health"])
    async def health_check():
        return {"status": "ok", "service": "AI Workflow Coordinator", "version": VERSION}
