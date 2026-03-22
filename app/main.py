"""
main.py
────────
FastAPI application entry point.
Run with: uvicorn app.main:app --reload
"""

import logging
import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.database import engine, Base
from app.routers import messages, tasks, slack

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

VERSION = "0.2.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up — creating database tables if they don't exist...")
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Database ready.")
    except Exception as exc:
        logger.critical("Database initialization failed: %s", exc, exc_info=True)
        sys.exit(1)
    yield
    logger.info("Shutting down.")


app = FastAPI(
    title="AI Workflow Coordinator",
    description=(
        "MVP SaaS that reads Slack/email messages, extracts tasks with AI, "
        "assigns them, and tracks them in a database."
    ),
    version=VERSION,
    lifespan=lifespan,
)

# ─── CORS ─────────────────────────────────────────────────────────────────────
# WARNING: allow_origins=["*"] with allow_credentials=True is rejected by
# browsers per the CORS spec. Credentials require an explicit origin list.
# Set ALLOWED_ORIGINS in your environment for production.
import os

_raw_origins = os.getenv("ALLOWED_ORIGINS", "")
ALLOWED_ORIGINS: list[str] = (
    [o.strip() for o in _raw_origins.split(",") if o.strip()]
    if _raw_origins
    else ["*"]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=bool(_raw_origins),   # only True when explicit origins set
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Routers ──────────────────────────────────────────────────────────────────
app.include_router(messages.router)
app.include_router(tasks.router)
app.include_router(slack.router)            # ← Slack Events API endpoint


# ─── Global exception handler ─────────────────────────────────────────────────
@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc: Exception):
    logger.error("Unhandled exception on %s %s: %s", request.method, request.url, exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error. Please try again later."},
    )


# ─── Health ───────────────────────────────────────────────────────────────────
@app.get("/", tags=["Health"])
async def health_check():
    return {"status": "ok", "service": "AI Workflow Coordinator", "version": VERSION}
