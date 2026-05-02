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
    BACKEND_URL            https://your-railway-url.railway.app
    FRONTEND_URL           https://your-vercel-url.vercel.app
    ALLOWED_ORIGINS        (optional, comma-separated for CORS)
    SLACK_CHANNEL_ID       (optional, restrict bot to one channel)
"""

import logging
import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.database import engine, Base
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
from app.routers.tasks import share_router
from app.scheduler import start_scheduler, stop_scheduler

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

VERSION = "1.5.0"

# ─── FastAPI lifespan ─────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up — creating database tables if they don't exist…")
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Database ready.")
    except Exception as exc:
        logger.critical("Database initialization failed: %s", exc, exc_info=True)
        sys.exit(1)

    start_scheduler()
    logger.info("Scheduler started.")

    yield

    stop_scheduler()
    logger.info("Shutting down.")


# ─── FastAPI app ──────────────────────────────────────────────────────────────
app = FastAPI(
    title       = "AI Workflow Coordinator",
    description = (
        "MVP SaaS that reads Slack messages, extracts tasks with AI, "
        "assigns them, and tracks them in a database."
    ),
    version  = VERSION,
    lifespan = lifespan,
)

# ── CORS ───────────────────────────────────────────────────────────────────────
_raw_origins = os.getenv("ALLOWED_ORIGINS", "")
_extra       = [o.strip() for o in _raw_origins.split(",") if o.strip()]
_frontend    = os.getenv("FRONTEND_URL", "").strip().rstrip("/")
_backend     = os.getenv("BACKEND_URL",  "").strip().rstrip("/")

ALLOWED_ORIGINS: list[str] = list(filter(None, [_frontend, _backend, *_extra]))
logger.info("CORS allowed origins: %s", ALLOWED_ORIGINS)

app.add_middleware(
    CORSMiddleware,
    allow_origins     = ["*"],
    allow_credentials = False,
    allow_methods     = ["*"],
    allow_headers     = ["*"],
)

# ── Routers ────────────────────────────────────────────────────────────────────
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


# ── Global exception handler ───────────────────────────────────────────────────
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


# ── Health ─────────────────────────────────────────────────────────────────────
@app.get("/", tags=["Health"])
async def health_check():
    return {"status": "ok", "service": "AI Workflow Coordinator", "version": VERSION}
