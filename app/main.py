"""
main.py
────────
FastAPI application entry point + Slack Bolt integration.

Run with:
    uvicorn app.main:app --reload

Environment variables required (see .env.example):
    SLACK_BOT_TOKEN        xoxb-…
    SLACK_SIGNING_SECRET   …
    SLACK_CLIENT_ID        …
    SLACK_CLIENT_SECRET    …
    DATABASE_URL           postgresql://…
    BACKEND_URL            https://your-railway-url.railway.app
    FRONTEND_URL           https://your-vercel-url.vercel.app
    ALLOWED_ORIGINS        (optional, comma-separated for CORS)
    SLACK_CHANNEL_ID       (optional, restrict to one channel)
"""

import logging
import os
import re
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from slack_bolt import App as BoltApp
from slack_bolt.adapter.fastapi import SlackRequestHandler

from app.database import engine, Base, SessionLocal
from app.models import Task, TaskStatus
from app.routers import messages, tasks, slack as slack_router
from app.routers import auth as auth_router
from app.routers import workspace_settings as workspace_settings_router
from app.routers import onboarding as onboarding_router          # Segment 7
from app.routers.tasks import share_router                       # ✅ Segment 8: public share route
from app.scheduler import start_scheduler, stop_scheduler        # Segment 3

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

VERSION = "0.9.0"  # bumped for Segment 8

# ─── Slack Bolt app ───────────────────────────────────────────────────────────
bolt_app = BoltApp(
    token=os.environ["SLACK_BOT_TOKEN"],
    signing_secret=os.environ["SLACK_SIGNING_SECRET"],
)
handler = SlackRequestHandler(bolt_app)

_ALLOWED_CHANNEL = os.getenv("SLACK_CHANNEL_ID", "").strip()

# ── Regex patterns ─────────────────────────────────────────────────────────────
_CMD_RE = re.compile(
    r"<@[A-Z0-9]+>\s+create\s+task\s+"
    r"(?:<@(?P<mention>[A-Z0-9]+)>\s+)?"
    r"(?P<title>.+)",
    re.IGNORECASE,
)
_MENTION_RE     = re.compile(r"<@[A-Z0-9]+>\s*", re.IGNORECASE)
_NL_ASSIGNEE_RE = re.compile(r"<@(?P<uid>[A-Z0-9]+)>", re.IGNORECASE)


def _resolve_slack_user(client, user_id: str) -> str:
    try:
        info = client.users_info(user=user_id)
        profile = info["user"].get("profile", {})
        return (
            profile.get("display_name")
            or profile.get("real_name")
            or user_id
        )
    except Exception:
        return user_id


def _task_exists(db, channel_id: str, message_ts: str) -> bool:
    return (
        db.query(Task)
        .filter_by(slack_channel_id=channel_id, slack_message_ts=message_ts)
        .first()
        is not None
    )


@bolt_app.event("app_mention")
def handle_mention(event, say, client, logger):
    channel_id = event.get("channel", "")
    message_ts = event.get("ts", "")
    text       = event.get("text", "")

    if _ALLOWED_CHANNEL and channel_id != _ALLOWED_CHANNEL:
        logger.info("Ignoring message from channel %s (not allowed)", channel_id)
        return

    match = _CMD_RE.search(text)

    if match:
        title         = match.group("title").strip()
        assignee_id   = match.group("mention")
        assignee_name = (
            _resolve_slack_user(client, assignee_id) if assignee_id else None
        )
        mode = "command"
    else:
        body = _MENTION_RE.sub("", text).strip()
        if not body:
            say(
                "Hi! I can create tasks two ways:\n"
                "• *Structured:* `@bot create task [@assignee] <title>`\n"
                "• *Natural language:* `@bot Hey Sarah, finish the report by Friday`"
            )
            return

        title = body
        assignee_match = _NL_ASSIGNEE_RE.search(body)
        if assignee_match:
            assignee_id   = assignee_match.group("uid")
            assignee_name = _resolve_slack_user(client, assignee_id)
            title = _NL_ASSIGNEE_RE.sub("", body).strip()
            title = re.sub(r"\s{2,}", " ", title)
        else:
            assignee_id   = None
            assignee_name = None

        mode = "natural"

    logger.info(
        "Processing task | mode=%s | title=%r | assignee=%r | ts=%s",
        mode, title, assignee_name, message_ts,
    )

    db = SessionLocal()
    try:
        if _task_exists(db, channel_id, message_ts):
            logger.info("Duplicate Slack event ts=%s — skipping", message_ts)
            return

        new_task = Task(
            title            = title,
            task_description = title,
            assignee         = assignee_name,
            assignee_id      = assignee_id,
            source_message   = text,
            slack_channel_id = channel_id,
            slack_message_ts = message_ts,
            status           = TaskStatus.to_do,
        )
        db.add(new_task)
        db.commit()
        db.refresh(new_task)

        # Segment 7 — mark "first_command_sent" onboarding step for the task creator
        # (wire in once Slack users are linked to DB users via owner_id)
        # if new_task.owner_id:
        #     from app.routers.onboarding import mark_step_for_user
        #     mark_step_for_user(db, new_task.owner_id, "first_command_sent")

        confirmation = (
            f"✅ Task *{title}* (id: {new_task.id}) assigned to *{assignee_name}* and added to *To Do*."
            if assignee_name else
            f"✅ Task *{title}* (id: {new_task.id}) added to *To Do* (no assignee)."
        )
        say(confirmation)
        logger.info(
            "Created task id=%s title=%r assignee=%r mode=%s",
            new_task.id, title, assignee_name, mode,
        )

    except Exception as exc:
        db.rollback()
        logger.error("Failed to create task: %s", exc, exc_info=True)
        say(f"⚠️ Sorry, I couldn't create that task. Please try again. (Error: {exc})")
    finally:
        db.close()


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

    start_scheduler()   # Segment 3 — start hourly overdue-ping job
    logger.info("Scheduler started.")

    yield

    stop_scheduler()    # Segment 3 — graceful shutdown
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
_extra = [o.strip() for o in _raw_origins.split(",") if o.strip()]

_frontend = os.getenv("FRONTEND_URL", "").strip().rstrip("/")
_backend  = os.getenv("BACKEND_URL",  "").strip().rstrip("/")

ALLOWED_ORIGINS: list[str] = list(filter(None, [
    _frontend,
    _backend,
    *_extra,
]))

if not ALLOWED_ORIGINS:
    logger.warning(
        "FRONTEND_URL and BACKEND_URL are not set. "
        "CORS will block all credentialed requests. "
        "Set FRONTEND_URL in Railway variables."
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins     = ALLOWED_ORIGINS if ALLOWED_ORIGINS else ["*"],
    allow_credentials = True,
    allow_methods     = ["*"],
    allow_headers     = ["*"],
)

# ── Routers ────────────────────────────────────────────────────────────────────
app.include_router(auth_router.router)                  # /auth/*
app.include_router(messages.router)
app.include_router(tasks.router)                        # /tasks/*
app.include_router(share_router)                        # ✅ Segment 8: GET /share/{token}
app.include_router(slack_router.router)                 # /slack/events + OAuth
app.include_router(workspace_settings_router.router)    # /workspace/settings
app.include_router(onboarding_router.router)            # /onboarding/*  (Segment 7)


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
