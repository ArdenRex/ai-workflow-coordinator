"""
main.py
────────
FastAPI application entry point.
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
from app.routers import referral as referral_router
from app.routers.tasks import share_router
from app.scheduler import start_scheduler, stop_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

VERSION = "1.5.0"

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up...")
    try:
        Base.metadata.create_all(bind=engine)
    except Exception as exc:
        logger.critical("Database failed: %s", exc)
        sys.exit(1)
    start_scheduler()
    yield
    stop_scheduler()

app = FastAPI(title="AI Workflow Coordinator", version=VERSION, lifespan=lifespan)

# ── CORS ───────────────────────────────────────────────────────────────────────
_frontend = os.getenv("FRONTEND_URL", "").strip().rstrip("/")
_backend  = os.getenv("BACKEND_URL", "").strip().rstrip("/")
_raw_origins = os.getenv("ALLOWED_ORIGINS", "")
_extra = [o.strip() for o in _raw_origins.split(",") if o.strip()]

ALLOWED_ORIGINS = list(filter(None, [_frontend, _backend, *_extra]))

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS if ALLOWED_ORIGINS else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ────────────────────────────────────────────────────────────────────
app.include_router(auth_router.router)
app.include_router(messages.router)
app.include_router(tasks.router)
app.include_router(share_router)
app.include_router(slack_router.router)
app.include_router(workspace_settings_router.router)
app.include_router(onboarding_router.router)
app.include_router(integrations_router.router)
app.include_router(locale_router.router)
app.include_router(viral_router.router)
app.include_router(teams_router.router)
app.include_router(public_api_router.router)
app.include_router(feedback_router.router)
app.include_router(billing_router.router)
app.include_router(admin_router.router)
app.include_router(referral_router.router)

@app.get("/")
async def health_check():
    return {"status": "ok", "version": VERSION}