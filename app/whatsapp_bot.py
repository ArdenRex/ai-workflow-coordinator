"""
whatsapp_bot.py
---------------
WhatsApp Business Connect — the WhatsApp equivalent of gmail_bot.py.

Flow:
  1. A user connects their WhatsApp Business number (Meta Embedded Signup —
     added in a later step). That stores the number's `phone_number_id` on
     their User row.
  2. WhatsApp pushes every message for that number to POST /webhooks/whatsapp
     (routers/whatsapp_router.py, which verifies Meta's signature) and hands
     the payload to handle_webhook_payload() below.
  3. Each text message is run through a FILTER so chit-chat never reaches the
     board. Only a message that is a task — a request, instruction or
     commitment, or work assigned to a named person — becomes a Task.

Why a filter is needed here but not for Gmail: ai_extractor.extract_task_from_message
ALWAYS returns a task for whatever text it is given ("ok thanks" → some task).
That's tolerable for email, but WhatsApp is mostly small talk, so a separate
yes/no gate runs first. Messages that fail the gate are dropped and NOT stored.

The gate has two layers:
  - prefilter():            free, deterministic — drops empty / single-word /
                            pure acknowledgement messages without any AI call.
  - classify_task_intent(): one cheap Groq call returning {"is_task": bool}.
                            Fails CLOSED: if the AI call errors, nothing is
                            created (a missing task is better than board spam).

Idempotency: Meta re-delivers webhooks it thinks failed. Created tasks store
the WhatsApp message id (Task.whatsapp_message_id) and are skipped on repeat;
a small in-memory cache also avoids re-classifying dropped messages.
"""

import asyncio
import json
import logging
import re
import secrets as _secrets
from collections import OrderedDict
from typing import Any, Awaitable, Callable, Iterator, Optional

from app.config import get_settings
from app.models import Priority, Task, TaskStatus, User

logger = logging.getLogger(__name__)

MIN_CONFIDENCE = 0.6          # same threshold gmail_bot uses
# If the AI call fails (rate limit, timeout, brief outage) try again after these
# pauses — 3 attempts in all. WhatsApp has already been told "received", so
# without this a message hit by a hiccup would be lost for good. (A server
# restart in the middle of a retry still loses that one message.)
RETRY_DELAYS = (2.0, 8.0)
MAX_GATE_CHARS = 1500         # WhatsApp messages can be long; the gate only needs the start

# ── Layer 1: deterministic prefilter ─────────────────────────────────────────

# Words that, on their own or in any combination, are never a task.
_ACK_WORDS = {
    "ok", "okay", "okk", "k", "kk", "thanks", "thank", "you", "thankyou", "thx", "ty",
    "hi", "hello", "hey", "salam", "assalamualaikum", "walaikum", "assalam", "walaikumassalam",
    "yes", "no", "yep", "yup", "nope", "noted", "done", "lol", "haha", "hahaha", "hmm",
    "sure", "fine", "cool", "great", "nice", "good", "welcome", "bye", "gm", "gn",
    "morning", "night", "ji", "haan", "han", "nahi", "shukriya", "jazakallah", "please",
    "sir", "bhai", "sis", "alright", "right", "got", "it", "np", "pls",
}
_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)   # letters only (any script)


def prefilter(text: str) -> tuple[bool, str]:
    """Return (worth_classifying, reason_if_not). No AI, no network."""
    if not text or not text.strip():
        return False, "empty"
    words = _WORD_RE.findall(text.lower())
    if not words:
        return False, "no letters (emoji/numbers only)"
    if len(words) < 2:
        return False, "single word"
    if all(w in _ACK_WORDS for w in words):
        return False, "acknowledgement/greeting"
    return True, ""


# ── Layer 2: AI yes/no gate ──────────────────────────────────────────────────

GATE_PROMPT = """You decide whether ONE WhatsApp message belongs on a team task board.

Return ONLY valid JSON: {"is_task": true} or {"is_task": false}

is_task = true when the message:
- asks someone to do something, gives an instruction, or lists a to-do
  (e.g. "send me the invoice by Friday", "can you review the contract?"), OR
- assigns work to a named person
  (e.g. "Ali will handle the redesign", "Sara - fix the login bug"), OR
- records a concrete commitment someone made to do something.

is_task = false for greetings, thanks, acknowledgements, small talk, jokes,
forwarded news, questions that only ask for information, status chatter with
no new work ("ok", "done", "on my way"), and anything without a concrete action.

When unsure, return {"is_task": false}."""


async def classify_task_intent(text: str) -> bool:
    """Ask Groq whether `text` is a task. Raises on API failure (caller fails closed)."""
    # Imported lazily so importing this module (and its tests) never needs Groq.
    from app.ai_extractor import _MODEL, _get_client

    response = await _get_client().chat.completions.create(
        model=_MODEL,
        temperature=0,
        max_tokens=20,
        messages=[
            {"role": "system", "content": GATE_PROMPT},
            {"role": "user", "content": f"Message:\n\n{text[:MAX_GATE_CHARS]}"},
        ],
    )
    raw = (response.choices[0].message.content or "").strip()
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError(f"Gate returned no JSON: {raw!r}")
    data = json.loads(match.group(0))
    return data.get("is_task") is True


# ── Webhook payload parsing ──────────────────────────────────────────────────

def iter_text_messages(payload: dict) -> Iterator[dict]:
    """
    Yield one dict per TEXT message in a Meta webhook payload:
      {phone_number_id, message_id, text, sender_name, direction}

    direction is "inbound" (someone messaged the business number) or
    "outbound" (the business owner sent it from their WhatsApp Business app —
    delivered as `smb_message_echoes` for coexistence numbers). Non-text
    messages (images, voice, reactions…) and status updates are skipped.
    """
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            field = change.get("field")
            value = change.get("value") or {}
            phone_number_id = (value.get("metadata") or {}).get("phone_number_id")
            if not phone_number_id:
                continue

            if field == "messages":
                names = {
                    c.get("wa_id"): (c.get("profile") or {}).get("name")
                    for c in value.get("contacts") or []
                }
                for m in value.get("messages") or []:
                    if m.get("type") != "text":
                        continue
                    body = (m.get("text") or {}).get("body")
                    if not body or not m.get("id"):
                        continue
                    yield {
                        "phone_number_id": phone_number_id,
                        "message_id": m["id"],
                        "text": body,
                        "sender_name": names.get(m.get("from")),
                        "direction": "inbound",
                    }

            elif field == "smb_message_echoes":
                for m in value.get("message_echoes") or []:
                    if m.get("type") != "text":
                        continue
                    body = (m.get("text") or {}).get("body")
                    if not body or not m.get("id"):
                        continue
                    yield {
                        "phone_number_id": phone_number_id,
                        "message_id": m["id"],
                        "text": body,
                        "sender_name": None,
                        "direction": "outbound",
                    }


# ── Core processing ──────────────────────────────────────────────────────────

async def _with_retry(fn: Callable[[str], Awaitable[Any]], text: str,
                      sleep: Callable[[float], Awaitable[None]], stats: dict) -> Any:
    """Call fn(text); on an exception wait and retry per RETRY_DELAYS, then re-raise."""
    for delay in (*RETRY_DELAYS, None):
        try:
            return await fn(text)
        except Exception as exc:
            if delay is None:
                raise
            stats["retries"] += 1
            logger.warning("WhatsApp AI call failed (%s) — retrying in %.0fs", type(exc).__name__, delay)
            await sleep(delay)


# Recently seen message ids (task or not) so webhook re-deliveries don't cost
# another AI call. Per-process only — the DB check below is the real guarantee
# for messages that became tasks.
_SEEN: "OrderedDict[str, None]" = OrderedDict()
_SEEN_MAX = 2000


def _mark_seen(message_id: str) -> bool:
    """Return True if already seen; otherwise record it and return False."""
    if message_id in _SEEN:
        return True
    _SEEN[message_id] = None
    while len(_SEEN) > _SEEN_MAX:
        _SEEN.popitem(last=False)
    return False


async def handle_webhook_payload(
    payload: dict,
    *,
    session_factory: Optional[Callable[[], Any]] = None,
    classify: Callable[[str], Awaitable[bool]] = classify_task_intent,
    extract: Optional[Callable[[str], Awaitable[Any]]] = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> dict:
    """
    Process one Meta webhook payload. Never raises — the webhook has already
    answered 200 by the time this runs in the background. Returns a stats dict.

    `session_factory`, `classify` and `extract` are injectable so the pipeline
    can be tested without a real database or AI.
    """
    if session_factory is None:
        from app.database import SessionLocal
        session_factory = SessionLocal
    if extract is None:
        from app.ai_extractor import extract_task_from_message
        extract = extract_task_from_message

    stats = {"messages": 0, "created": 0, "skipped_duplicate": 0,
             "skipped_prefilter": 0, "skipped_not_task": 0,
             "skipped_low_confidence": 0, "skipped_no_user": 0,
             "skipped_billing": 0, "retries": 0, "errors": 0}

    db = session_factory()
    try:
        for msg in iter_text_messages(payload):
            stats["messages"] += 1
            mid = msg["message_id"]
            try:
                if _mark_seen(mid) or db.query(Task.id).filter(Task.whatsapp_message_id == mid).first():
                    stats["skipped_duplicate"] += 1
                    continue

                ok, reason = prefilter(msg["text"])
                if not ok:
                    stats["skipped_prefilter"] += 1
                    logger.debug("WhatsApp %s dropped by prefilter: %s", mid, reason)
                    continue

                user = (
                    db.query(User)
                    .filter(User.whatsapp_phone_number_id == msg["phone_number_id"],
                            User.whatsapp_connected.is_(True))
                    .first()
                )
                if not user or not user.workspace_id:
                    stats["skipped_no_user"] += 1
                    logger.warning("WhatsApp %s: no connected user/workspace for phone_number_id=%s",
                                   mid, msg["phone_number_id"])
                    continue

                # Trial ended / not subscribed -> no task (and no AI call spent on it).
                from app.billing_access import is_user_blocked
                if is_user_blocked(db, user):
                    stats["skipped_billing"] += 1
                    continue

                # Fail closed: any AI error → no task, never a guess.
                if not await _with_retry(classify, msg["text"], sleep, stats):
                    stats["skipped_not_task"] += 1
                    continue

                extracted = await _with_retry(extract, msg["text"], sleep, stats)
                confidence = getattr(extracted, "confidence", 1.0) or 1.0
                if not extracted or not extracted.task or not extracted.task.strip():
                    stats["skipped_not_task"] += 1
                    continue
                if confidence < MIN_CONFIDENCE:
                    stats["skipped_low_confidence"] += 1
                    continue

                task = Task(
                    title             = extracted.task,
                    task_description  = extracted.task,
                    assignee          = extracted.assignee or None,
                    deadline          = extracted.deadline,
                    priority          = extracted.priority or Priority.medium,
                    source_message    = msg["text"],
                    status            = TaskStatus.to_do,
                    workspace_id      = user.workspace_id,
                    owner_id          = user.id,
                    share_token       = _secrets.token_urlsafe(12),
                    whatsapp_message_id = mid,
                )
                db.add(task)
                db.commit()
                db.refresh(task)
                stats["created"] += 1
                logger.info("Created task id=%s from WhatsApp | user_id=%s direction=%s",
                            task.id, user.id, msg["direction"])

            except Exception as exc:  # one bad message must not drop the rest
                db.rollback()
                _SEEN.pop(mid, None)   # let a Meta re-delivery retry it
                stats["errors"] += 1
                logger.error("WhatsApp message %s failed: %s", mid, exc, exc_info=True)
    finally:
        db.close()

    return stats
