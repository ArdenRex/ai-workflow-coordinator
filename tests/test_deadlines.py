"""Reading the AI's free-text deadlines ("today", "Friday", "June 30", ISO dates) as real dates."""
from datetime import date, datetime, timedelta, timezone

import pytest

from app.deadlines import resolve_deadline_date as rd

WED = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)      # a Wednesday


@pytest.mark.parametrize("text,expected", [
    ("today", date(2026, 10, 28)), ("Today by 5pm", date(2026, 10, 28)), ("tonight", date(2026, 10, 28)),
    ("EOD", date(2026, 10, 28)), ("end of day", date(2026, 10, 28)), ("this afternoon", date(2026, 10, 28)),
    ("tomorrow", date(2026, 10, 29)), ("Tmrw", date(2026, 10, 29)),
    ("Friday", date(2026, 10, 30)), ("friday", date(2026, 10, 30)), ("Fri", date(2026, 10, 30)),
    ("this Friday", date(2026, 10, 30)), ("by Friday EOD", date(2026, 10, 30)), ("tomorrow EOD", date(2026, 10, 29)),
    ("Wednesday", date(2026, 10, 28)),                         # same weekday = today
    ("Sunday", date(2026, 11, 1)), ("Monday", date(2026, 11, 2)),
    ("next Monday", date(2026, 11, 2)), ("next Wednesday", date(2026, 11, 4)),
    ("June 30", date(2027, 6, 30)), ("30 June", date(2027, 6, 30)), ("Jun 30th", date(2027, 6, 30)),
    ("30th of June", date(2027, 6, 30)),
    ("October 20", date(2026, 10, 20)),                        # slightly past = overdue, not next year
    ("Nov 5", date(2026, 11, 5)), ("December 1st", date(2026, 12, 1)),
    ("2026-11-05", date(2026, 11, 5)), ("2026-11-05T17:00:00Z", date(2026, 11, 5)),
    ("2026-11-05 17:00", date(2026, 11, 5)), ("2026-1-5", date(2026, 1, 5)), ("2020-01-01", date(2020, 1, 1)),
    ("in 3 days", date(2026, 10, 31)), ("in 1 day", date(2026, 10, 29)),
])
def test_recognised(text, expected):
    assert rd(text, WED) == expected


@pytest.mark.parametrize("text", [None, "", "   ", "asap", "soon", "next week", "whenever", "end of month",
                                  "Feb 30", "2026-13-45", "March", "the may meeting", "no deadline", "Q3"])
def test_unrecognised_is_none(text):
    assert rd(text, WED) is None


def test_relative_words_are_measured_from_creation_not_from_now():
    created_monday = datetime(2026, 10, 26, 9, 0, tzinfo=timezone.utc)
    assert rd("tomorrow", created_monday) == date(2026, 10, 27)
    assert rd("today", created_monday) == date(2026, 10, 26)
    assert rd("Friday", created_monday) == date(2026, 10, 30)


def test_year_rollover():
    dec = datetime(2026, 12, 28, tzinfo=timezone.utc)
    assert rd("January 5", dec) == date(2027, 1, 5)            # upcoming
    assert rd("Dec 20", dec) == date(2026, 12, 20)             # just passed
    assert rd("Feb 29", datetime(2027, 1, 2, tzinfo=timezone.utc)) is None   # 2027 is not a leap year


def test_timezones_and_missing_created_at():
    late_in_karachi_west = datetime(2026, 10, 28, 23, 30, tzinfo=timezone(timedelta(hours=-5)))   # = 04:30 UTC next day
    assert rd("today", late_in_karachi_west) == date(2026, 10, 29)
    assert rd("today", datetime(2026, 10, 28, 12, 0)) == date(2026, 10, 28)                        # naive = UTC
    assert rd("today", None) == datetime.now(timezone.utc).date()
