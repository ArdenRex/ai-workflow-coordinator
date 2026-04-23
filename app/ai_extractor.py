"""
ai_extractor.py
───────────────
Uses Groq's chat completion to extract:
  - task        : concise, actionable description
  - assignee    : person responsible (or null)
  - deadline    : human-readable due date (or null)
  - priority    : "low" | "medium" | "high" | "critical"
  - urgency     : "none" | "low" | "medium" | "high" | "critical"
  - confidence  : 0.0–1.0 — how confident the AI is in the extraction

from a raw Slack/email/manual message.
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

Given a message from Slack, email, or a manager, extract the following fields and return ONLY valid JSON:
{
  "task": "clear, actionable task description (always required)",
  "assignee": "first or full name of the person responsible, or null if not mentioned",
  "deadline": "deadline as a specific, human-readable string e.g. 'today', 'tomorrow', 'Friday', 'June 30', 'next Monday', or null if no deadline",
  "priority": "one of: low | medium | high | critical",
  "urgency": "one of: none | low | medium | high | critical",
  "confidence": 0.95
}

Priority inference rules — read ALL urgency signals carefully:
- "critical"  → production down, security breach, data loss, "ASAP", "emergency", "blocking everything", "right now"
- "high"      → "urgent", "important", "as soon as possible", deadline is today or tomorrow, blocking another team, "high priority"
- "medium"    → normal business request, this-week deadline, "this week", "soon", no explicit urgency markers
- "low"       → "whenever you get a chance", "nice to have", "no rush", far-future deadline or no deadline, "low priority"

Urgency rules (separate from priority — urgency = tone of the message):
- "critical"  → all-caps, exclamation marks, "RIGHT NOW", "IMMEDIATELY", "BLOCKING"
- "high"      → strong urgency words: "urgent", "ASAP", "today", "important"
- "medium"    → moderate: "soon", "this week", "please"
- "low"       → calm tone, no urgency markers
- "none"      → purely factual, no time pressure

Deadline normalization rules:
- "today" → keep as "today"
- "tomorrow" → keep as "tomorrow"
- "next week" → keep as "next week"
- "by Friday" / "on Friday" / "Friday" → keep as "Friday"
- "June 30" / "30 June" → keep as "June 30"
- "end of month" → keep as "end of month"
- "EOD" → keep as "end of day today"
- "COB" → keep as "close of business today"
- If no deadline → null

Assignee rules:
- Extract the FULL name or first name of the person being assigned the task
- If the message says "assign to Ali", "Ali should do this", "Hey Ali", "@Ali" → assignee = "Ali"
- If the sender is assigning to themselves → assignee = null (let the system handle it)
- If no assignee is mentioned → null

Confidence rules:
- 0.9–1.0: Clear message with obvious task, assignee, and deadline
- 0.7–0.9: Most fields clear, one field ambiguous
- 0.5–0.7: Message is vague or short, some guesswork involved
- Below 0.5: Very unclear message

Rules:
- "task" must ALWAYS be present and non-empty. Write it as an imperative sentence: "Prepare sales report", "Review contract", "Fix login bug"
- "assignee" and "deadline" are null when absent
- "priority" must be exactly one of: low | medium | high | critical — never null
- "urgency" must be exactly one of: none | low | medium | high | critical — never null
- "confidence" must be a float between 0.0 and 1.0
- Return ONLY the JSON object. No markdown, no commentary, no extra keys.

Examples:
Message: "Ali make sales report today it's urgent"
Output: {"task": "Prepare sales report", "assignee": "Ali", "deadline": "today", "priority": "high", "urgency": "high", "confidence": 0.95}

Message: "Qaasim review the contract by Friday"
Output: {"task": "Review the contract", "assignee": "Qaasim", "deadline": "Friday", "priority": "medium", "urgency": "medium", "confidence": 0.95}

Message: "production is down ASAP fix it"
Output: {"task": "Fix production outage", "assignee": null, "deadline": "today", "priority": "critical", "urgency": "critical", "confidence": 0.9}

Message: "whenever you get a chance, update the docs"
Output: {"task": "Update the documentation", "assignee": null, "deadline": null, "priority": "low", "urgency": "none", "confidence": 0.85}
"""

_MODEL = "llama-3.3-70b-versatile"
_MAX_MESSAGE_CHARS = 4_000

VALID_URGENCIES: set[str] = {"none", "low", "medium", "high", "critical"}


async def extract_task_from_message(message: str) -> ExtractedTask:
    """
    Send a raw message to Groq and extract structured task data.

    Args:
        message: Raw message text from Slack, email, or manual input.

    Returns:
        ExtractedTask with task, assignee, deadline, priority, urgency, confidence.

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
            max_tokens=400,
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

    # ── Priority ──────────────────────────────────────────────────────────────
    raw_priority = (data.get("priority") or "").lower().strip()
    if raw_priority not in VALID_PRIORITIES:
        logger.warning("Unexpected priority %r — defaulting to 'medium'.", raw_priority)
        raw_priority = Priority.medium.value

    # ── Urgency ───────────────────────────────────────────────────────────────
    raw_urgency = (data.get("urgency") or "").lower().strip()
    if raw_urgency not in VALID_URGENCIES:
        logger.warning("Unexpected urgency %r — defaulting to 'medium'.", raw_urgency)
        raw_urgency = "medium"

    # ── Confidence ────────────────────────────────────────────────────────────
    try:
        confidence = float(data.get("confidence", 0.8))
        confidence = max(0.0, min(1.0, confidence))
    except (TypeError, ValueError):
        confidence = 0.8

    # ── Task text ─────────────────────────────────────────────────────────────
    task_text = (data.get("task") or "").strip()
    if not task_text:
        logger.warning("AI returned empty task description — using fallback.")
        task_text = "Unnamed task"

    # ── Assignee ──────────────────────────────────────────────────────────────
    assignee = data.get("assignee") or None
    if assignee:
        assignee = assignee.strip()

    # ── Deadline ──────────────────────────────────────────────────────────────
    deadline = data.get("deadline") or None
    if deadline:
        deadline = deadline.strip()

    logger.info(
        "Extracted — task=%r assignee=%r deadline=%r priority=%s urgency=%s confidence=%.2f",
        task_text, assignee, deadline, raw_priority, raw_urgency, confidence,
    )

    return ExtractedTask(
        task=task_text,
        assignee=assignee,
        deadline=deadline,
        priority=raw_priority,
        urgency=raw_urgency,
        confidence=confidence,
    )
