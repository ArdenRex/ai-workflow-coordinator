"""Business memory model: what may be remembered, where it came from, how fresh it is, how it ranks.
Pure data and logic: no database, no LLM, no I/O. Persistence (8.2), ingestion (8.3), retrieval (8.4), and use by
agents/planning (8.5) all build on these rules.

Four kinds of memory, with different lifetimes
    SHORT_TERM   needed for the current task. Expires within hours (max 24h).
    OPERATIONAL  about ongoing work/workflows. Expires (default 30 days, max 1 year).
    KNOWLEDGE    durable business facts (company, products, policies, processes). Never expires on its own but
                 goes STALE after a review period, so the OS does not use old facts with false confidence.
    PREFERENCE   one user's own preferences. Belongs to exactly one user and is private to them.

Safety properties, enforced here and fail-closed
- Every item names its SOURCE (who/what told us) and when it was observed: "where did I learn it?"
- Governed writes: only humans, documents and connectors may create KNOWLEDGE or PREFERENCE. Agents and the system may
  only write SHORT_TERM and OPERATIONAL. Agent-derived text can never be promoted to durable business knowledge.
- Bounded: title/content/tag/ttl limits, no control characters, no NUL.
- No secrets: content that looks like a credential (API key, bearer token, private key, password assignment) is
  rejected, not stored. The error never echoes the content.
- Fresh or not: `freshness()` is a pure function of kind and timestamps. EXPIRED items are never returned;
  STALE items are returned only flagged and down-ranked.
- Deterministic retrieval ranking: keyword overlap (title > tags > content) x freshness x source trust. Ties break by
  newest then id. No embeddings or new frameworks.
- Workspace ownership is part of the item: "which workspace owns it?" (enforcement in the store, 8.2).
Memory is DATA, never instructions: whoever puts it in a prompt must wrap it as untrusted (8.5).
"""
import enum
import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from app.memory.errors import InvalidMemoryError

MAX_TITLE_CHARS = 120
MAX_CONTENT_CHARS = 4000
MAX_TAGS = 8
MAX_REF_CHARS = 200
MAX_LABEL_CHARS = 120
MAX_QUERY_CHARS = 500
TAG_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,31}$")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_DAY = 86400


class MemoryKind(str, enum.Enum):
    SHORT_TERM = "short_term"
    OPERATIONAL = "operational"
    KNOWLEDGE = "knowledge"
    PREFERENCE = "preference"


class SourceKind(str, enum.Enum):
    USER = "user"              # a person told us directly
    DOCUMENT = "document"      # an uploaded business document
    CONNECTOR = "connector"    # read from a connected external system
    SYSTEM = "system"          # derived by the OS itself (e.g. a run outcome)
    AGENT = "agent"            # proposed by an AI agent


class Freshness(str, enum.Enum):
    FRESH = "fresh"
    AGING = "aging"
    STALE = "stale"
    EXPIRED = "expired"


# Which sources may create which kinds. Anything not listed is refused.
WRITABLE_KINDS = {
    SourceKind.USER: {MemoryKind.SHORT_TERM, MemoryKind.OPERATIONAL, MemoryKind.KNOWLEDGE, MemoryKind.PREFERENCE},
    SourceKind.DOCUMENT: {MemoryKind.KNOWLEDGE, MemoryKind.OPERATIONAL},
    SourceKind.CONNECTOR: {MemoryKind.KNOWLEDGE, MemoryKind.OPERATIONAL, MemoryKind.SHORT_TERM},
    SourceKind.SYSTEM: {MemoryKind.SHORT_TERM, MemoryKind.OPERATIONAL},
    SourceKind.AGENT: {MemoryKind.SHORT_TERM, MemoryKind.OPERATIONAL},
}
# Ranking weight per source: how much we lean on it when relevance is equal.
TRUST = {SourceKind.USER: 1.0, SourceKind.DOCUMENT: 1.0, SourceKind.CONNECTOR: 0.9,
         SourceKind.SYSTEM: 0.8, SourceKind.AGENT: 0.6}
# Lifetime per kind: (default ttl, max ttl) in seconds; None = no expiry. KNOWLEDGE/PREFERENCE may not be given a ttl.
TTL = {MemoryKind.SHORT_TERM: (3600, _DAY), MemoryKind.OPERATIONAL: (30 * _DAY, 365 * _DAY),
       MemoryKind.KNOWLEDGE: (None, None), MemoryKind.PREFERENCE: (None, None)}
# After this age without being refreshed an item with no expiry is STALE (needs review before confident use).
REVIEW_AFTER = {MemoryKind.KNOWLEDGE: 180 * _DAY, MemoryKind.PREFERENCE: 365 * _DAY}
_FRESHNESS_WEIGHT = {Freshness.FRESH: 1.0, Freshness.AGING: 0.8, Freshness.STALE: 0.4, Freshness.EXPIRED: 0.0}

_SECRET_PATTERNS = [re.compile(p, re.I) for p in (
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    r"\bsk-[a-z0-9_\-]{16,}",
    r"\b(?:ghp|gho|ghs|github_pat)_[a-z0-9_]{20,}",
    r"\bAKIA[0-9A-Z]{16}\b",
    r"\bxox[abprs]-[a-z0-9-]{10,}",
    r"\bbearer\s+[a-z0-9._\-]{20,}",
    r"\beyJ[a-z0-9_\-]{10,}\.[a-z0-9_\-]{10,}\.[a-z0-9_\-]{10,}",          # JWT
    r"\b(?:password|passwd|pwd|secret|api[_-]?key|token)\s*[:=]\s*\S{6,}",
)]


def contains_secret(text: str) -> bool:
    return any(p.search(text) for p in _SECRET_PATTERNS)


@dataclass(frozen=True)
class SourceRef:
    """Where a piece of memory came from. `ref` is an id/slug (a user id, document id, connector or run id), not content."""
    kind: SourceKind
    ref: str
    label: Optional[str] = None

    def __post_init__(self):
        if not isinstance(self.kind, SourceKind):
            raise InvalidMemoryError("invalid_source", "Unknown source kind")
        if not isinstance(self.ref, str) or not (1 <= len(self.ref) <= MAX_REF_CHARS) or _CONTROL_RE.search(self.ref):
            raise InvalidMemoryError("invalid_source", "A source reference of 1 to %d characters is required" % MAX_REF_CHARS)
        if self.label is not None and (not isinstance(self.label, str) or len(self.label) > MAX_LABEL_CHARS
                                       or _CONTROL_RE.search(self.label)):
            raise InvalidMemoryError("invalid_source", "The source label is invalid")


def _text(value: Any, code: str, name: str, max_chars: int) -> str:
    if not isinstance(value, str):
        raise InvalidMemoryError(code, f"{name} must be text")
    v = value.strip()
    if not v or len(v) > max_chars:
        raise InvalidMemoryError(code, f"{name} must be 1 to {max_chars} characters")
    if _CONTROL_RE.search(v):
        raise InvalidMemoryError(code, f"{name} contains control characters")
    return v


@dataclass(frozen=True)
class MemoryDraft:
    """A proposed memory write, validated on construction. It carries no workspace: the store binds that."""
    kind: MemoryKind
    title: str
    content: str
    source: SourceRef
    tags: Tuple[str, ...] = ()
    ttl_seconds: Optional[int] = None
    owner_user_id: Optional[str] = None      # required for PREFERENCE, forbidden otherwise
    scope_ref: Optional[str] = None          # e.g. the run/plan a SHORT_TERM item belongs to

    def __post_init__(self):
        if not isinstance(self.kind, MemoryKind):
            raise InvalidMemoryError("invalid_kind", "Unknown memory kind")
        if not isinstance(self.source, SourceRef):
            raise InvalidMemoryError("invalid_source", "A source is required")
        if self.kind not in WRITABLE_KINDS[self.source.kind]:
            raise InvalidMemoryError("source_not_allowed",
                                     "This source may not create this kind of memory")
        object.__setattr__(self, "title", _text(self.title, "invalid_title", "Title", MAX_TITLE_CHARS))
        object.__setattr__(self, "content", _text(self.content, "invalid_content", "Content", MAX_CONTENT_CHARS))
        if contains_secret(self.title) or contains_secret(self.content):
            raise InvalidMemoryError("secret_detected", "Content that looks like a credential cannot be stored")
        tags = tuple(self.tags)
        if len(tags) > MAX_TAGS or len(set(tags)) != len(tags) or not all(isinstance(t, str) and TAG_RE.match(t) for t in tags):
            raise InvalidMemoryError("invalid_tags", "Tags must be up to %d unique lowercase slugs" % MAX_TAGS)
        object.__setattr__(self, "tags", tags)
        default, maximum = TTL[self.kind]
        if self.ttl_seconds is not None:
            if maximum is None:
                raise InvalidMemoryError("ttl_not_allowed", "This kind of memory does not take a lifetime")
            if isinstance(self.ttl_seconds, bool) or not isinstance(self.ttl_seconds, int) or not (60 <= self.ttl_seconds <= maximum):
                raise InvalidMemoryError("invalid_ttl", "The lifetime is outside the allowed range")
        if self.kind == MemoryKind.PREFERENCE:
            if not self.owner_user_id:
                raise InvalidMemoryError("owner_required", "A preference belongs to one user")
            if self.source.kind != SourceKind.USER or self.source.ref != self.owner_user_id:
                raise InvalidMemoryError("source_not_allowed", "Only a user may record their own preference")
        elif self.owner_user_id is not None:
            raise InvalidMemoryError("owner_not_allowed", "Only preferences have an owner")
        if self.scope_ref is not None:
            object.__setattr__(self, "scope_ref", _text(self.scope_ref, "invalid_scope", "Scope", MAX_REF_CHARS))

    def effective_ttl(self) -> Optional[int]:
        return self.ttl_seconds if self.ttl_seconds is not None else TTL[self.kind][0]

    def content_digest(self) -> str:
        """Stable fingerprint for de-duplication; independent of tags and timing."""
        raw = f"{self.kind.value}\x1f{' '.join(self.title.lower().split())}\x1f{' '.join(self.content.lower().split())}"
        return hashlib.sha256(raw.encode()).hexdigest()


@dataclass(frozen=True)
class MemoryItem:
    """A stored memory as the rest of the OS sees it. Built by the store; immutable."""
    id: str
    workspace_id: str
    kind: MemoryKind
    title: str
    content: str
    source: SourceRef
    observed_at: datetime
    expires_at: Optional[datetime] = None
    tags: Tuple[str, ...] = ()
    owner_user_id: Optional[str] = None
    scope_ref: Optional[str] = None

    @classmethod
    def from_draft(cls, draft: MemoryDraft, *, id: str, workspace_id: str, now: datetime) -> "MemoryItem":
        ttl = draft.effective_ttl()
        return cls(id=id, workspace_id=workspace_id, kind=draft.kind, title=draft.title, content=draft.content,
                   source=draft.source, observed_at=now, expires_at=now + timedelta(seconds=ttl) if ttl else None,
                   tags=draft.tags, owner_user_id=draft.owner_user_id, scope_ref=draft.scope_ref)


def freshness(item: MemoryItem, now: datetime) -> Freshness:
    """Pure: EXPIRED once past expiry; otherwise STALE after the review age (no-expiry kinds) or AGING in the last quarter
    of a bounded lifetime. A future-dated observation is treated as just observed (never fresher than now)."""
    if item.expires_at is not None and now >= item.expires_at:
        return Freshness.EXPIRED
    age = max((now - item.observed_at).total_seconds(), 0.0)
    if item.expires_at is not None:
        life = (item.expires_at - item.observed_at).total_seconds()
        return Freshness.AGING if life > 0 and age >= 0.75 * life else Freshness.FRESH
    review = REVIEW_AFTER.get(item.kind)
    if review is not None:
        if age >= review:
            return Freshness.STALE
        return Freshness.AGING if age >= 0.75 * review else Freshness.FRESH
    return Freshness.FRESH


def explain(item: MemoryItem, now: datetime) -> Dict[str, Any]:
    """The four questions: what do I know, where did I learn it, is it current, which workspace owns it."""
    return {"id": item.id, "kind": item.kind.value, "title": item.title, "workspace_id": item.workspace_id,
            "source": {"kind": item.source.kind.value, "ref": item.source.ref, "label": item.source.label},
            "observed_at": item.observed_at.isoformat(), "freshness": freshness(item, now).value,
            "expires_at": item.expires_at.isoformat() if item.expires_at else None}


# ------------------------------------------------------------------ retrieval ranking (pure)
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOP = frozenset("a an and are as at be by for from has have how i in is it its of on or our that the their this to "
                  "was we what when where which who why will with you your".split())


def tokenize(text: str) -> List[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOP and len(t) > 1]


@dataclass(frozen=True)
class Ranked:
    item: MemoryItem
    score: float
    freshness: Freshness


def score_item(query_tokens: Sequence[str], item: MemoryItem, now: datetime) -> Tuple[float, Freshness]:
    """keyword overlap (title x3, tags x2, content x1, each token counted once per field) x freshness x source trust."""
    fresh = freshness(item, now)
    if not query_tokens or fresh == Freshness.EXPIRED:
        return 0.0, fresh
    title, tags, content = set(tokenize(item.title)), set(tokenize(" ".join(item.tags))), set(tokenize(item.content))
    qs = set(query_tokens)
    raw = 3 * len(qs & title) + 2 * len(qs & tags) + len(qs & content)
    return raw / len(qs) * _FRESHNESS_WEIGHT[fresh] * TRUST[item.source.kind], fresh


def rank(query: str, items: Iterable[MemoryItem], now: datetime, limit: int = 10, *, include_stale: bool = True) -> List[Ranked]:
    """Deterministic: highest score first, then newest observation, then id. Zero-score and EXPIRED items never appear."""
    if not isinstance(query, str) or len(query) > MAX_QUERY_CHARS:
        raise InvalidMemoryError("invalid_query", "A query of up to %d characters is required" % MAX_QUERY_CHARS)
    if not isinstance(limit, int) or isinstance(limit, bool) or not (1 <= limit <= 50):
        raise InvalidMemoryError("invalid_limit", "The limit must be 1 to 50")
    q = tokenize(query)
    out = []
    for it in items:
        s, f = score_item(q, it, now)
        if s > 0 and (include_stale or f != Freshness.STALE):
            out.append(Ranked(it, s, f))
    out.sort(key=lambda r: (-r.score, -r.item.observed_at.timestamp(), r.item.id))
    return out[:limit]
