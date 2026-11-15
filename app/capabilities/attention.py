"""Operations digest, "Show me what requires attention" (Step 11.1). Read-only, deterministic, no model involved.

The service gathers its facts ONLY by submitting the ordinary domain read tools to the execution kernel as the calling user
(email.message.list, calendar.event.list, crm.lead.list, project.project.list, project.task.list). So every read is
permission-checked, policy-checked, rate-limited per connection and audited exactly like any other tool call; this module has no
connector access and no authority of its own. A source the caller may not read, that is not connected, or that fails is reported in
`sources` with a fixed status and never fails the digest. Nothing is written anywhere.

Rules (fixed, explainable; `reason` is fixed text and never comes from a remote system):
  calendar  event overlapping the next one                 high    "calendar_conflict"
            timed event starting within 2 hours            medium  "meeting_soon"
            other event starting within 24 hours           low     "meeting_today"
  project   open task past its due date                    high    "task_overdue"
            open task due today or within 2 days           medium  "task_due_soon"     (at most 5 projects, 50 tasks each)
  crm       lead created within the last 7 days            medium  "new_lead"
  email     unread inbox message                           low     "unread_email"
Limits: 10 items per source, 50 in total; a source that hit a limit is marked truncated. Chat is not included in 11.1.

Item titles and names come from external systems: they are cleaned and length-capped by the connectors, flagged `external_text`,
and are data only. Nothing in this module acts on them.
"""
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel

from app.kernel.permissions import Principal
from app.kernel.service import ToolExecutionService
from app.capabilities.kernel_read import SourceFailed as _Failed
from app.capabilities.kernel_read import SourceState, iso as _iso, parse_dt as _dt, read_tool, title as _title

Severity = Literal["high", "medium", "low"]
SourceName = Literal["calendar", "project", "crm", "email"]
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
MAX_PER_SOURCE, MAX_TOTAL, MAX_PROJECTS = 10, 50, 5
SOON, TODAY_WINDOW, NEW_LEAD_DAYS, DUE_SOON_DAYS = timedelta(hours=2), timedelta(hours=24), 7, 2


class AttentionItem(BaseModel):
    source: SourceName
    kind: str
    severity: Severity
    title: str
    reason: str
    ref_tool: str
    ref_id: Optional[str] = None
    when: Optional[str] = None
    external_text: bool = False


class SourceReport(BaseModel):
    source: SourceName
    status: SourceState
    checked: int = 0
    truncated: bool = False


class AttentionDigest(BaseModel):
    generated_at: str
    items: List[AttentionItem]
    sources: List[SourceReport]
    counts: Dict[str, int]
    partial: bool


class AttentionService:
    def __init__(self, kernel: ToolExecutionService, *, clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self._kernel, self._clock = kernel, clock

    # ------------------------------------------------------------------ public
    def digest(self, principal: Principal) -> AttentionDigest:
        now = self._clock().astimezone(timezone.utc).replace(microsecond=0)
        sources = (("calendar", self._calendar), ("project", self._project), ("crm", self._crm), ("email", self._email))
        items: List[AttentionItem] = []
        reports: List[SourceReport] = []
        for name, fn in sources:
            report = SourceReport(source=name, status="ok")
            try:
                found = fn(principal, now, report)
                report.truncated = report.truncated or len(found) > MAX_PER_SOURCE
                items.extend(found[:MAX_PER_SOURCE])
            except _Failed as failed:
                report.status = failed.state
            reports.append(report)
        order = {n: i for i, (n, _) in enumerate(sources)}
        items.sort(key=lambda i: (SEVERITY_ORDER[i.severity], i.when is None, i.when or "", order[i.source]))
        if len(items) > MAX_TOTAL:
            items = items[:MAX_TOTAL]
            for r in reports:
                r.truncated = True
        counts = {sev: sum(1 for i in items if i.severity == sev) for sev in SEVERITY_ORDER}
        return AttentionDigest(generated_at=_iso(now), items=items, sources=reports, counts=counts,
                               partial=any(r.status != "ok" or r.truncated for r in reports))

    # ------------------------------------------------------------------ one kernel read
    def _call(self, principal: Principal, tool_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return read_tool(self._kernel, principal, tool_id, data)

    # ------------------------------------------------------------------ sources
    def _calendar(self, principal, now, report) -> List[AttentionItem]:
        out = self._call(principal, "calendar.event.list",
                         {"time_min": _iso(now), "time_max": _iso(now + TODAY_WINDOW), "limit": 50})
        events = [e for e in out.get("events", []) if isinstance(e, dict) and e.get("status") != "cancelled"]
        report.checked, report.truncated = len(events), bool(out.get("next_cursor"))
        timed = []
        for e in events:
            start, end = _dt(e.get("start")), _dt(e.get("end"))
            if not e.get("all_day") and start and end and end > start:
                timed.append((start, end, e))
        timed.sort(key=lambda t: t[0])
        items: List[AttentionItem] = []
        for (s1, e1, a), (s2, _e2, b) in zip(timed, timed[1:]):
            if s2 < e1:
                ta, _ = _title(a.get("summary"), "An event")
                tb, _ = _title(b.get("summary"), "another event")
                items.append(AttentionItem(source="calendar", kind="calendar_conflict", severity="high",
                                           title=f"{ta} overlaps {tb}"[:200], reason="Two events overlap in the next 24 hours",
                                           ref_tool="calendar.event.get", ref_id=b.get("id"), when=_iso(s2), external_text=True))
        for start, _end, e in timed:
            soon = start - now <= SOON
            title, ext = _title(e.get("summary"), "An event")
            items.append(AttentionItem(source="calendar", kind="meeting_soon" if soon else "meeting_today",
                                       severity="medium" if soon else "low", title=title, external_text=ext,
                                       reason="Starts within 2 hours" if soon else "Starts within 24 hours",
                                       ref_tool="calendar.event.get", ref_id=e.get("id"), when=_iso(start)))
        return items

    def _project(self, principal, now, report) -> List[AttentionItem]:
        projects = self._call(principal, "project.project.list", {"limit": MAX_PROJECTS}).get("projects", [])
        today = now.date()
        items: List[AttentionItem] = []
        for project in projects[:MAX_PROJECTS]:
            out = self._call(principal, "project.task.list", {"project_id": project.get("id"), "limit": 50})
            report.truncated = report.truncated or bool(out.get("next_cursor"))
            for task in out.get("tasks", []):
                report.checked += 1
                try:
                    due = date.fromisoformat(task.get("due_on") or "")
                except ValueError:
                    continue
                if task.get("completed") is True or (due - today).days > DUE_SOON_DAYS:
                    continue
                overdue = due < today
                title, ext = _title(task.get("name"), "A task")
                items.append(AttentionItem(source="project", kind="task_overdue" if overdue else "task_due_soon",
                                           severity="high" if overdue else "medium", title=title, external_text=ext,
                                           reason="Open and past its due date" if overdue else "Open and due within 2 days",
                                           ref_tool="project.task.get", ref_id=task.get("id"), when=f"{due.isoformat()}T00:00:00Z"))
        report.truncated = report.truncated or len(projects) > MAX_PROJECTS
        return items

    def _crm(self, principal, now, report) -> List[AttentionItem]:
        out = self._call(principal, "crm.lead.list", {"limit": 50})
        leads = [x for x in out.get("leads", []) if isinstance(x, dict)]
        report.checked, report.truncated = len(leads), bool(out.get("next_cursor"))
        items = []
        for lead in leads:
            created = _dt(lead.get("created_at"))
            if created is None or now - created > timedelta(days=NEW_LEAD_DAYS) or created > now + timedelta(minutes=5):
                continue
            name = " ".join(p for p in (lead.get("first_name"), lead.get("last_name")) if p)
            title, ext = _title(name or lead.get("email"), "A new lead")
            items.append(AttentionItem(source="crm", kind="new_lead", severity="medium", title=title, external_text=ext,
                                       reason="Created in the last 7 days", ref_tool="crm.lead.get", ref_id=lead.get("id"),
                                       when=_iso(created)))
        return items

    def _email(self, principal, now, report) -> List[AttentionItem]:
        out = self._call(principal, "email.message.list", {"label": "INBOX", "unread_only": True, "limit": 25})
        messages = [m for m in out.get("messages", []) if isinstance(m, dict)]
        report.checked, report.truncated = len(messages), bool(out.get("next_cursor"))
        items = []
        for m in messages:
            title, ext = _title(m.get("subject"), "(no subject)")
            items.append(AttentionItem(source="email", kind="unread_email", severity="low", title=title, external_text=ext,
                                       reason="Unread in the inbox", ref_tool="email.message.get", ref_id=m.get("id")))
        return items
