"""
main.py
────────
FastAPI application entry point + Slack Bolt integration.

Run with:
    uvicorn app.main:app --reload

Environment variables required (see .env.example):
    SLACK_BOT_TOKEN        xoxb-…
    SLACK_SIGNING_SECRET   …
    DATABASE_URL           postgresql://…
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

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

VERSION = "0.3.0"

# ─── Slack Bolt app ───────────────────────────────────────────────────────────
bolt_app = BoltApp(
    token=os.environ["SLACK_BOT_TOKEN"],
    signing_secret=os.environ["SLACK_SIGNING_SECRET"],
)
handler = SlackRequestHandler(bolt_app)

# Optional: restrict bot to one channel
_ALLOWED_CHANNEL = os.getenv("SLACK_CHANNEL_ID", "").strip()

# ── Regex patterns ─────────────────────────────────────────────────────────────
# Matches:  @bot create task <title>
#           @bot create task @ali Finish sales report
_CMD_RE = re.compile(
    r"<@[A-Z0-9]+>\s+create\s+task\s+"   # mention + "create task "
    r"(?:<@(?P<mention>[A-Z0-9]+)>\s+)?"  # optional @assignee mention
    r"(?P<title>.+)",                      # task title (rest of message)
    re.IGNORECASE,
)


def _resolve_slack_user(client, user_id: str) -> str:
    """Return display name for a Slack user ID, fallback to raw ID."""
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
    """Idempotency check — True if this Slack message was already processed."""
    return (
        db.query(Task)
        .filter_by(slack_channel_id=channel_id, slack_message_ts=message_ts)
        .first()
        is not None
    )


@bolt_app.event("app_mention")
def handle_mention(event, say, client, logger):
    """
    Listens for:  @bot create task [@assignee] <title>
    """
    channel_id = event.get("channel", "")
    message_ts = event.get("ts", "")
    text       = event.get("text", "")

    # Optional channel restriction
    if _ALLOWED_CHANNEL and channel_id != _ALLOWED_CHANNEL:
        logger.info("Ignoring message from channel %s (not allowed)", channel_id)
        return

    match = _CMD_RE.search(text)
    if not match:
        say("Sorry, I didn't understand that. Try: `@bot create task <title>`")
        return

    title          = match.group("title").strip()
    assignee_id    = match.group("mention")          # Slack user ID or None
    assignee_name  = None

    if assignee_id:
        assignee_name = _resolve_slack_user(client, assignee_id)

    db = SessionLocal()
    try:
        # ── Idempotency guard ──────────────────────────────────────────────
        if _task_exists(db, channel_id, message_ts):
            logger.info("Duplicate Slack event ts=%s — skipping", message_ts)
            return

        # ── Insert task ────────────────────────────────────────────────────
        new_task = Task(
            title            = title,
            task_description = title,          # keep legacy column in sync
            assignee         = assignee_name,
            assignee_id      = assignee_id,
            source_message   = text,
            slack_channel_id = channel_id,
            slack_message_ts = message_ts,
            status           = TaskStatus.to_do,   # ← always "to_do" from Slack
        )
        db.add(new_task)
        db.commit()
        db.refresh(new_task)

        # ── Confirmation message ────────────────────────────────────────────
        if assignee_name:
            confirmation = (
                f"✅ Task *{title}* (id: {new_task.id}) "
                f"assigned to *{assignee_name}* and added to *To Do*."
            )
        else:
            confirmation = (
                f"✅ Task *{title}* (id: {new_task.id}) "
                f"added to *To Do* (no assignee)."
            )
        say(confirmation)
        logger.info("Created task id=%s title=%r assignee=%r", new_task.id, title, assignee_name)

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
    yield
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
ALLOWED_ORIGINS: list[str] = (
    [o.strip() for o in _raw_origins.split(",") if o.strip()]
    if _raw_origins
    else ["*"]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins     = ALLOWED_ORIGINS,
    allow_credentials = bool(_raw_origins),
    allow_methods     = ["*"],
    allow_headers     = ["*"],
)

# ── Routers ────────────────────────────────────────────────────────────────────
app.include_router(messages.router)
app.include_router(tasks.router)
app.include_router(slack_router.router)   # url_verification + legacy webhook


# ── Slack Events endpoint (Bolt) ───────────────────────────────────────────────
@app.post("/slack/events")
async def slack_events(req: Request):
    """Receives all Slack Events API payloads and dispatches via Bolt."""
    return await handler.handle(req)


# ── Global exception handler ───────────────────────────────────────────────────
@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc: Exception):
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
