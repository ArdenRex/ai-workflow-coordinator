"""Coordination, "Prepare the information needed for tomorrow's meetings" (Step 11.5). Read-only, deterministic, no model involved.

Facts come ONLY from ordinary read tools submitted to the execution kernel as the calling user (kernel_read.py):
`calendar.event.list` for tomorrow, then `crm.lead.list` (only when there is at least one meeting to match). No connector access, no
authority of its own, nothing written.

"Tomorrow" is the next UTC calendar day: the calendar connector works in UTC and exposes no user time zone, so a workspace far from UTC
sees a shifted day. The window is returned (`window_start` / `window_end`) so this is never hidden.

Per meeting (non-cancelled events; timed ones by start then id, all-day ones after them; at most 15, more marks `truncated`):
  title, start, end, all_day, location, attendee_count (a count, never addresses), `conflicts_with` (timed events it overlaps;
  back-to-back is not an overlap) and `related_leads`.
Related leads are POSSIBLE matches by text only, because the calendar exposes no attendee emails: a lead is listed when its full name
(first and last name, each 2+ letters, as whole words in order) or its company (4+ letters, whole words in order) appears in the event
title. Name matches rank before company matches, then lead id; at most 3 per meeting. The `reason` is fixed text and says it is a title
match. The lead's email is never returned (open it with `ref_tool` / `ref_id`). Private events show "(private)" and so match nothing.
Limits: CRM 3 pages of 100 leads (more => the crm source is `truncated`). A calendar failure gives no meetings and a fixed status; a CRM
failure keeps the meetings with no related leads and sets the crm status. No remote error text is ever returned. Titles, names, companies
and stages are external text: flagged `external_text`, data only, never acted on.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from pydantic import BaseModel

from app.capabilities.attention import SourceReport
from app.capabilities.kernel_read import SourceFailed, iso, parse_dt, read_tool, title
from app.kernel.permissions import Principal
from app.kernel.service import ToolExecutionService

MAX_MEETINGS, MAX_RELATED, CAL_LIMIT = 15, 3, 50
CRM_PAGES, CRM_PAGE_SIZE = 3, 100
MIN_NAME_PART, MIN_COMPANY_CHARS = 2, 4
NAME_REASON, COMPANY_REASON = "Lead name appears in the event title", "Lead company appears in the event title"


class RelatedLead(BaseModel):
    ref_tool: str = "crm.lead.get"
    ref_id: str
    name: str
    company: Optional[str] = None
    stage: Optional[str] = None
    match: str
    reason: str
    external_text: bool = True


class BriefMeeting(BaseModel):
    ref_tool: str = "calendar.event.get"
    ref_id: str
    title: str
    external_text: bool = False
    start: str
    end: str
    all_day: bool
    location: Optional[str] = None
    attendee_count: Optional[int] = None
    conflicts_with: List[str]
    related_leads: List[RelatedLead]


class MeetingBriefing(BaseModel):
    generated_at: str
    day: str
    window_start: str
    window_end: str
    counts: Dict[str, int]
    meetings: List[BriefMeeting]
    sources: List[SourceReport]
    partial: bool


def _tokens(text: Any) -> List[str]:
    if not isinstance(text, str):
        return []
    out, cur = [], []
    for ch in text.lower():
        if ch.isalnum():
            cur.append(ch)
        elif cur:
            out.append("".join(cur))
            cur = []
    if cur:
        out.append("".join(cur))
    return out


def _contains(haystack: List[str], needle: List[str]) -> bool:
    n = len(needle)
    return n > 0 and any(haystack[i:i + n] == needle for i in range(len(haystack) - n + 1))


class MeetingService:
    def __init__(self, kernel: ToolExecutionService, *, clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self._kernel, self._clock = kernel, clock

    def brief(self, principal: Principal) -> MeetingBriefing:
        now = self._clock().astimezone(timezone.utc).replace(microsecond=0)
        start = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0)
        end = start + timedelta(days=1)
        cal, crm = SourceReport(source="calendar", status="ok"), SourceReport(source="crm", status="ok")
        meetings: List[Dict[str, Any]] = []
        try:
            meetings = self._calendar(principal, start, end, cal)
        except SourceFailed as failed:
            cal.status = failed.state
        leads: List[Dict[str, Any]] = []
        if meetings:
            try:
                leads = self._leads(principal, crm)
            except SourceFailed as failed:
                crm.status = failed.state
        shown = [self._meeting(m, meetings, leads) for m in meetings[:MAX_MEETINGS]]
        cal.truncated = cal.truncated or len(meetings) > MAX_MEETINGS
        counts = {"meetings": len(shown), "all_day": sum(1 for m in shown if m.all_day),
                  "conflicts": sum(1 for m in shown if m.conflicts_with),
                  "with_related_leads": sum(1 for m in shown if m.related_leads)}
        return MeetingBriefing(generated_at=iso(now), day=start.date().isoformat(), window_start=iso(start), window_end=iso(end),
                               counts=counts, meetings=shown, sources=[cal, crm],
                               partial=any(r.status != "ok" or r.truncated for r in (cal, crm)))

    # ------------------------------------------------------------------ reads
    def _calendar(self, principal, start, end, report: SourceReport) -> List[Dict[str, Any]]:
        out = read_tool(self._kernel, principal, "calendar.event.list", {"time_min": iso(start), "time_max": iso(end), "limit": CAL_LIMIT})
        events = [e for e in out.get("events", []) if isinstance(e, dict) and e.get("status") != "cancelled"
                  and isinstance(e.get("id"), str)]
        report.checked, report.truncated = len(events), bool(out.get("next_cursor"))
        found, seen = [], set()
        for e in events:
            if e["id"] in seen:
                continue
            seen.add(e["id"])
            s, en = parse_dt(e.get("start")), parse_dt(e.get("end"))
            if e.get("all_day"):
                found.append({"e": e, "timed": False, "s": None, "en": None})
            elif s is not None and en is not None and en > s:
                found.append({"e": e, "timed": True, "s": s, "en": en})
        found.sort(key=lambda m: (not m["timed"], m["s"] or start, m["e"]["id"]))
        return found

    def _leads(self, principal, report: SourceReport) -> List[Dict[str, Any]]:
        leads: List[Dict[str, Any]] = []
        cursor: Optional[str] = None
        for _ in range(CRM_PAGES):
            data: Dict[str, Any] = {"limit": CRM_PAGE_SIZE}
            if cursor:
                data["cursor"] = cursor
            try:
                out = read_tool(self._kernel, principal, "crm.lead.list", data)
            except SourceFailed as failed:
                if not leads:
                    raise
                report.status, report.truncated = failed.state, True          # keep what an earlier page returned
                return leads
            page = [x for x in out.get("leads", []) if isinstance(x, dict) and isinstance(x.get("id"), str)]
            leads.extend(page)
            report.checked = len(leads)
            cursor = out.get("next_cursor") if isinstance(out.get("next_cursor"), str) and out.get("next_cursor") else None
            if cursor is None:
                return leads
        report.truncated = True
        return leads

    # ------------------------------------------------------------------ one meeting
    def _meeting(self, m: Dict[str, Any], all_meetings: List[Dict[str, Any]], leads: List[Dict[str, Any]]) -> BriefMeeting:
        e = m["e"]
        shown, ext = title(e.get("summary"), "An event")
        conflicts = sorted(o["e"]["id"] for o in all_meetings
                           if m["timed"] and o["timed"] and o is not m and o["s"] < m["en"] and m["s"] < o["en"])
        location = e.get("location") if isinstance(e.get("location"), str) and e.get("location").strip() else None
        attendees = e.get("attendee_count") if isinstance(e.get("attendee_count"), int) and not isinstance(e.get("attendee_count"), bool) else None
        return BriefMeeting(ref_id=e["id"], title=shown, external_text=ext, start=str(e.get("start"))[:40], end=str(e.get("end"))[:40],
                            all_day=not m["timed"], location=location[:200] if location else None, attendee_count=attendees,
                            conflicts_with=conflicts, related_leads=self._related(e.get("summary") if ext else None, leads))

    @staticmethod
    def _related(summary: Optional[str], leads: List[Dict[str, Any]]) -> List[RelatedLead]:
        words = _tokens(summary)
        if not words:
            return []
        hits: List[Tuple[int, str, RelatedLead]] = []
        for lead in leads:
            first, last = _tokens(lead.get("first_name")), _tokens(lead.get("last_name"))
            name_words = first + last
            company = _tokens(lead.get("company"))
            kind = None
            if first and last and min(len(w) for w in name_words) >= MIN_NAME_PART and _contains(words, name_words):
                kind = 0
            elif company and sum(len(w) for w in company) >= MIN_COMPANY_CHARS and _contains(words, company):
                kind = 1
            if kind is None:
                continue
            name = " ".join(p for p in (lead.get("first_name"), lead.get("last_name")) if isinstance(p, str) and p)
            shown, _ = title(name or lead.get("email"), "(unnamed lead)")
            comp = lead.get("company") if isinstance(lead.get("company"), str) and lead.get("company").strip() else None
            stage = lead.get("stage") if isinstance(lead.get("stage"), str) and lead.get("stage").strip() else None
            hits.append((kind, lead["id"], RelatedLead(ref_id=lead["id"], name=shown, company=comp[:200] if comp else None,
                                                       stage=stage[:64] if stage else None, match="name" if kind == 0 else "company",
                                                       reason=NAME_REASON if kind == 0 else COMPANY_REASON)))
        hits.sort(key=lambda h: (h[0], h[1]))
        return [h[2] for h in hits[:MAX_RELATED]]
