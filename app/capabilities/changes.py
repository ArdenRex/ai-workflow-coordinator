"""Business Intelligence, "What changed this week?" (Step 11.4). Read-only, deterministic, no model involved.

Summarises the last 7 days (window = [now - 7 days, now]) across calendar, project, CRM and email. Facts come ONLY from ordinary read
tools submitted to the execution kernel as the calling user (see kernel_read.py): permission-checked, policy-checked, rate-limited
per connection and audited like any other tool call. This module has no connector access and no authority of its own.

What each source can honestly say (the connectors expose nothing more):
  calendar  meeting_held       non-cancelled event that started in the window and has ended   (counts: meetings_held, meetings_cancelled)
  project   task_overdue       open task whose due date fell inside the window (became overdue this week)
            task_completed     completed task last modified in the window (Asana has no completion time: "modified" is the evidence)
            task_updated       open task last modified in the window            (one item per task; precedence overdue > completed > updated)
  crm       lead_created       lead created in the window
            lead_updated       lead created earlier but updated in the window
  email     COUNTS ONLY        received (INBOX), of which unread, and sent (SENT); no subjects or senders are returned, because email
                               is the most sensitive and most injectable text. Gmail's own `newer_than:7d` filter does the date
                               filtering; a message whose Date header parses and falls outside the window is dropped as well.
`counts` always holds every key below (zero when nothing happened) and covers everything that was READ, not only the capped items.
Items: at most 10 per source, 40 in total, newest first (then source, then id). Limits: calendar 2 pages of 50, project first 5
projects x 1 page of 100 tasks, CRM 3 pages of 100, email 2 pages of 25 per label; anything left over marks the source `truncated`.
A failure on a first read gives the source a fixed status and no data; a later failure keeps what was read, sets the status and marks
`truncated`. A broken source never breaks the report. No remote error text is ever returned. Names and titles are external text:
cleaned and capped by the connectors, flagged `external_text`, returned as data, and never acted on.
"""
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel

from app.capabilities.attention import SourceReport
from app.capabilities.kernel_read import SourceFailed, iso, parse_dt, read_tool, title
from app.kernel.permissions import Principal
from app.kernel.service import ToolExecutionService

WINDOW = timedelta(days=7)
MAX_PER_SOURCE, MAX_TOTAL, MAX_PROJECTS = 10, 40, 5
CAL_PAGES, CAL_PAGE_SIZE = 2, 50
TASK_PAGE_SIZE = 100
CRM_PAGES, CRM_PAGE_SIZE = 3, 100
MAIL_PAGES, MAIL_PAGE_SIZE, MAIL_QUERY = 2, 25, "newer_than:7d"
FUTURE_SLACK = timedelta(minutes=5)
COUNT_KEYS = ("meetings_held", "meetings_cancelled", "tasks_completed", "tasks_updated", "tasks_overdue", "leads_created",
              "leads_updated", "emails_received", "emails_unread", "emails_sent")
SOURCE_ORDER = {"calendar": 0, "project": 1, "crm": 2, "email": 3}


class ChangeItem(BaseModel):
    source: str
    kind: str
    title: str
    reason: str
    when: Optional[str] = None
    ref_tool: str
    ref_id: Optional[str] = None
    external_text: bool = False


class WeeklyChanges(BaseModel):
    generated_at: str
    window_start: str
    window_end: str
    counts: Dict[str, int]
    items: List[ChangeItem]
    sources: List[SourceReport]
    partial: bool


class _Acc:
    """What one source gathered: items, counts and the report it updates."""

    def __init__(self, report: SourceReport):
        self.report, self.items, self.counts = report, [], {}

    def add(self, key: str, n: int = 1) -> None:
        self.counts[key] = self.counts.get(key, 0) + n

    def fail(self, state: str) -> None:
        self.report.status = state
        self.report.truncated = self.report.checked > 0          # a first-read failure has nothing to be truncated


class ChangesService:
    def __init__(self, kernel: ToolExecutionService, *, clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self._kernel, self._clock = kernel, clock

    def report(self, principal: Principal) -> WeeklyChanges:
        now = self._clock().astimezone(timezone.utc).replace(microsecond=0)
        start = now - WINDOW
        sources = (("calendar", self._calendar), ("project", self._project), ("crm", self._crm), ("email", self._email))
        items: List[ChangeItem] = []
        reports: List[SourceReport] = []
        counts = {k: 0 for k in COUNT_KEYS}
        for name, fn in sources:
            acc = _Acc(SourceReport(source=name, status="ok"))
            try:
                fn(principal, now, start, acc)
            except SourceFailed as failed:
                acc.fail(failed.state)
            for key, n in acc.counts.items():
                counts[key] += n
            found = sorted(acc.items, key=_order)
            acc.report.truncated = acc.report.truncated or len(found) > MAX_PER_SOURCE
            items.extend(found[:MAX_PER_SOURCE])
            reports.append(acc.report)
        items.sort(key=_order)
        if len(items) > MAX_TOTAL:
            items = items[:MAX_TOTAL]
            for r in reports:
                r.truncated = True
        return WeeklyChanges(generated_at=iso(now), window_start=iso(start), window_end=iso(now), counts=counts, items=items,
                             sources=reports, partial=any(r.status != "ok" or r.truncated for r in reports))

    def _call(self, principal: Principal, tool_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return read_tool(self._kernel, principal, tool_id, data)

    # ------------------------------------------------------------------ calendar
    def _calendar(self, principal, now, start, acc: _Acc) -> None:
        cursor, seen = None, set()
        for page in range(CAL_PAGES):
            data: Dict[str, Any] = {"time_min": iso(start), "time_max": iso(now), "limit": CAL_PAGE_SIZE}
            if cursor:
                data["cursor"] = cursor
            try:
                out = self._call(principal, "calendar.event.list", data)
            except SourceFailed as failed:
                if acc.report.checked == 0:
                    raise
                acc.fail(failed.state)
                return
            for e in (x for x in out.get("events", []) if isinstance(x, dict)):
                eid = e.get("id")
                if eid in seen:
                    continue
                seen.add(eid)
                acc.report.checked += 1
                self._event(e, now, start, acc)
            cursor = out.get("next_cursor") if isinstance(out.get("next_cursor"), str) and out.get("next_cursor") else None
            if cursor is None:
                return
        acc.report.truncated = True

    @staticmethod
    def _event(e: Dict[str, Any], now: datetime, start: datetime, acc: _Acc) -> None:
        if e.get("all_day"):
            try:
                first, end_day = date.fromisoformat(str(e.get("start"))), date.fromisoformat(str(e.get("end")))
            except ValueError:
                return
            began, ended = first >= start.date(), end_day <= now.date()
            when = f"{first.isoformat()}T00:00:00Z"
        else:
            s, en = parse_dt(e.get("start")), parse_dt(e.get("end"))
            if s is None or en is None or en <= s:
                return
            began, ended, when = s >= start, en <= now, iso(s)
        if not began:
            return                                              # started before the window: not an event of this week
        if e.get("status") == "cancelled":
            acc.add("meetings_cancelled")
            return
        if not ended:
            return
        acc.add("meetings_held")
        shown, ext = title(e.get("summary"), "An event")
        acc.items.append(ChangeItem(source="calendar", kind="meeting_held", title=shown, external_text=ext, when=when,
                                    reason="Took place in the past 7 days", ref_tool="calendar.event.get", ref_id=e.get("id")))

    # ------------------------------------------------------------------ project
    def _project(self, principal, now, start, acc: _Acc) -> None:
        projects = self._call(principal, "project.project.list", {"limit": MAX_PROJECTS}).get("projects", [])
        acc.report.truncated = len(projects) > MAX_PROJECTS
        seen, today = set(), now.date()
        for project in projects[:MAX_PROJECTS]:
            try:
                out = self._call(principal, "project.task.list",
                                 {"project_id": project.get("id"), "limit": TASK_PAGE_SIZE, "include_completed": True})
            except SourceFailed as failed:
                if acc.report.checked == 0 and not acc.counts:
                    raise
                acc.fail(failed.state)
                acc.report.truncated = True
                return
            acc.report.truncated = acc.report.truncated or bool(out.get("next_cursor"))
            for t in (x for x in out.get("tasks", []) if isinstance(x, dict)):
                tid = t.get("id")
                if tid in seen:
                    continue
                seen.add(tid)
                acc.report.checked += 1
                self._task(t, now, start, today, acc)

    @staticmethod
    def _task(t: Dict[str, Any], now: datetime, start: datetime, today: date, acc: _Acc) -> None:
        modified = parse_dt(t.get("modified_at"))
        changed = modified is not None and start <= modified <= now + FUTURE_SLACK
        done = t.get("completed") is True
        try:
            due: Optional[date] = date.fromisoformat(t.get("due_on") or "")
        except ValueError:
            due = None
        shown, ext = title(t.get("name"), "A task")
        if not done and due is not None and start.date() <= due < today:
            kind, reason, when = "task_overdue", "Open and became overdue in the past 7 days", f"{due.isoformat()}T00:00:00Z"
            acc.add("tasks_overdue")
        elif done and changed:
            kind, reason, when = "task_completed", "Complete, and last changed in the past 7 days", iso(modified)
            acc.add("tasks_completed")
        elif not done and changed:
            kind, reason, when = "task_updated", "Open, and changed in the past 7 days", iso(modified)
            acc.add("tasks_updated")
        else:
            return
        acc.items.append(ChangeItem(source="project", kind=kind, title=shown, reason=reason, when=when, external_text=ext,
                                    ref_tool="project.task.get", ref_id=t.get("id")))

    # ------------------------------------------------------------------ crm
    def _crm(self, principal, now, start, acc: _Acc) -> None:
        cursor, seen = None, set()
        for page in range(CRM_PAGES):
            data: Dict[str, Any] = {"limit": CRM_PAGE_SIZE}
            if cursor:
                data["cursor"] = cursor
            try:
                out = self._call(principal, "crm.lead.list", data)
            except SourceFailed as failed:
                if acc.report.checked == 0:
                    raise
                acc.fail(failed.state)
                return
            for lead in (x for x in out.get("leads", []) if isinstance(x, dict)):
                lid = lead.get("id")
                if lid in seen or not isinstance(lid, str):
                    continue
                seen.add(lid)
                acc.report.checked += 1
                self._lead(lead, now, start, acc)
            cursor = out.get("next_cursor") if isinstance(out.get("next_cursor"), str) and out.get("next_cursor") else None
            if cursor is None:
                return
        acc.report.truncated = True

    @staticmethod
    def _lead(lead: Dict[str, Any], now: datetime, start: datetime, acc: _Acc) -> None:
        def inside(value: Any) -> Optional[datetime]:
            d = parse_dt(value)
            return d if d is not None and start <= d <= now + FUTURE_SLACK else None
        created, updated = inside(lead.get("created_at")), inside(lead.get("updated_at"))
        if created is not None:
            kind, reason, when, key = "lead_created", "Created in the past 7 days", created, "leads_created"
        elif updated is not None:
            kind, reason, when, key = "lead_updated", "Updated in the past 7 days", updated, "leads_updated"
        else:
            return
        acc.add(key)
        name = " ".join(p for p in (lead.get("first_name"), lead.get("last_name")) if isinstance(p, str) and p)
        shown, ext = title(name or lead.get("email"), "A lead")
        acc.items.append(ChangeItem(source="crm", kind=kind, title=shown, reason=reason, when=iso(when), external_text=ext,
                                    ref_tool="crm.lead.get", ref_id=lead["id"]))

    # ------------------------------------------------------------------ email (counts only)
    def _email(self, principal, now, start, acc: _Acc) -> None:
        for label, key in (("INBOX", "emails_received"), ("SENT", "emails_sent")):
            cursor, seen = None, set()
            for page in range(MAIL_PAGES):
                data: Dict[str, Any] = {"label": label, "query": MAIL_QUERY, "limit": MAIL_PAGE_SIZE}
                if cursor:
                    data["cursor"] = cursor
                try:
                    out = self._call(principal, "email.message.list", data)
                except SourceFailed as failed:
                    if acc.report.checked == 0:
                        raise
                    acc.fail(failed.state)
                    return
                for m in (x for x in out.get("messages", []) if isinstance(x, dict)):
                    mid = m.get("id")
                    if mid in seen:
                        continue
                    seen.add(mid)
                    acc.report.checked += 1
                    if not _in_window(m.get("date"), start, now):
                        continue
                    acc.add(key)
                    if label == "INBOX" and m.get("unread") is True:
                        acc.add("emails_unread")
                cursor = out.get("next_cursor") if isinstance(out.get("next_cursor"), str) and out.get("next_cursor") else None
                if cursor is None:
                    break
            else:
                acc.report.truncated = True


def _in_window(text: Any, start: datetime, now: datetime) -> bool:
    """Gmail already filtered by date; a Date header that parses cleanly and is outside the window is dropped, anything else is kept."""
    try:
        value = parsedate_to_datetime(text) if isinstance(text, str) else None
    except (TypeError, ValueError, IndexError):
        value = None
    if value is None or value.tzinfo is None:
        return True
    return start <= value <= now + FUTURE_SLACK


def _order(item: ChangeItem):
    return (item.when is None, _neg(item.when), SOURCE_ORDER.get(item.source, 9), item.ref_id or "")


def _neg(when: Optional[str]):
    """Newest first without parsing: ISO UTC text sorts chronologically, so invert it character by character."""
    return tuple(-ord(c) for c in when) if when else ()
