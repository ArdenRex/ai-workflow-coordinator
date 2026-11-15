"""Knowledge ingestion (8.3): a document becomes source-tracked memory chunks.

    text --normalize--> --chunk--> MemoryDrafts (source = DOCUMENT/<document_id>) --replace_document--> memory_items

Rules
- Trusted and human-only: ingestion goes through `MemoryService.check_trusted` (admins; never an agent). Document text
  is DATA, so everything the memory model enforces still applies per chunk (size, control characters, no secrets).
- Nothing is half-ingested: the document is fully validated and cut into drafts BEFORE the database is touched, and the
  swap of old chunks for new ones is one transaction. A document containing a credential-looking string is rejected
  as a whole (also across chunk boundaries) and the error never echoes it.
- Source tracking: every chunk carries source kind DOCUMENT, the document id as its ref and the document title as its
  label; its `scope_ref` records which version of the document it belongs to, its position and the chunk count.
- Replace on update: uploading the same document id again replaces ALL its chunks. Identical content is a no-op
  (knowledge is marked as freshly reviewed). A shorter document leaves no leftover chunks.
- Purge on delete: deleting a document purges every chunk's content at once; only metadata remains.
- Deterministic chunking, no models: paragraphs are packed up to the target size; an oversized paragraph is cut at
  sentence ends, then at whitespace. Every non-space character of the document lands in exactly one chunk.
- Audit: ONE content-free event per call (`memory.document_ingested|refreshed|deleted`) with ids and counts only.
"""
import hashlib
import re
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from app.kernel.permissions import Principal
from app.memory.errors import InvalidMemoryError
from app.memory.model import MAX_CONTENT_CHARS, MemoryDraft, MemoryKind as K, SourceKind as SK, SourceRef, contains_secret
from app.memory.store import DocumentInfo, MemoryService, chunk_scope, parse_chunk_scope

MAX_DOCUMENT_ID_CHARS = 64
MAX_DOCUMENT_TITLE_CHARS = 100          # leaves room for the " [12/100]" suffix inside the 120-character title limit
DOCUMENT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")
DOCUMENT_KINDS = (K.KNOWLEDGE, K.OPERATIONAL)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0e-\x1f\x7f]")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class IngestResult:
    """Content-free outcome. status: created | updated | unchanged | refreshed."""
    document_id: str
    status: str
    chunks: int
    added: int = 0
    replaced: int = 0
    removed: int = 0


def normalize_text(text: object, *, max_chars: int) -> str:
    if not isinstance(text, str):
        raise InvalidMemoryError("invalid_document", "Document text must be text")
    t = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x0c", "\n").replace("\t", " ")
    if _CONTROL_RE.search(t):
        raise InvalidMemoryError("invalid_document", "The document contains control characters")
    t = "\n".join(line.rstrip() for line in t.split("\n"))
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    if not t:
        raise InvalidMemoryError("invalid_document", "The document is empty")
    if len(t) > max_chars:
        raise InvalidMemoryError("document_too_large", f"A document may have at most {max_chars} characters")
    return t


def _hard_split(s: str, n: int) -> List[str]:
    out: List[str] = []
    while len(s) > n:
        cut = s.rfind(" ", 0, n + 1)
        if cut < n // 2:
            cut = n
        out.append(s[:cut].strip())
        s = s[cut:].lstrip()
    if s:
        out.append(s)
    return out


def chunk_text(text: str, target: int) -> List[str]:
    """Pure and deterministic. Every chunk is non-empty and at most `target` characters."""
    if not 1 <= target <= MAX_CONTENT_CHARS:
        raise InvalidMemoryError("invalid_chunk_size", "The chunk size is outside the allowed range")
    units: List[Tuple[str, str]] = []                                  # (separator before, text)
    for para in (p.strip() for p in text.split("\n\n")):
        if not para:
            continue
        pieces: List[str] = []
        for sent in (_SENTENCE_RE.split(para) if len(para) > target else [para]):
            pieces.extend(_hard_split(sent, target) if len(sent) > target else [sent])
        units.extend(("\n\n" if k == 0 else " ", piece) for k, piece in enumerate(pieces))
    chunks: List[str] = []
    cur = ""
    for sep, piece in units:
        cand = cur + sep + piece if cur else piece
        if cur and len(cand) > target:
            chunks.append(cur)
            cur = piece
        else:
            cur = cand
    if cur:
        chunks.append(cur)
    return chunks


class DocumentIngestor:
    def __init__(self, memory: MemoryService):
        self.memory, self.settings = memory, memory.settings

    def ingest(self, principal: Principal, *, document_id: str, title: str, text: str, kind: K = K.KNOWLEDGE,
               tags: Sequence[str] = (), ttl_seconds: Optional[int] = None) -> IngestResult:
        self.memory.check_trusted(principal)                           # before anything is parsed or stored
        doc_id = self._document_id(document_id)
        title = self._title(title)
        if kind not in DOCUMENT_KINDS:
            raise InvalidMemoryError("invalid_kind", "A document becomes knowledge or operational memory")
        body = normalize_text(text, max_chars=self.settings.memory_max_document_chars)
        if contains_secret(body):
            raise InvalidMemoryError("secret_detected", "Content that looks like a credential cannot be stored")
        pieces = chunk_text(body, self.settings.memory_chunk_chars)
        if len(pieces) > self.settings.memory_max_chunks_per_document:
            raise InvalidMemoryError("too_many_chunks", "The document is too large to ingest")
        tags = tuple(tags)
        digest = hashlib.sha256("\x1f".join((kind.value, str(ttl_seconds), title, ",".join(tags), body)).encode()).hexdigest()
        n = len(pieces)
        source = SourceRef(SK.DOCUMENT, doc_id, title)
        drafts = [MemoryDraft(kind=kind, title=title if n == 1 else f"{title} [{i + 1}/{n}]", content=piece,
                              source=source, tags=tags, ttl_seconds=ttl_seconds, scope_ref=chunk_scope(digest, i, n))
                  for i, piece in enumerate(pieces)]                  # fully validated before the database is touched
        live = self.memory.live_document_scopes(principal, doc_id)
        if self._is_current(live, digest, n):
            if kind == K.KNOWLEDGE:
                self.memory.refresh_document(principal, doc_id)
                return IngestResult(doc_id, "refreshed", n)
            return IngestResult(doc_id, "unchanged", n)
        added, replaced, removed = self.memory.replace_document(principal, doc_id, drafts)
        return IngestResult(doc_id, "updated" if (replaced or removed) else "created", n, added, replaced, removed)

    def delete(self, principal: Principal, document_id: str) -> int:
        """Purges every chunk of the document. Idempotent: returns how many chunks were removed (0 if none)."""
        self.memory.check_trusted(principal)
        return self.memory.delete_document(principal, self._document_id(document_id))

    def documents(self, principal: Principal) -> List[DocumentInfo]:
        return self.memory.list_documents(principal)

    @staticmethod
    def _is_current(live: Sequence[str], digest: str, n: int) -> bool:
        parsed = [parse_chunk_scope(s) for s in live]
        return (len(live) == n and all(p is not None and p[0] == digest[:32] and p[2] == n for p in parsed)
                and sorted(p[1] for p in parsed if p) == list(range(n)))

    @staticmethod
    def _document_id(value: object) -> str:
        if not isinstance(value, str) or not DOCUMENT_ID_RE.match(value):
            raise InvalidMemoryError("invalid_document_id", "A document id is a lowercase slug of up to %d characters"
                                     % MAX_DOCUMENT_ID_CHARS)
        return value

    @staticmethod
    def _title(value: object) -> str:
        if not isinstance(value, str):
            raise InvalidMemoryError("invalid_document_title", "The title must be text")
        v = value.strip()
        if not v or len(v) > MAX_DOCUMENT_TITLE_CHARS or _CONTROL_RE.search(v) or "\n" in v:
            raise InvalidMemoryError("invalid_document_title", "The title must be 1 to %d characters on one line"
                                     % MAX_DOCUMENT_TITLE_CHARS)
        return v
