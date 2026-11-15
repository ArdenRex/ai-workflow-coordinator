"""Sales capability, "Show me qualified opportunities" (Step 11.3). Read-only, deterministic, no model involved.

Gathers CRM leads ONLY by submitting `crm.lead.list` to the execution kernel as the calling user (see kernel_read.py), then applies
fixed rules. The CRM connector exposes only name, email, company, lifecycle stage and created/updated times, so "qualified" means
exactly one thing here: the lead's CRM stage says so. Nothing is scored from message content and nothing is guessed.

  tier                 CRM stage (lower-cased, punctuation removed)   rank
  opportunity          "opportunity"                                  1
  sales_qualified      "salesqualifiedlead"                           2
  marketing_qualified  "marketingqualifiedlead"                       3
Every other stage (lead, subscriber, customer, evangelist, other, missing or unknown) is NOT listed.

Order: tier, then most recent activity first (last activity = updated_at, else created_at; a lead with no usable date comes last in
its tier), then lead id. `fresh` marks activity in the last 30 days and is shown in `reason`; it is explanation, not a separate sort
term (recency already puts active leads first). `reason` is fixed text from this module.

Limits: at most 3 pages of 100 leads are read (a remaining page marks `truncated`); at most 25 opportunities are returned (counts
still cover every qualified lead that was read). A failure on the first page returns an empty list with a fixed status; a failure on
a later page keeps what was read, sets the status and marks `truncated`. No remote error text is ever returned. The lead's email is
not returned (open the lead via `ref_tool`/`ref_id`). Names and companies come from the CRM: they are cleaned and capped by the
connector, flagged `external_text`, returned as data, and never acted on.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel

from app.capabilities.kernel_read import SourceFailed, SourceState, iso, parse_dt, read_tool, title
from app.kernel.permissions import Principal
from app.kernel.service import ToolExecutionService

Tier = Literal["opportunity", "sales_qualified", "marketing_qualified"]
TIER_BY_STAGE: Dict[str, Tier] = {"opportunity": "opportunity", "salesqualifiedlead": "sales_qualified",
                                  "marketingqualifiedlead": "marketing_qualified"}
TIER_RANK = {"opportunity": 0, "sales_qualified": 1, "marketing_qualified": 2}
TIER_REASON = {"opportunity": "In the opportunity stage", "sales_qualified": "Marked sales qualified",
               "marketing_qualified": "Marked marketing qualified"}
FRESH_REASON, STALE_REASON, NO_DATE_REASON = "active in the last 30 days", "no activity in 30+ days", "no activity date"
STALE_AFTER = timedelta(days=30)
PAGE_SIZE, MAX_PAGES, MAX_RESULTS = 100, 3, 25


class OpportunityItem(BaseModel):
    rank: int
    tier: Tier
    name: str
    company: Optional[str] = None
    external_text: bool = False
    fresh: bool
    last_activity: Optional[str] = None
    reason: str
    ref_tool: str = "crm.lead.get"
    ref_id: str


class OpportunityList(BaseModel):
    generated_at: str
    status: SourceState
    checked: int
    qualified_total: int
    truncated: bool
    counts: Dict[str, int]
    items: List[OpportunityItem]
    partial: bool


def _stage_key(raw: Any) -> str:
    return "".join(ch for ch in raw.lower() if ch.isalnum()) if isinstance(raw, str) else ""


class OpportunityService:
    def __init__(self, kernel: ToolExecutionService, *, clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self._kernel, self._clock = kernel, clock

    def list(self, principal: Principal) -> OpportunityList:
        now = self._clock().astimezone(timezone.utc).replace(microsecond=0)
        leads, status, truncated = self._read(principal)
        found: List[Tuple[tuple, Dict[str, Any]]] = []
        seen = set()
        for lead in leads:
            lead_id = lead.get("id")
            tier = TIER_BY_STAGE.get(_stage_key(lead.get("stage")))
            if tier is None or not isinstance(lead_id, str) or lead_id in seen:
                continue
            seen.add(lead_id)
            last = self._last_activity(lead, now)
            fresh = last is not None and now - last <= STALE_AFTER
            key = (TIER_RANK[tier], -last.timestamp() if last else float("inf"), lead_id)
            found.append((key, {"tier": tier, "lead": lead, "last": last, "fresh": fresh}))
        found.sort(key=lambda pair: pair[0])
        counts = {t: sum(1 for _, f in found if f["tier"] == t) for t in TIER_RANK}
        items = [self._item(i + 1, f) for i, (_, f) in enumerate(found[:MAX_RESULTS])]
        return OpportunityList(generated_at=iso(now), status=status, checked=len(leads), qualified_total=len(found),
                               truncated=truncated, counts=counts, items=items, partial=status != "ok" or truncated)

    # ------------------------------------------------------------------ internals
    def _read(self, principal: Principal) -> Tuple[List[Dict[str, Any]], SourceState, bool]:
        leads: List[Dict[str, Any]] = []
        cursor: Optional[str] = None
        for page in range(MAX_PAGES):
            data: Dict[str, Any] = {"limit": PAGE_SIZE}
            if cursor:
                data["cursor"] = cursor
            try:
                out = read_tool(self._kernel, principal, "crm.lead.list", data)
            except SourceFailed as failed:
                return leads, failed.state, bool(leads)
            leads.extend(x for x in out.get("leads", []) if isinstance(x, dict))
            cursor = out.get("next_cursor") if isinstance(out.get("next_cursor"), str) and out.get("next_cursor") else None
            if cursor is None:
                return leads, "ok", False
        return leads, "ok", True                       # pages used up and the CRM still has more

    @staticmethod
    def _last_activity(lead: Dict[str, Any], now: datetime) -> Optional[datetime]:
        for field in ("updated_at", "created_at"):
            value = parse_dt(lead.get(field))
            if value is not None and value <= now + timedelta(minutes=5):      # a date in the future is not evidence of activity
                return value
        return None

    @staticmethod
    def _item(rank: int, f: Dict[str, Any]) -> OpportunityItem:
        lead, tier, last = f["lead"], f["tier"], f["last"]
        name = " ".join(p for p in (lead.get("first_name"), lead.get("last_name")) if isinstance(p, str) and p)
        shown, ext = title(name or lead.get("email"), "(unnamed lead)")
        company = lead.get("company") if isinstance(lead.get("company"), str) and lead.get("company").strip() else None
        activity = FRESH_REASON if f["fresh"] else (STALE_REASON if last is not None else NO_DATE_REASON)
        return OpportunityItem(rank=rank, tier=tier, name=shown, company=company[:200] if company else None,
                               external_text=ext or company is not None, fresh=f["fresh"],
                               last_activity=iso(last) if last else None, reason=f"{TIER_REASON[tier]}; {activity}",
                               ref_id=lead["id"])
