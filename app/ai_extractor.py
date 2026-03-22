"""
ai_extractor.py
───────────────
Uses Groq's chat completion to extract:
  - task        : concise, actionable description
  - assignee    : person responsible (or null)
  - deadline    : human-readable due date (or null)
  - priority    : "low" | "medium" | "high" | "critical"

from a raw Slack/email message.
"""

import json
import logging
from typing import Optional

from groq import AsyncGroq, APITimeoutError, AuthenticationError, RateLimitError, APIError

from app.config import get_settings
from app.models import Priority
from app.schemas import ExtractedTask

logger = logging.getLogger(__name__)

# ── Client — instantiated once, reused across requests ───────────────────────
_client: Optional[AsyncGroq] = None


def _get_client() -> AsyncGroq:
    global _client
    if _client is None:
        settings = get_settings()
        _client = AsyncGroq(
            api_key=settings.groq_api_key.get_secret_value(),
            timeout=30.0,
            max_retries=2,
        )
    return _client


VALID_PRIORITIES: set[str] = {p.value for p in Priority}

SYSTEM_PROMPT = """You are a task extraction assistant for a project management system.

Given a message from Slack or email, extract the following fields and return ONLY valid JSON:
{
  "task": "clear, actionable task description (always required)",
  "assignee": "first or full name of the person responsible, or null if not mentioned",
  "deadline": "deadline in plain English e.g. 'Friday', 'June 30', 'next Monday', or null",
  "priority": "one of: low | medium | high | critical"
}

Priority inference rules — read urgency signals carefully:
- "critical"  → production down, security breach, data loss, "ASAP", "emergency", "blocking everything"
- "high"      → "urgent", "important", "as soon as possible", tight deadline (today / tomorrow), blocking another team
- "medium"    → normal business request, this-week deadline, no explicit urgency markers
- "low"       → "whenever you get a chance", "nice to have", "no rush", far-future or no deadline

Rules:
- "task" must always be present and non-empty.
- "assignee" and "deadline" are null when absent from the message.
- "priority" must be exactly one of the four values above — never null.
- Return ONLY the JSON object. No markdown, no commentary, no extra keys.
"""

_MODEL = "llama-3.3-70b-versatile"       # Fast, free, excellent for structured extraction
_MAX_MESSAGE_CHARS = 4_000


async def extract_task_from_message(message: str) -> ExtractedTask:
    """
    Send a raw message to Groq and extract structured task data.

    Args:
        message: Raw message text from Slack or email.

    Returns:
        ExtractedTask with task, assignee, deadline, and priority fields.

    Raises:
        ValueError: If the AI response cannot be parsed or contains invalid data.
        groq.APIError: On unrecoverable API-level failure.
    """
    if not message or not message.strip():
        raise ValueError("Cannot extract task from an empty message.")

    payload = message.strip()
    if len(payload) > _MAX_MESSAGE_CHARS:
        logger.warning(
            "Message truncated from %d to %d chars before extraction.",
            len(payload), _MAX_MESSAGE_CHARS,
        )
        payload = payload[:_MAX_MESSAGE_CHARS]

    logger.info("Sending message to Groq for task extraction (len=%d).", len(payload))

    try:
        response = await _get_client().chat.completions.create(
            model=_MODEL,
            temperature=0,
            max_tokens=300,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Extract task from this message:\n\n{payload}"},
            ],
            response_format={"type": "json_object"},
        )
    except RateLimitError as exc:
        logger.error("Groq rate limit hit: %s", exc)
        raise
    except AuthenticationError as exc:
        logger.critical("Groq authentication failed — check your API key: %s", exc)
        raise
    except APITimeoutError as exc:
        logger.error("Groq request timed out: %s", exc)
        raise
    except APIError as exc:
        logger.error("Groq API error: %s", exc)
        raise

    raw = response.choices[0].message.content
    if not raw:
        raise ValueError("Groq returned an empty response body.")

    logger.debug("Raw Groq response: %s", raw)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error("Groq returned invalid JSON: %s", raw)
        raise ValueError(f"AI returned invalid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"AI returned unexpected JSON type {type(data).__name__!r}; expected object.")

    raw_priority = (data.get("priority") or "").lower().strip()
    if raw_priority not in VALID_PRIORITIES:
        logger.warning("Unexpected priority %r — defaulting to 'medium'.", raw_priority)
        raw_priority = Priority.medium.value

    task_text = (data.get("task") or "").strip()
    if not task_text:
        logger.warning("AI returned empty task description — using fallback.")
        task_text = "Unnamed task"

    return ExtractedTask(
        task=task_text,
        assignee=data.get("assignee") or None,
        deadline=data.get("deadline") or None,
        priority=raw_priority,
    )
