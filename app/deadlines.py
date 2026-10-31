"""
deadlines.py
------------
Task.deadline is free text written by the AI extractor ("today", "Friday",
"June 30", "next Monday") or an ISO date typed in the web UI — it is NOT a date
column. This turns it into a real date so the daily digest can ask "is it due
today?" / "is it overdue?".

Relative words ("today", "tomorrow", "Friday") are measured from WHEN THE TASK
WAS CREATED, not from now: a task created on Monday that says "tomorrow" is due
Tuesday, even if the digest runs on Thursday.

Returns None when the text isn't a recognizable date ("soon", "asap", "next
week", ...) — those tasks simply never count as due-today or overdue.
Dates are UTC, matching the rest of the scheduler.
"""

import re
from datetime import date, datetime, timedelta, timezone
from typing import Optional

_WEEKDAYS = {
    "monday": 0, "mon": 0, "tuesday": 1, "tue": 1, "tues": 1, "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thur": 3, "thurs": 3, "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5, "sunday": 6, "sun": 6,
}
_MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3, "april": 4, "apr": 4,
    "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7, "august": 8, "aug": 8,
    "september": 9, "sept": 9, "sep": 9, "october": 10, "oct": 10, "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}
_MONTH_RE = "|".join(sorted(_MONTHS, key=len, reverse=True))
_WEEKDAY_RE = "|".join(sorted(_WEEKDAYS, key=len, reverse=True))

_ISO = re.compile(r"^\s*(\d{4})-(\d{1,2})-(\d{1,2})(?:[T\s].*)?$")
_MONTH_DAY = re.compile(rf"\b({_MONTH_RE})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b")
_DAY_MONTH = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_MONTH_RE})\b")
_IN_DAYS = re.compile(r"\bin\s+(\d{1,3})\s+days?\b")
_TODAY = re.compile(r"\b(today|tonight)\b")
# Time-of-day words only qualify a day ("Friday EOD"); on their own they mean today.
_TODAY_QUALIFIER = re.compile(r"\b(eod|end of (?:the )?day|this (?:morning|afternoon|evening))\b")
_TOMORROW = re.compile(r"\b(tomorrow|tmrw|tmr)\b")
_WEEKDAY = re.compile(rf"\b(next\s+)?({_WEEKDAY_RE})\b")

# A date like "June 30" with no year means the UPCOMING one — unless it is only
# slightly in the past (then the task is genuinely overdue, not a year away).
_PAST_GRACE_DAYS = 30


def _base_date(created_at: Optional[datetime]) -> date:
    if created_at is None:
        return datetime.now(timezone.utc).date()
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return created_at.astimezone(timezone.utc).date()


def _safe_date(y: int, m: int, d: int) -> Optional[date]:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _month_day(base: date, month: int, day: int) -> Optional[date]:
    d = _safe_date(base.year, month, day)
    if d is None:
        return None
    if d < base - timedelta(days=_PAST_GRACE_DAYS):
        d = _safe_date(base.year + 1, month, day)
    return d


def resolve_deadline_date(text: Optional[str], created_at: Optional[datetime] = None) -> Optional[date]:
    """The calendar date a deadline string refers to, or None if it can't be told."""
    if not text or not str(text).strip():
        return None
    base = _base_date(created_at)
    raw = str(text)

    m = _ISO.match(raw)
    if m:
        return _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    t = raw.strip().lower()

    m = _MONTH_DAY.search(t)
    if m:
        return _month_day(base, _MONTHS[m.group(1)], int(m.group(2)))
    m = _DAY_MONTH.search(t)
    if m:
        return _month_day(base, _MONTHS[m.group(2)], int(m.group(1)))

    m = _IN_DAYS.search(t)
    if m:
        return base + timedelta(days=int(m.group(1)))
    if _TODAY.search(t):
        return base
    if _TOMORROW.search(t):
        return base + timedelta(days=1)

    m = _WEEKDAY.search(t)
    if m:
        ahead = (_WEEKDAYS[m.group(2)] - base.weekday()) % 7
        if m.group(1) and ahead == 0:      # "next Monday" said on a Monday = a week later
            ahead = 7
        return base + timedelta(days=ahead)

    if _TODAY_QUALIFIER.search(t):
        return base

    return None
