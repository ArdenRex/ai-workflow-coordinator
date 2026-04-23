"""
priority_engine.py
──────────────────
Segment 2: Priority + Urgency engine.

Applies workspace-level rules to override or boost task priority:

1. Keyword rules   — specific words/phrases in the message force a priority
2. Channel rules   — specific Slack channels always produce High priority
3. Urgency boost   — if AI-detected urgency is "critical" or "high" and the
                     current priority is below that level, it gets bumped up
4. Drift detection — returns True if a high/critical task has been unstarted
                     longer than the workspace's configured drift_alert_hours

All functions are pure (no DB writes) so they can be called from anywhere.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from app.models import Priority, Task, TaskStatus, WorkspaceSettings


# ── Priority ordering (higher index = higher priority) ────────────────────────
_PRIORITY_ORDER = [
    Priority.low,
    Priority.medium,
    Priority.high,
    Priority.critical,
]


def _priority_rank(p: Priority) -> int:
    try:
        return _PRIORITY_ORDER.index(p)
    except ValueError:
        return 1  # default to medium rank


def _higher(a: Priority, b: Priority) -> Priority:
    """Return whichever priority is higher."""
    return a if _priority_rank(a) >= _priority_rank(b) else b


# ── Public API ────────────────────────────────────────────────────────────────

def apply_priority_rules(
    message: str,
    base_priority: Priority,
    urgency: str,
    slack_channel_id: Optional[str],
    settings: Optional[WorkspaceSettings],
) -> Priority:
    """
    Given a raw message, AI-assigned base_priority + urgency, and workspace
    settings, return the final priority to store on the task.

    Rules applied in order (each can only raise priority, never lower it):
      1. Keyword rules from workspace settings
      2. High-priority channel rules from workspace settings
      3. Urgency boost from AI extraction
    """
    final = base_priority

    if settings is None:
        # No custom rules — still apply urgency boost
        return _apply_urgency_boost(final, urgency)

    # ── 1. Keyword rules ──────────────────────────────────────────────────────
    keyword_rules: list[dict] = settings.keyword_rules or []
    message_lower = message.lower()

    for rule in keyword_rules:
        keyword = str(rule.get("keyword", "")).lower().strip()
        priority_str = str(rule.get("priority", "")).lower().strip()

        if not keyword or not priority_str:
            continue

        try:
            rule_priority = Priority(priority_str)
        except ValueError:
            continue

        if keyword in message_lower:
            final = _higher(final, rule_priority)

    # ── 2. High-priority channel rules ────────────────────────────────────────
    if slack_channel_id:
        high_channels: list[str] = settings.high_priority_channels or []
        if slack_channel_id in high_channels:
            final = _higher(final, Priority.high)

    # ── 3. Urgency boost ──────────────────────────────────────────────────────
    final = _apply_urgency_boost(final, urgency)

    return final


def _apply_urgency_boost(priority: Priority, urgency: str) -> Priority:
    """
    If AI detected high/critical urgency in tone, boost priority to match
    (but never lower an already higher priority).
    """
    urgency_map = {
        "high":     Priority.high,
        "critical": Priority.critical,
    }
    boost = urgency_map.get(urgency.lower() if urgency else "")
    if boost:
        return _higher(priority, boost)
    return priority


def is_drifting(task: Task, settings: Optional[WorkspaceSettings]) -> bool:
    """
    Returns True if a high/critical task has been unstarted (to_do or pending)
    for longer than drift_alert_hours.

    Used by the follow-up scheduler (Segment 3) to decide whether to ping.
    """
    # Only flag high or critical tasks
    if task.priority not in (Priority.high, Priority.critical):
        return False

    # Only flag unstarted tasks
    if task.status not in (TaskStatus.to_do, TaskStatus.pending):
        return False

    threshold_hours = 24  # default
    if settings and settings.drift_alert_hours:
        threshold_hours = max(1, settings.drift_alert_hours)

    now = datetime.now(timezone.utc)

    # created_at may be timezone-naive from older rows — normalise
    created = task.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)

    hours_old = (now - created).total_seconds() / 3600
    return hours_old >= threshold_hours


def get_priority_explanation(
    original: Priority,
    final: Priority,
    urgency: str,
    triggered_keyword: Optional[str] = None,
    triggered_channel: bool = False,
) -> str:
    """
    Returns a human-readable string explaining why priority was set/changed.
    Used by the frontend to show a tooltip like "Priority boosted: keyword URGENT".
    """
    if original == final:
        return f"Priority set to {final.value} by AI extraction."

    reasons = []
    if triggered_keyword:
        reasons.append(f"keyword '{triggered_keyword}'")
    if triggered_channel:
        reasons.append("high-priority channel")
    if urgency in ("high", "critical"):
        reasons.append(f"urgent tone detected ({urgency})")

    reason_str = " + ".join(reasons) if reasons else "workspace rules"
    return (
        f"Priority boosted from {original.value} → {final.value} "
        f"({reason_str})"
    )
