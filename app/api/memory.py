"""Memory, document and search endpoints. Thin: access rules, validation, purge and audit live in the memory services.

Items       POST /memory · GET /memory · GET /memory/{id} · DELETE /memory/{id}
Search      POST /memory/search            (POST so the query text never lands in URLs or access logs)
Documents   GET /memory/documents · PUT /memory/documents/{document_id} · DELETE /memory/documents/{document_id}

Humans only: the caller is the signed-in user acting as themselves (no agent principal exists on this API). A source
is never taken from the request: items are always recorded as coming from the caller, documents as DOCUMENT/<id>.
Reads need `memory:read`, writes `memory:write` (knowledge and documents need `memory:manage`; the service enforces it
again). Anything the caller may not see, including other workspaces' items and other users' preferences, is a plain 404.
Errors are fixed text plus a fixed code; the content that was rejected is never echoed. Responses to readers carry
content only for items that reader may see; listing documents returns no content at all.
"""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.identity.context import WorkspaceContext, require_permission
from app.memory import errors as me
from app.memory.ingest import DocumentIngestor
from app.memory.model import (Freshness, MAX_CONTENT_CHARS, MAX_QUERY_CHARS, MAX_TAGS, MAX_TITLE_CHARS, MemoryDraft,
                              MemoryKind, SourceKind, SourceRef, freshness)
from app.memory.retrieval import MAX_RESULTS, RetrievalService
from app.memory.store import MemoryService, to_item
from app.models.memory import MemoryRecord

router = APIRouter(prefix="/workspaces/{workspace_id}/memory", tags=["memory"])
MAX_UPLOAD_CHARS = 2_000_000          # hard ceiling of MEMORY_MAX_DOCUMENT_CHARS; the service applies the configured one


class CreateMemoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: MemoryKind
    title: str = Field(min_length=1, max_length=MAX_TITLE_CHARS)
    content: str = Field(min_length=1, max_length=MAX_CONTENT_CHARS)
    tags: List[str] = Field(default_factory=list, max_length=MAX_TAGS)
    ttl_seconds: Optional[int] = Field(default=None, ge=1)


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=MAX_QUERY_CHARS)
    kinds: Optional[List[MemoryKind]] = Field(default=None, max_length=4)
    limit: int = Field(default=5, ge=1, le=MAX_RESULTS)
    max_per_source: int = Field(default=3, ge=1, le=MAX_RESULTS)
    current_only: bool = False


class UploadDocumentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=MAX_UPLOAD_CHARS)
    kind: MemoryKind = MemoryKind.KNOWLEDGE
    tags: List[str] = Field(default_factory=list, max_length=MAX_TAGS)
    ttl_seconds: Optional[int] = Field(default=None, ge=1)


class SourceView(BaseModel):
    kind: SourceKind
    ref: str
    label: Optional[str]


class MemoryView(BaseModel):
    id: str
    kind: MemoryKind
    title: str
    content: str
    source: SourceView
    observed_at: datetime
    expires_at: Optional[datetime]
    freshness: Freshness
    stale: bool
    tags: List[str]
    version: int

    @classmethod
    def of(cls, rec: MemoryRecord, now: datetime) -> "MemoryView":
        it = to_item(rec)
        f = freshness(it, now)
        return cls(id=rec.id, kind=rec.kind, title=rec.title, content=rec.content,
                   source=SourceView(kind=rec.source_kind, ref=rec.source_ref, label=rec.source_label),
                   observed_at=it.observed_at, expires_at=it.expires_at, freshness=f, stale=f == Freshness.STALE,
                   tags=list(rec.tags or []), version=rec.version)


class HitView(BaseModel):
    id: str
    kind: MemoryKind
    title: str
    content: str
    source: SourceView
    observed_at: datetime
    expires_at: Optional[datetime]
    freshness: Freshness
    stale: bool
    score: float
    tags: List[str]


class SearchResponse(BaseModel):
    hits: List[HitView]
    considered: int
    truncated: bool
    budget_truncated: bool
    has_stale: bool
    reason: Optional[str] = None


class DocumentView(BaseModel):
    """No content: what the document is, how many chunks, when it was last recorded or reviewed."""
    document_id: str
    title: Optional[str]
    kind: MemoryKind
    chunks: int
    observed_at: datetime


class IngestView(BaseModel):
    document_id: str
    status: str                  # created | updated | unchanged | refreshed
    chunks: int
    added: int
    replaced: int
    removed: int


class DeletedView(BaseModel):
    removed: int


def _http(exc: me.MemoryError_) -> HTTPException:
    """Fixed client-facing text. Never the rejected content (the services guarantee that already)."""
    if isinstance(exc, me.MemoryNotFoundError):
        return HTTPException(404, "Memory not found")
    if isinstance(exc, me.MemoryForbiddenError):
        return HTTPException(403, "Insufficient permissions")
    if isinstance(exc, (me.MemoryConflictError, me.MemoryLimitError)):
        return HTTPException(409, f"The memory request could not be completed ({exc.code})")
    if isinstance(exc, me.InvalidMemoryError):
        return HTTPException(422, f"The memory request is not valid ({exc.code})")
    return HTTPException(400, "The memory request could not be processed")


def _svc(db: Session, settings: Settings) -> MemoryService:
    return MemoryService(db, settings)


# ------------------------------------------------------------------ documents (declared before /{memory_id})
@router.get("/documents", response_model=List[DocumentView])
def list_documents(ctx: WorkspaceContext = Depends(require_permission("memory:read")),
                   db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    try:
        docs = DocumentIngestor(_svc(db, settings)).documents(ctx.principal())
    except me.MemoryError_ as exc:
        raise _http(exc)
    return [DocumentView(document_id=d.document_id, title=d.title, kind=d.kind, chunks=d.chunks,
                         observed_at=d.observed_at) for d in docs]


@router.put("/documents/{document_id}", response_model=IngestView)
def upload_document(document_id: str, body: UploadDocumentRequest,
                    ctx: WorkspaceContext = Depends(require_permission("memory:manage")),
                    db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    """Create or replace a document (same id = replace all its chunks). Text only; admins only."""
    try:
        r = DocumentIngestor(_svc(db, settings)).ingest(ctx.principal(), document_id=document_id, title=body.title,
                                                        text=body.text, kind=body.kind, tags=body.tags,
                                                        ttl_seconds=body.ttl_seconds)
    except me.MemoryError_ as exc:
        raise _http(exc)
    return IngestView(document_id=r.document_id, status=r.status, chunks=r.chunks, added=r.added, replaced=r.replaced,
                      removed=r.removed)


@router.delete("/documents/{document_id}", response_model=DeletedView)
def delete_document(document_id: str, ctx: WorkspaceContext = Depends(require_permission("memory:manage")),
                    db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    """Purges every chunk. Idempotent: deleting a document that is not there removes 0."""
    try:
        return DeletedView(removed=DocumentIngestor(_svc(db, settings)).delete(ctx.principal(), document_id))
    except me.MemoryError_ as exc:
        raise _http(exc)


# ------------------------------------------------------------------ search
@router.post("/search", response_model=SearchResponse)
def search(body: SearchRequest, ctx: WorkspaceContext = Depends(require_permission("memory:read")),
           db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    try:
        res = RetrievalService(_svc(db, settings)).retrieve(
            ctx.principal(), body.query, kinds=body.kinds, limit=body.limit, current_only=body.current_only,
            max_per_source=body.max_per_source)
    except me.MemoryError_ as exc:
        raise _http(exc)
    return SearchResponse(
        hits=[HitView(id=h.memory_id, kind=h.kind, title=h.title, content=h.content,
                      source=SourceView(kind=h.source_kind, ref=h.source_ref, label=h.source_label),
                      observed_at=h.observed_at, expires_at=h.expires_at, freshness=h.freshness, stale=h.stale,
                      score=h.score, tags=list(h.tags)) for h in res.hits],
        considered=res.considered, truncated=res.truncated, budget_truncated=res.budget_truncated,
        has_stale=res.has_stale, reason=res.reason)


# ------------------------------------------------------------------ items
@router.post("", response_model=MemoryView, status_code=201)
def create_memory(body: CreateMemoryRequest, ctx: WorkspaceContext = Depends(require_permission("memory:write")),
                  db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    """Recorded as coming from the caller (never a source named in the request). Preferences belong to the caller."""
    p, svc = ctx.principal(), _svc(db, settings)
    try:
        draft = MemoryDraft(kind=body.kind, title=body.title, content=body.content, tags=tuple(body.tags),
                            ttl_seconds=body.ttl_seconds, source=SourceRef(SourceKind.USER, p.user_id),
                            owner_user_id=p.user_id if body.kind == MemoryKind.PREFERENCE else None)
        return MemoryView.of(svc.create(p, draft), svc.now())
    except me.MemoryError_ as exc:
        raise _http(exc)


@router.get("", response_model=List[MemoryView])
def list_memory(kind: Optional[MemoryKind] = None, limit: int = Query(50, ge=1, le=200),
                ctx: WorkspaceContext = Depends(require_permission("memory:read")),
                db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    svc = _svc(db, settings)
    try:
        return [MemoryView.of(r, svc.now()) for r in svc.list(ctx.principal(), kind=kind, limit=limit)]
    except me.MemoryError_ as exc:
        raise _http(exc)


@router.get("/{memory_id}", response_model=MemoryView)
def get_memory(memory_id: str, ctx: WorkspaceContext = Depends(require_permission("memory:read")),
               db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    svc = _svc(db, settings)
    try:
        return MemoryView.of(svc.get(ctx.principal(), memory_id), svc.now())
    except me.MemoryError_ as exc:
        raise _http(exc)


@router.delete("/{memory_id}", status_code=204)
def delete_memory(memory_id: str, ctx: WorkspaceContext = Depends(require_permission("memory:write")),
                  db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    """A real delete: the content is purged. Idempotent for the caller's own items."""
    try:
        _svc(db, settings).delete(ctx.principal(), memory_id)
    except me.MemoryError_ as exc:
        raise _http(exc)
