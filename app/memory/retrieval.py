"""Memory retrieval (8.4): what does the OS know about this question, from where, and is it current?

    caller --> MemoryService.candidates (workspace + visibility + liveness enforced) --> pure ranker --> bounded result

Rules
- Read-only. It never writes memory, never calls a model and has no authority: it only returns what this caller may
  already see. Workspace isolation, `memory:read`, preference privacy, short-term visibility and expiry are all enforced
  by the store, not re-implemented here.
- Agents never receive PREFERENCE items (a user's private preferences are not agent context), even for the user they act
  for. An agent still needs `memory:read` in its scope.
- Every hit carries its provenance and honesty flags: kind, source (kind, ref, label), observed_at, expires_at,
  freshness and `stale`. Stale items are returned only flagged and down-ranked, or left out with `current_only=True`.
  The result says `has_stale` so callers do not use old facts with false confidence.
- Bounded: query <= 500 characters, limit <= 20 (default 5), at most `max_per_source` hits from one document/source
  (default 3, so one long document cannot crowd out everything else), and at most MEMORY_RETRIEVAL_MAX_CHARS of text in
  total. `truncated` is true when the workspace has more visible items than the search window (newest 1000), so a
  caller knows older items may not have been searched; `budget_truncated` when the text budget cut the list short.
- Audit: one `memory.retrieved` event per call with ids, counts and the query LENGTH. Never the query text, titles or
  content.
- Memory is DATA, never instructions: whoever puts hits in a prompt (8.5) must wrap them as untrusted.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple

from app.kernel.audit import record_event
from app.kernel.permissions import Principal
from app.memory import store as store_mod
from app.memory.errors import InvalidMemoryError, MemoryForbiddenError
from app.memory.model import Freshness, MemoryKind as K, MAX_QUERY_CHARS, SourceKind, rank, tokenize
from app.memory.store import MemoryService

DEFAULT_LIMIT = 5
MAX_RESULTS = 20
DEFAULT_MAX_PER_SOURCE = 3


@dataclass(frozen=True)
class RetrievalHit:
    memory_id: str
    kind: K
    title: str
    content: str
    source_kind: SourceKind
    source_ref: str
    source_label: Optional[str]
    observed_at: datetime
    expires_at: Optional[datetime]
    freshness: Freshness
    stale: bool
    score: float
    tags: Tuple[str, ...] = ()


@dataclass(frozen=True)
class RetrievalResult:
    hits: Tuple[RetrievalHit, ...]
    considered: int = 0                  # visible items that were searched
    truncated: bool = False              # more visible items exist than the search window
    budget_truncated: bool = False       # the text budget cut the list short
    has_stale: bool = False
    reason: Optional[str] = None         # fixed word when nothing could be searched, e.g. no_searchable_terms


class RetrievalService:
    def __init__(self, memory: MemoryService):
        self.memory, self.settings = memory, memory.settings

    def retrieve(self, principal: Principal, query: str, *, kinds: Optional[Sequence[K]] = None, limit: int = DEFAULT_LIMIT,
                 current_only: bool = False, max_per_source: int = DEFAULT_MAX_PER_SOURCE) -> RetrievalResult:
        if not principal.can("memory:read"):
            raise MemoryForbiddenError("Not allowed to read memory")
        self._validate(query, kinds, limit, max_per_source)
        if not tokenize(query):
            return self._done(principal, query, RetrievalResult((), reason="no_searchable_terms"))
        wanted = [k for k in (kinds or list(K)) if not (principal.agent is not None and k == K.PREFERENCE)]
        if not wanted:
            return self._done(principal, query, RetrievalResult((), reason="no_permitted_kinds"))
        window = store_mod.MAX_CANDIDATES
        items = self.memory.candidates(principal, wanted, limit=window)
        ranked = rank(query, items, self.memory.now(), limit=50, include_stale=not current_only)
        hits: List[RetrievalHit] = []
        per_source: Dict[Tuple[str, str], int] = {}
        chars, over_budget = 0, False
        for r in ranked:
            src = (r.item.source.kind.value, r.item.source.ref)
            if per_source.get(src, 0) >= max_per_source:
                continue
            if hits and chars + len(r.item.content) > self.settings.memory_retrieval_max_chars:
                over_budget = True
                break
            per_source[src] = per_source.get(src, 0) + 1
            chars += len(r.item.content)
            it = r.item
            hits.append(RetrievalHit(it.id, it.kind, it.title, it.content, it.source.kind, it.source.ref, it.source.label,
                                     it.observed_at, it.expires_at, r.freshness, r.freshness == Freshness.STALE,
                                     round(r.score, 6), it.tags))
            if len(hits) >= limit:
                break
        res = RetrievalResult(tuple(hits), considered=len(items), truncated=len(items) >= window,
                              budget_truncated=over_budget, has_stale=any(h.stale for h in hits))
        return self._done(principal, query, res)

    # ------------------------------------------------------------------ internals
    def _done(self, principal: Principal, query: str, res: RetrievalResult) -> RetrievalResult:
        record_event(self.memory.db, workspace_id=principal.workspace_id, event_type="memory.retrieved",
                     actor=principal.user_id,
                     payload={"results": len(res.hits), "memory_ids": [h.memory_id for h in res.hits],
                              "considered": res.considered, "stale": sum(h.stale for h in res.hits),
                              "truncated": res.truncated, "budget_truncated": res.budget_truncated,
                              "reason": res.reason, "query_chars": len(query), "agent": principal.agent})
        self.memory.db.commit()
        return res

    @staticmethod
    def _validate(query: object, kinds: object, limit: object, max_per_source: object) -> None:
        if not isinstance(query, str) or not query.strip() or len(query) > MAX_QUERY_CHARS:
            raise InvalidMemoryError("invalid_query", "A query of 1 to %d characters is required" % MAX_QUERY_CHARS)
        for name, v in (("limit", limit), ("max_per_source", max_per_source)):
            if not isinstance(v, int) or isinstance(v, bool) or not 1 <= v <= MAX_RESULTS:
                raise InvalidMemoryError("invalid_limit", "The %s must be 1 to %d" % (name, MAX_RESULTS))
        if kinds is not None and (isinstance(kinds, (str, bytes)) or not all(isinstance(k, K) for k in kinds)):
            raise InvalidMemoryError("invalid_kind", "Unknown memory kind")
