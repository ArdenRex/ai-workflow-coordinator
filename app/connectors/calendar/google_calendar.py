"""Google Calendar connector (read-only): the PRIMARY calendar of the account that owns the OAuth grant.

Uses OAuth refresh-token credentials (see app/connectors/oauth.py) and refuses a grant broader than the read-only
calendar scopes. Only GET requests are made, only to calendars/primary/events. Availability is computed from events
(opaque, not cancelled), clipped to the window and merged; all-day events count as busy for whole UTC days (their real
time zone is not requested). Shapes follow Calendar API v3 as I know it; verify against a real account before relying on it.
"""
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, List, Optional, Tuple

from pydantic import ValidationError

from app.connectors.base import Capability
from app.connectors.calendar.base import (CURSOR_PATTERN, EVENT_ID_PATTERN, PRIVATE_TITLE, AvailabilityInput,
                                          AvailabilityOutput, BusySlot, CalendarConnector, Event, EventDetail,
                                          CalendarWriter, CreateMeetingInput, CreateMeetingOutput, GetEventInput, GetEventOutput,
                                          ListEventsInput, ListEventsOutput,
                                          calendar_tool_definitions, to_utc_text)
from app.connectors.errors import ConnectorBadResponseError, ConnectorNotFoundError
from app.connectors.kit import paginate
from app.connectors.oauth import OAuthConnector
from app.kernel.registry import ToolDefinition

CALENDAR_SCOPES = frozenset({"https://www.googleapis.com/auth/calendar.readonly",
                             "https://www.googleapis.com/auth/calendar.events.readonly"})
CALENDAR_WRITE_SCOPES = frozenset({"https://www.googleapis.com/auth/calendar.events"})
_CURSOR = re.compile(CURSOR_PATTERN)
_ID = re.compile(EVENT_ID_PATTERN)
_EVENT_FIELDS = "id,status,summary,start,end,location,visibility,transparency,attendees/email"
_LIST_FIELDS = f"nextPageToken,items({_EVENT_FIELDS})"
_GET_FIELDS = f"{_EVENT_FIELDS},description"
_EVENTS = "/calendar/v3/calendars/primary/events"
_bad = lambda: ConnectorBadResponseError("External system returned an unexpected shape")  # noqa: E731


def _moment(node: Any) -> Tuple[str, bool, datetime]:
    """(text, all_day, instant in UTC) from a Calendar start/end object."""
    if not isinstance(node, dict):
        raise _bad()
    try:
        if node.get("dateTime") is not None:
            if not isinstance(node["dateTime"], str):
                raise _bad()
            dt = datetime.fromisoformat(node["dateTime"])
            if dt.tzinfo is None or dt.utcoffset() is None:
                raise _bad()
            return to_utc_text(dt), False, dt.astimezone(timezone.utc)
        if isinstance(node.get("date"), str):
            d = date.fromisoformat(node["date"])
            return d.isoformat(), True, datetime.combine(d, time.min, tzinfo=timezone.utc)
    except ValueError:
        raise _bad() from None
    raise _bad()


class GoogleCalendarConnector(OAuthConnector, CalendarConnector, CalendarWriter):
    name = "google_calendar"
    allowed_scopes = CALENDAR_SCOPES
    write_scopes = CALENDAR_WRITE_SCOPES
    probe_path = _EVENTS
    probe_params = {"maxResults": 1, "fields": "items(id)"}

    def capabilities(self) -> List[Capability]:
        caps = [Capability("event.list", "List events"), Capability("event.get", "Get one event"),
                Capability("availability.read", "Read busy intervals")]
        if self.allow_write:
            caps.append(Capability("meeting.create", "Create a calendar event", write=True))
        return caps

    def tools(self) -> List[ToolDefinition]:
        return calendar_tool_definitions(lambda workspace_id: self)

    # -- reads -------------------------------------------------------------------
    def _page(self, data, cursor: Optional[str], limit: int):
        params = {"timeMin": data.time_min, "timeMax": data.time_max, "singleEvents": "true", "orderBy": "startTime",
                  "maxResults": limit, "fields": _LIST_FIELDS}
        if cursor:
            params["pageToken"] = cursor
        raw = self._request("GET", _EVENTS, params=params)
        if not isinstance(raw, dict) or not isinstance(raw.get("items", []), list):
            raise _bad()
        nxt = raw.get("nextPageToken")
        if nxt is not None and (not isinstance(nxt, str) or not _CURSOR.match(nxt)):
            raise _bad()
        return raw.get("items", []), nxt or None

    def list_events(self, data: ListEventsInput) -> ListEventsOutput:
        items, nxt = self._page(data, data.cursor, data.limit)
        events = [self._event(i, Event) for i in items if not (isinstance(i, dict) and i.get("status") == "cancelled")]
        return ListEventsOutput(events=events[:data.limit], next_cursor=nxt)

    def get_event(self, data: GetEventInput) -> GetEventOutput:
        raw = self._request("GET", f"{_EVENTS}/{data.event_id}", params={"fields": _GET_FIELDS})
        if not isinstance(raw, dict):
            raise _bad()
        if raw.get("id") != data.event_id or raw.get("status") == "cancelled":
            raise ConnectorNotFoundError("Resource not found in external system")
        return GetEventOutput(event=self._event(raw, EventDetail))

    def availability(self, data: AvailabilityInput) -> AvailabilityOutput:
        lo = datetime.fromisoformat(data.time_min.replace("Z", "+00:00"))
        hi = datetime.fromisoformat(data.time_max.replace("Z", "+00:00"))
        page = paginate(lambda cur: self._page(data, cur, 250), max_pages=5, max_items=500)
        spans = []
        for item in page.items:
            if not isinstance(item, dict):
                raise _bad()
            if item.get("status") == "cancelled" or item.get("transparency") == "transparent":
                continue
            _, _, start = _moment(item.get("start"))
            _, _, end = _moment(item.get("end"))
            start, end = max(start, lo), min(end, hi)
            if end > start:
                spans.append((start, end))
        merged: List[List[datetime]] = []
        for start, end in sorted(spans):
            if merged and start <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
        return AvailabilityOutput(busy=[BusySlot(start=to_utc_text(s), end=to_utc_text(e)) for s, e in merged],
                                  truncated=page.truncated)

    # -- helpers -----------------------------------------------------------------
    @staticmethod
    def _event(raw: Any, model):
        if not isinstance(raw, dict) or not isinstance(raw.get("id"), str) or not _ID.match(raw["id"]):
            raise _bad()
        start, all_day, _ = _moment(raw.get("start"))
        end, _, _ = _moment(raw.get("end"))
        attendees = raw.get("attendees")
        if attendees is not None and not isinstance(attendees, list):
            raise _bad()
        private = raw.get("visibility") in ("private", "confidential")
        fields = dict(id=raw["id"], summary=PRIVATE_TITLE if private else raw.get("summary"), start=start, end=end,
                      all_day=all_day, location=None if private else raw.get("location"),
                      status=raw.get("status"), attendee_count=len(attendees or []), private=private)
        if model is EventDetail:
            fields["description"] = None if private else raw.get("description")
        try:
            return model(**fields)
        except ValidationError:
            raise _bad() from None


    # -- writes (10.5): only when the connection has allow_write; never retried ----------------------------------------
    def create_meeting(self, data: CreateMeetingInput) -> CreateMeetingOutput:
        self._require_write()
        body = {"summary": data.summary, "start": {"dateTime": data.start, "timeZone": "UTC"},
                "end": {"dateTime": data.end, "timeZone": "UTC"}, "attendees": [{"email": a} for a in data.attendees]}
        if data.location:
            body["location"] = data.location
        if data.description:
            body["description"] = data.description
        raw = self._request("POST", _EVENTS, params={"sendUpdates": "all" if data.notify_attendees else "none"},
                            json_body=body)
        event = self._event(raw, Event)
        if event.status == "cancelled":
            raise _bad()
        return CreateMeetingOutput(event=event)
