"""Memory store: persistence, access rules, lifecycle and content-free audit for business memory.

    ACTIVE --supersede--> SUPERSEDED (new ACTIVE version)     ACTIVE --delete--> DELETED     ACTIVE --lifetime ends--> EXPIRED

Design rules (same family as runs and plans)
- Every status change is a compare-and-swap UPDATE restricted to the workspace and ACTIVE, so a dead row never comes
  back and two writers cannot both win. Memory is always read and written inside one workspace; an id from another
  workspace is indistinguishable from a missing one (MemoryNotFoundError).
- Content does not outlive its usefulness: a superseded, deleted or expired row has its title, content and tags PURGED
  in the same transaction (metadata stays for provenance and audit). A delete therefore really deletes.
- Who sees what: `memory:read` is needed for everything. Preferences are visible ONLY to their owner (not even admins).
  Short-term items are visible to their creator and to admins. Operational and knowledge items are visible to every
  reader in the workspace. Expired-but-unswept items are treated as gone.
- Who writes what (on top of the pure draft rules): `memory:write`; humans write as themselves (a source cannot name
  another user); KNOWLEDGE needs `memory:manage` (admins curate durable business facts); agents write only as their own
  agent, only short-term/operational, only with `memory:write` in their scope, and may change only what they created.
  Documents, connectors and the system are not "callers": trusted ingestion uses `create_trusted` (admin only).
- Bounded: MEMORY_MAX_ITEMS active items per workspace, MEMORY_MAX_PREFERENCES_PER_USER per user.
- No duplicates: one ACTIVE row per (kind, owner/creator, content) via a unique dedupe key; a repeated write returns the
  existing item.
- Audit: `memory.created|superseded|deleted|expired` carry ids, kind, source kind, version and sizes. Never titles,
  content or tags.
- Documents (8.3): a document is a set of ACTIVE chunks sharing one DOCUMENT source ref. `replace_document` swaps the
  whole set in ONE transaction (old chunks purged, new ones inserted, versions and lineage carried over by position);
  `delete_document` purges them all. Both are trusted (human admins only) and audit ONE content-free event per call.
"""
import hashlib
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings
from app.kernel.audit import record_event
from app.kernel.permissions import Principal
from app.memory.errors import (InvalidMemoryError, MemoryConflictError, MemoryForbiddenError, MemoryLimitError,
                               MemoryNotFoundError)
from app.memory.model import MemoryDraft, MemoryItem, MemoryKind as K, SourceKind as SK, SourceRef
from app.models.enums import MemoryStatus as M
from app.models.memory import MemoryRecord

TRUSTED_SOURCES = {SK.DOCUMENT, SK.CONNECTOR, SK.SYSTEM}
MAX_LIST = 200
MAX_CANDIDATES = 1000


def chunk_scope(digest: str, index: int, total: int) -> str:
    """`scope_ref` of a document chunk: which version of the document, which part, of how many."""
    return f"{digest[:32]}:{index}:{total}"


def parse_chunk_scope(scope: Optional[str]) -> Optional[Tuple[str, int, int]]:
    try:
        digest, i, n = (scope or "").split(":")
        return (digest, int(i), int(n)) if digest and 0 <= int(i) < int(n) else None
    except ValueError:
        return None


@dataclass(frozen=True)
class DocumentInfo:
    """A document as a reader sees it: no content, only what/where/how fresh."""
    document_id: str
    title: Optional[str]
    kind: K
    chunks: int
    observed_at: datetime


def to_item(rec: MemoryRecord) -> MemoryItem:
    return MemoryItem(id=rec.id, workspace_id=rec.workspace_id, kind=rec.kind, title=rec.title, content=rec.content,
                      source=SourceRef(rec.source_kind, rec.source_ref, rec.source_label),
                      observed_at=_aware(rec.observed_at), expires_at=_aware(rec.expires_at), tags=tuple(rec.tags or ()),
                      owner_user_id=rec.owner_user_id, scope_ref=rec.scope_ref)


def _aware(d: Optional[datetime]) -> Optional[datetime]:
    return d if d is None or d.tzinfo else d.replace(tzinfo=timezone.utc)


class MemoryService:
    def __init__(self, db: Session, settings: Settings, *, clock: Optional[Callable[[], datetime]] = None):
        self.db, self.settings = db, settings
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def now(self) -> datetime:
        return self._clock()

    # ---------------------------------------------------------------- create
    def create(self, principal: Principal, draft: MemoryDraft) -> MemoryRecord:
        self._check_writer(principal, draft)
        return self._insert(principal, draft)

    def create_trusted(self, principal: Principal, draft: MemoryDraft) -> MemoryRecord:
        """For ingestion and system code (documents, connectors, the OS itself). Human admins only; the source must be
        a trusted kind (never a user or an agent, which go through `create`)."""
        self.check_trusted(principal)
        if draft.source.kind not in TRUSTED_SOURCES:
            raise MemoryForbiddenError("This source must use the normal write path")
        return self._insert(principal, draft)

    # ---------------------------------------------------------------- read
    def get(self, principal: Principal, memory_id: str) -> MemoryRecord:
        self._need_read(principal)
        rec = self._load(principal.workspace_id, memory_id)
        if rec.status != M.ACTIVE or not self._live(rec) or not self._can_see(principal, rec):
            raise MemoryNotFoundError("Memory not found")
        return rec

    def list(self, principal: Principal, *, kind: Optional[K] = None, limit: int = 50) -> List[MemoryRecord]:
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_LIST:
            raise InvalidMemoryError("invalid_limit", f"The limit must be 1 to {MAX_LIST}")
        return self._visible(principal, [kind] if kind else None, limit)

    def candidates(self, principal: Principal, kinds: Optional[Sequence[K]] = None,
                   limit: int = MAX_CANDIDATES) -> List[MemoryItem]:
        """Live memory this caller may see, as pure `MemoryItem`s (newest first), for ranking by the retrieval layer."""
        return [to_item(r) for r in self._visible(principal, list(kinds) if kinds else None, min(limit, MAX_CANDIDATES))]

    # ---------------------------------------------------------------- supersede / delete
    def supersede(self, principal: Principal, memory_id: str, draft: MemoryDraft) -> MemoryRecord:
        """Replaces an item with a new version of the same kind. The old version's content is purged immediately."""
        old = self.get(principal, memory_id)
        self._check_modify(principal, old)
        self._check_writer(principal, draft)
        if draft.kind != old.kind or draft.owner_user_id != old.owner_user_id:
            raise InvalidMemoryError("kind_mismatch", "A new version must keep the same kind and owner")
        now = self._clock()
        key = self._dedupe_key(principal, draft)
        clash = self._active_by_key(principal.workspace_id, key)
        if clash is not None and clash.id != old.id:
            raise MemoryConflictError("The same memory already exists")
        res = self.db.execute(update(MemoryRecord).where(
            MemoryRecord.id == old.id, MemoryRecord.workspace_id == old.workspace_id, MemoryRecord.status == M.ACTIVE)
            .values(self._purge(M.SUPERSEDED, now, principal.user_id)))
        if res.rowcount != 1:
            self.db.rollback()
            raise MemoryConflictError("The memory changed; try again")
        new = self._build(principal, draft, now, key, version=old.version + 1, lineage=old.lineage_id, supersedes=old.id)
        self.db.add(new)
        try:
            self.db.flush()
        except IntegrityError:
            self.db.rollback()
            raise MemoryConflictError("The same memory already exists")
        self._event("memory.superseded", principal, new, previous_id=old.id)
        self.db.commit()
        self.db.refresh(new)
        return new

    def delete(self, principal: Principal, memory_id: str) -> MemoryRecord:
        """Deletes for real: the content is purged. Idempotent. Not-visible and missing are the same 404."""
        self._need_read(principal)
        rec = self._load(principal.workspace_id, memory_id)
        if not self._can_see(principal, rec):
            raise MemoryNotFoundError("Memory not found")
        if rec.status != M.ACTIVE:
            return rec
        self._check_modify(principal, rec)
        now = self._clock()
        res = self.db.execute(update(MemoryRecord).where(
            MemoryRecord.id == rec.id, MemoryRecord.workspace_id == rec.workspace_id, MemoryRecord.status == M.ACTIVE)
            .values(self._purge(M.DELETED, now, principal.user_id)))
        if res.rowcount == 1:
            self._event("memory.deleted", principal, rec)
        self.db.commit()
        self.db.refresh(rec)
        return rec

    def expire_overdue(self, workspace_id: str) -> int:
        """Sweeps one workspace: expired items become EXPIRED with their content purged. Safe to repeat. For the
        scheduler (Step 9) and maintenance; users never call it."""
        now, n = self._clock(), 0
        due = list(self.db.scalars(select(MemoryRecord).where(
            MemoryRecord.workspace_id == workspace_id, MemoryRecord.status == M.ACTIVE,
            MemoryRecord.expires_at.is_not(None), MemoryRecord.expires_at <= now)))
        for rec in due:
            res = self.db.execute(update(MemoryRecord).where(
                MemoryRecord.id == rec.id, MemoryRecord.workspace_id == workspace_id, MemoryRecord.status == M.ACTIVE)
                .values(self._purge(M.EXPIRED, now, None)))
            if res.rowcount == 1:
                n += 1
                record_event(self.db, workspace_id=workspace_id, event_type="memory.expired", actor=None,
                             payload={"memory_id": rec.id, "kind": rec.kind.value, "version": rec.version})
        self.db.commit()
        return n


    # ---------------------------------------------------------------- documents (trusted ingestion, 8.3)
    @staticmethod
    def check_trusted(principal: Principal) -> None:
        if principal.agent is not None or not principal.can("memory:manage"):
            raise MemoryForbiddenError("Not allowed to record trusted memory")

    def live_document_scopes(self, principal: Principal, document_id: str) -> List[str]:
        """The `scope_ref` of every live chunk of a document (to tell whether a new upload changes anything)."""
        self.check_trusted(principal)
        return [r.scope_ref or "" for r in self._doc_records(principal.workspace_id, document_id) if self._live(r)]

    def list_documents(self, principal: Principal) -> List[DocumentInfo]:
        """Documents this caller may know about (their chunks are readable by every reader). No content returned."""
        self._need_read(principal)
        docs: Dict[str, List[MemoryRecord]] = {}
        for rec in self.db.scalars(select(MemoryRecord).where(
                MemoryRecord.workspace_id == principal.workspace_id, MemoryRecord.status == M.ACTIVE,
                MemoryRecord.source_kind == SK.DOCUMENT).order_by(MemoryRecord.source_ref, MemoryRecord.id)):
            if self._live(rec) and self._can_see(principal, rec):
                docs.setdefault(rec.source_ref, []).append(rec)
        return [DocumentInfo(ref, recs[0].source_label, recs[0].kind, len(recs), max(_aware(r.observed_at) for r in recs))
                for ref, recs in sorted(docs.items())]

    def replace_document(self, principal: Principal, document_id: str, drafts: Sequence[MemoryDraft]) -> Tuple[int, int, int]:
        """Atomically makes `drafts` the complete, current set of chunks of one document. Chunks are matched by position:
        a replaced chunk keeps its lineage and gets the next version; extra new chunks start new lineages; leftover old
        chunks are deleted. Old content is purged in the same transaction. Returns (added, replaced, removed)."""
        self.check_trusted(principal)
        if not drafts:
            raise InvalidMemoryError("invalid_document", "A document needs at least one chunk")
        for d in drafts:
            if d.source.kind != SK.DOCUMENT or d.source.ref != document_id or d.kind not in (K.KNOWLEDGE, K.OPERATIONAL):
                raise MemoryForbiddenError("A document chunk must be a document-sourced knowledge or operational item")
        ws, now = principal.workspace_id, self._clock()
        old = self._doc_records(ws, document_id)
        total = self.db.scalar(select(func.count()).select_from(MemoryRecord).where(
            MemoryRecord.workspace_id == ws, MemoryRecord.status == M.ACTIVE))
        if total - len(old) + len(drafts) > self.settings.memory_max_items:
            raise MemoryLimitError("This workspace has reached its memory limit")
        by_pos: Dict[int, Tuple[str, str, int]] = {}                    # position -> (id, lineage, version)
        for rec in old:
            pos = parse_chunk_scope(rec.scope_ref)
            if pos is not None and pos[1] < len(drafts) and pos[1] not in by_pos:
                by_pos[pos[1]] = (rec.id, rec.lineage_id, rec.version)
        replaced_ids = {v[0] for v in by_pos.values()}
        for rec in old:                                                 # purge first so dedupe keys are free again
            status = M.SUPERSEDED if rec.id in replaced_ids else M.DELETED
            res = self.db.execute(update(MemoryRecord).where(
                MemoryRecord.id == rec.id, MemoryRecord.workspace_id == ws, MemoryRecord.status == M.ACTIVE)
                .values(self._purge(status, now, principal.user_id)))
            if res.rowcount != 1:
                self.db.rollback()
                raise MemoryConflictError("The document changed; try again")
        chars = 0
        for i, draft in enumerate(drafts):
            prev = by_pos.get(i)
            new = self._build(principal, draft, now, self._dedupe_key(principal, draft),
                              version=prev[2] + 1 if prev else 1, lineage=prev[1] if prev else None,
                              supersedes=prev[0] if prev else None)
            self.db.add(new)
            try:
                self.db.flush()
            except IntegrityError:
                self.db.rollback()
                raise MemoryConflictError("The document changed; try again")
            if prev is None:
                new.lineage_id = new.id
            chars += new.content_chars
        removed = len(old) - len(replaced_ids)
        record_event(self.db, workspace_id=ws, event_type="memory.document_ingested", actor=principal.user_id,
                     payload={"document_id": document_id, "kind": drafts[0].kind.value, "chunks": len(drafts),
                              "replaced": len(replaced_ids), "added": len(drafts) - len(replaced_ids),
                              "removed": removed, "content_chars": chars})
        self.db.commit()
        return len(drafts) - len(replaced_ids), len(replaced_ids), removed

    def refresh_document(self, principal: Principal, document_id: str) -> int:
        """Marks a knowledge document as reviewed (an identical re-upload): its chunks count as freshly observed."""
        self.check_trusted(principal)
        now = self._clock()
        res = self.db.execute(update(MemoryRecord).where(
            MemoryRecord.workspace_id == principal.workspace_id, MemoryRecord.source_kind == SK.DOCUMENT,
            MemoryRecord.source_ref == document_id, MemoryRecord.status == M.ACTIVE, MemoryRecord.kind == K.KNOWLEDGE)
            .values(observed_at=now, updated_at=now))
        if res.rowcount:
            record_event(self.db, workspace_id=principal.workspace_id, event_type="memory.document_refreshed",
                         actor=principal.user_id, payload={"document_id": document_id, "chunks": res.rowcount})
        self.db.commit()
        return res.rowcount

    def delete_document(self, principal: Principal, document_id: str) -> int:
        """Deletes every chunk of a document for real (content purged). Idempotent; returns how many were removed."""
        self.check_trusted(principal)
        ws, now, n = principal.workspace_id, self._clock(), 0
        for rec in self._doc_records(ws, document_id):
            res = self.db.execute(update(MemoryRecord).where(
                MemoryRecord.id == rec.id, MemoryRecord.workspace_id == ws, MemoryRecord.status == M.ACTIVE)
                .values(self._purge(M.DELETED, now, principal.user_id)))
            n += res.rowcount
        if n:
            record_event(self.db, workspace_id=ws, event_type="memory.document_deleted", actor=principal.user_id,
                         payload={"document_id": document_id, "chunks": n})
        self.db.commit()
        return n

    def _doc_records(self, workspace_id: str, document_id: str) -> List[MemoryRecord]:
        return list(self.db.scalars(select(MemoryRecord).where(
            MemoryRecord.workspace_id == workspace_id, MemoryRecord.source_kind == SK.DOCUMENT,
            MemoryRecord.source_ref == document_id, MemoryRecord.status == M.ACTIVE).order_by(MemoryRecord.id)))

    # ---------------------------------------------------------------- internals
    def _insert(self, principal: Principal, draft: MemoryDraft) -> MemoryRecord:
        self._need_write(principal)
        ws, now = principal.workspace_id, self._clock()
        key = self._dedupe_key(principal, draft)
        existing = self._active_by_key(ws, key)
        if existing is not None:
            return existing
        total = self.db.scalar(select(func.count()).select_from(MemoryRecord).where(
            MemoryRecord.workspace_id == ws, MemoryRecord.status == M.ACTIVE))
        if total >= self.settings.memory_max_items:
            raise MemoryLimitError("This workspace has reached its memory limit")
        if draft.kind == K.PREFERENCE:
            mine = self.db.scalar(select(func.count()).select_from(MemoryRecord).where(
                MemoryRecord.workspace_id == ws, MemoryRecord.status == M.ACTIVE, MemoryRecord.kind == K.PREFERENCE,
                MemoryRecord.owner_user_id == draft.owner_user_id))
            if mine >= self.settings.memory_max_preferences_per_user:
                raise MemoryLimitError("The preference limit has been reached")
        rec = self._build(principal, draft, now, key, version=1, lineage=None, supersedes=None)
        self.db.add(rec)
        try:
            self.db.flush()
        except IntegrityError:                                    # lost a race with an identical write
            self.db.rollback()
            existing = self._active_by_key(ws, key)
            if existing is None:
                raise
            return existing
        rec.lineage_id = rec.id
        self._event("memory.created", principal, rec)
        self.db.commit()
        self.db.refresh(rec)
        return rec

    def _build(self, principal: Principal, draft: MemoryDraft, now: datetime, key: str, *, version: int,
               lineage: Optional[str], supersedes: Optional[str]) -> MemoryRecord:
        item = MemoryItem.from_draft(draft, id="-", workspace_id=principal.workspace_id, now=now)
        rec = MemoryRecord(workspace_id=principal.workspace_id, kind=draft.kind, status=M.ACTIVE, title=draft.title,
                           content=draft.content, tags=list(draft.tags), content_chars=len(draft.content),
                           content_digest=draft.content_digest(), dedupe_key=key, source_kind=draft.source.kind,
                           source_ref=draft.source.ref, source_label=draft.source.label, observed_at=now,
                           expires_at=item.expires_at, owner_user_id=draft.owner_user_id, scope_ref=draft.scope_ref,
                           created_by=principal.user_id, created_by_agent=principal.agent, version=version,
                           lineage_id=lineage or "pending", supersedes_id=supersedes)
        return rec

    @staticmethod
    def _dedupe_key(principal: Principal, draft: MemoryDraft) -> str:
        who = draft.owner_user_id or (principal.user_id if draft.kind == K.SHORT_TERM else "")
        raw = f"{draft.kind.value}|{who}|{draft.content_digest()}"
        if draft.source.kind == SK.DOCUMENT:                    # the same text in two documents stays two memories
            raw += f"|doc:{draft.source.ref}"
        return "m:" + hashlib.sha256(raw.encode()).hexdigest()

    def _purge(self, status: M, now: datetime, actor: Optional[str]) -> dict:
        return dict(status=status, title="", content="", tags=[], dedupe_key=None, ended_at=now, ended_by=actor,
                    updated_at=now)

    def _active_by_key(self, workspace_id: str, key: str) -> Optional[MemoryRecord]:
        return self.db.scalar(select(MemoryRecord).where(
            MemoryRecord.workspace_id == workspace_id, MemoryRecord.dedupe_key == key, MemoryRecord.status == M.ACTIVE))

    def _load(self, workspace_id: str, memory_id: str) -> MemoryRecord:
        rec = self.db.scalar(select(MemoryRecord).where(MemoryRecord.id == memory_id,
                                                        MemoryRecord.workspace_id == workspace_id)) \
            if isinstance(memory_id, str) else None
        if rec is None:
            raise MemoryNotFoundError("Memory not found")
        return rec

    def _live(self, rec: MemoryRecord) -> bool:
        exp = _aware(rec.expires_at)
        return exp is None or exp > self._clock()

    def _visible(self, principal: Principal, kinds: Optional[Sequence[K]], limit: int) -> List[MemoryRecord]:
        self._need_read(principal)
        q = select(MemoryRecord).where(MemoryRecord.workspace_id == principal.workspace_id,
                                       MemoryRecord.status == M.ACTIVE)
        if kinds:
            q = q.where(MemoryRecord.kind.in_(list(kinds)))
        q = q.where(or_(MemoryRecord.kind != K.PREFERENCE, MemoryRecord.owner_user_id == principal.user_id))
        q = q.order_by(MemoryRecord.observed_at.desc(), MemoryRecord.id)
        out: List[MemoryRecord] = []
        for rec in self.db.scalars(q):                           # second, independent check in code
            if self._live(rec) and self._can_see(principal, rec):
                out.append(rec)
                if len(out) >= limit:
                    break
        return out

    # -- access rules
    @staticmethod
    def _need_read(principal: Principal) -> None:
        if not principal.can("memory:read"):
            raise MemoryForbiddenError("Not allowed to read memory")

    @staticmethod
    def _need_write(principal: Principal) -> None:
        if not principal.can("memory:write"):
            raise MemoryForbiddenError("Not allowed to write memory")

    @staticmethod
    def _can_see(principal: Principal, rec: MemoryRecord) -> bool:
        if rec.workspace_id != principal.workspace_id:
            return False
        if rec.kind == K.PREFERENCE:
            return rec.owner_user_id == principal.user_id
        if rec.kind == K.SHORT_TERM:
            return rec.created_by == principal.user_id or principal.can("memory:manage")
        return True

    def _check_writer(self, principal: Principal, draft: MemoryDraft) -> None:
        self._need_write(principal)
        src = draft.source
        if principal.agent is not None:
            if src.kind != SK.AGENT or src.ref != principal.agent:
                raise MemoryForbiddenError("An agent may only write as itself")
        else:
            if src.kind != SK.USER or src.ref != principal.user_id:
                raise MemoryForbiddenError("A source must be the person writing it")
        if draft.kind == K.KNOWLEDGE and not principal.can("memory:manage"):
            raise MemoryForbiddenError("Only administrators may record business knowledge")
        if draft.kind == K.PREFERENCE and draft.owner_user_id != principal.user_id:
            raise MemoryForbiddenError("A preference can only be recorded by its owner")

    def _check_modify(self, principal: Principal, rec: MemoryRecord) -> None:
        self._need_write(principal)
        if principal.agent is not None:
            if rec.created_by_agent != principal.agent or rec.kind not in (K.SHORT_TERM, K.OPERATIONAL):
                raise MemoryForbiddenError("An agent may only change what it created")
        elif rec.kind == K.PREFERENCE:
            if rec.owner_user_id != principal.user_id:
                raise MemoryForbiddenError("Not allowed to change this memory")
        elif rec.kind == K.KNOWLEDGE:
            if not principal.can("memory:manage"):
                raise MemoryForbiddenError("Only administrators may change business knowledge")
        elif rec.created_by != principal.user_id and not principal.can("memory:manage"):
            raise MemoryForbiddenError("Not allowed to change this memory")

    def _event(self, event_type: str, principal: Principal, rec: MemoryRecord, **extra) -> None:
        record_event(self.db, workspace_id=rec.workspace_id, event_type=event_type, actor=principal.user_id,
                     payload={"memory_id": rec.id, "kind": rec.kind.value, "source_kind": rec.source_kind.value,
                              "version": rec.version, "content_chars": rec.content_chars, "agent": principal.agent, **extra})
