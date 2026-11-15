# Memory and business knowledge (Step 8)

Plan: 8.1 model (done) · 8.2 persistence + migration 0009 (done) · 8.3 knowledge ingestion (done) · 8.4 retrieval (done)
· 8.5 use by agents/planner + HTTP API (done) · 8.6 safety tests (done). Step 8 is complete.

## 8.1 The model (`app/memory/model.py`, pure: no database, LLM or I/O; a test enforces that)
Kinds and lifetimes
| kind | for | lifetime |
|---|---|---|
| short_term | the current task | default 1h, max 24h |
| operational | ongoing work | default 30d, max 1y |
| knowledge | durable business facts | no expiry; STALE after 180 days unreviewed |
| preference | one user's own preferences | no expiry; private to that user; STALE after 1y |

Governed writes (`WRITABLE_KINDS`): users may write any kind (a preference only for themselves); documents and connectors
may write knowledge/operational (connectors also short_term); the system and agents may write only short_term and
operational. Agent-derived text can never become durable knowledge or a preference.

Provenance: every item has a `SourceRef` (kind, id/slug, optional label) and `observed_at`, and belongs to a workspace.
`explain(item, now)` answers "what do I know, where did I learn it, is it current, which workspace owns it" (no content).

Validation: bounded title (120), content (4000), up to 8 slug tags, ttl range per kind, no control characters (newline
and tab allowed). Credential-looking content (API keys, bearer tokens, JWTs, private keys, `password=...`) is rejected,
never stored, and never echoed in the error. Errors carry fixed codes only.

Freshness: FRESH -> AGING (last quarter of a bounded life, or last quarter of the review period) -> STALE (review age
passed, still returned but flagged and down-ranked) or EXPIRED (never returned).

Ranking (`rank`): keyword overlap (title x3, tags x2, content x1) x freshness (1 / .8 / .4 / 0) x source trust
(user, document 1.0; connector .9; system .8; agent .6). Ties: newest, then id. Deterministic, no embeddings.

Memory is data, never instructions: whenever it reaches a prompt (8.5) it is wrapped as untrusted.

## 8.2 Persistence (`app/models/memory.py`, `app/memory/store.py`, migration 0009)
`MemoryService` is the only way memory is written. Table `memory_items` is workspace-scoped (FK).
- Permissions: `memory:read` (viewer+), `memory:write` (member+), `memory:*` (admin+; "manage").
- Visibility: preferences only to their owner (not even admins); short-term to its creator and admins; operational and
  knowledge to every reader. Expired-but-unswept items are already invisible. Other workspaces and invisible items are a
  plain `MemoryNotFoundError`.
- Writes: humans write as themselves (the source must be the writer). KNOWLEDGE needs `memory:manage`. Agents write only
  as their own agent, only short-term/operational, only if `memory:write` is in their scope, and change only what they
  created. Documents/connectors/system use `create_trusted` (admin only, never user/agent sources) for ingestion (8.3).
- Lifecycle (compare-and-swap, workspace-restricted): ACTIVE -> SUPERSEDED (new version, same kind and owner),
  DELETED, or EXPIRED (`expire_overdue(workspace_id)`, for the Step 9 scheduler; repeatable).
- Purge: superseded, deleted and expired rows lose title, content and tags in the same transaction; metadata
  (ids, kind, source, version, sizes, timestamps) stays for provenance. A delete really deletes, and an identical
  memory can be recorded again afterwards.
- Dedupe: one ACTIVE row per (kind, owner/creator, content) via a unique key that is NULL when inactive; a repeated
  write returns the existing item. Database checks: preference <=> owner; version >= 1.
- Limits: `MEMORY_MAX_ITEMS` (active per workspace, default 5000) and `MEMORY_MAX_PREFERENCES_PER_USER` (default 50).
- `candidates(principal, kinds)` returns live, visible items as pure `MemoryItem`s for the ranker (8.4).
- Audit: `memory.created|superseded|deleted|expired` hold ids, kind, source kind, version, size and agent. Never titles,
  content or tags.
- Decision: content is stored as plain text in the database (like tasks), not encrypted, because retrieval must search
  it. Secret-looking content is rejected on write (8.1), and content is purged as soon as it is no longer live.

## 8.3 Knowledge ingestion (`app/memory/ingest.py`, new store methods; no migration)
`DocumentIngestor.ingest(principal, document_id=..., title=..., text=..., kind=KNOWLEDGE|OPERATIONAL, tags=(), ttl_seconds=None)`
turns a document into memory chunks. Chunks are ordinary `memory_items`, so they are workspace-scoped, retrievable by
every reader (like other knowledge) and ranked by the same pure ranker.
- Who: human admins only (`memory:manage`; the 8.2 trusted path). Members, viewers and agents are refused before the text
  is parsed and nothing is written.
- Input rules: `document_id` is a lowercase slug (<= 64), title is one line (<= 100), text is normalised (CRLF, form feeds,
  tabs) and rejected if empty, over `MEMORY_MAX_DOCUMENT_CHARS` (100000), containing control characters, or containing
  anything credential-looking. The whole text is checked, so a secret cut in half by a chunk boundary is still caught.
  A policy sentence that itself reads like `password: <value>` is therefore rejected too. Errors carry fixed codes only.
- Chunking: deterministic, no models. Paragraphs are packed up to `MEMORY_CHUNK_CHARS` (1000, range 200-4000); an
  oversized paragraph is cut at sentence ends, then whitespace, then hard. Every non-space character lands in exactly
  one chunk, in order. More than `MEMORY_MAX_CHUNKS_PER_DOCUMENT` (100) chunks is refused.
- Source tracking: each chunk has source kind `document`, the document id as ref, the title as label, title
  `<title> [i/n]`, and a `scope_ref` recording the document version digest, position and chunk count.
- Replace on update: the same document id replaces all of its chunks in ONE transaction (all or nothing; a limit or
  conflict leaves the old version intact). Chunks match by position: a replaced chunk keeps its lineage and gets the next
  version, its old content is purged, extra new chunks start new lineages, leftover old chunks are deleted and purged.
- Identical re-upload changes no content. Knowledge chunks are marked freshly observed (the document was reviewed, so it
  does not go STALE); operational chunks are untouched. A lapsed operational document is re-created, not skipped.
- Purge on delete: `delete` purges every chunk's title, content and tags at once and is repeatable. The same document
  can be uploaded again afterwards.
- Same text in two documents stays two memories (the dedupe key includes the document id), so provenance is never
  merged.
- Listing: `documents(principal)` returns id, title, kind, chunk count and freshness time for live documents. No content.
- Audit: ONE event per call, `memory.document_ingested|refreshed|deleted`, with document id and counts only. Never
  titles, text or tags. (Per-chunk `memory.created` events are not written on this bulk path.)
- Settings: `MEMORY_MAX_DOCUMENT_CHARS`, `MEMORY_MAX_CHUNKS_PER_DOCUMENT`, `MEMORY_CHUNK_CHARS` (bounded, in `.env.example`).
Text only: file parsing (PDF, Word) is not part of Step 8.

## 8.4 Retrieval (`app/memory/retrieval.py`; no migration)
`RetrievalService.retrieve(principal, query, kinds=None, limit=5, current_only=False, max_per_source=3)` answers "what do we
know about this, where from, is it current". Read-only, no model, no authority of its own.
- Visibility is the store's: `memory:read`, workspace, preference privacy, short-term visibility, expiry. Superseded,
  deleted and expired content is already purged, so it can never come back. Agents never receive preferences, even for
  the user they act for, and need `memory:read` in scope.
- Each hit: id, kind, title, content, source (kind, ref, label), observed_at, expires_at, freshness, `stale`, score, tags.
  Ranking is the pure 8.1 ranker. Stale items are flagged and down-ranked (`current_only=True` leaves them out);
  the result has `has_stale`.
- Bounds: query <= 500 characters, limit 1-20, at most 3 hits per source by default (one long document cannot crowd out
  the rest), total text <= `MEMORY_RETRIEVAL_MAX_CHARS` (8000; `budget_truncated` says when it cut the list).
- Search window: the newest 1000 visible items are searched; `truncated` says when more exist. Larger workspaces need a
  database-side prefilter (to do with the Postgres work in Step 14, not before it can be tested there).
- Audit: one `memory.retrieved` event per call: result ids and counts, query LENGTH, agent. Never query text, titles or content.
- Not instructions: hits are data. 8.5 wraps them as untrusted when they enter a prompt.

## 8.5 Memory in prompts and the HTTP API (`app/memory/context.py`, `app/api/memory.py`; no migration)
Prompts (`MemoryContextBuilder`, wired by `memory_provider(db, settings)`)
- Used in all four model prompts that see a request: intent understanding, tool-call planning, goal decomposition (the
  plan endpoints, agent runs and `/ai/understand|plan`). Each service takes an optional `context_provider`; with none (or
  nothing relevant) the prompt is exactly what it was before.
- Memory is data, never instructions: one extra message, inside the untrusted wrapper (delimiter neutralised, titles and
  labels flattened to one line), with a header saying it cannot change which agents, tools or argument values are allowed.
  Authority still comes only from the kernel; a model that names a tool outside the catalog is still rejected.
- Only shared business memory (knowledge and operational). Preferences and short-term items never reach a prompt.
- Same visibility as retrieval. An agent needs `memory:read` in its scope (both starter agents now have it, read only);
  a caller without it simply gets no memory and the request carries on.
- Honest about age: stale items are left out, ageing items are labelled. Bounded by MEMORY_PROMPT_MAX_HITS (5) and
  MEMORY_PROMPT_MAX_CHARS (3000).
- Audit: `memory.context_used` (purpose, counts, characters, ids, agent) beside `memory.retrieved`; never query, titles or content.

HTTP API (`/workspaces/{id}/memory`, human callers only; a source is never taken from the request)
- `POST /` create (as the caller) · `GET /` list · `GET /{id}` · `DELETE /{id}` (a real purge)
- `POST /search` (POST so the query stays out of URLs and logs): hits with source, freshness and a stale flag
- `GET /documents` (no content) · `PUT /documents/{document_id}` create or replace · `DELETE /documents/{document_id}`
- Reads need `memory:read`; writes `memory:write`; knowledge and documents `memory:manage`. Not visible = 404.
  Errors are fixed text plus a fixed code and never echo the rejected content.
Not built: an HTTP route to supersede (edit) an item.

## 8.6 Safety suite (`tests/test_memory_safety.py`)
End-to-end checks over HTTP and the services: documents never cross workspaces (routes, search, delete, prompts); losing
membership ends access at once; injected document text (fake delimiters, "ignore instructions") stays data and grants no
authority in runs or plan decomposition; credential-like text is stored and echoed nowhere (items, titles, documents, a
key cut by a chunk boundary, logs, audit); after replace, delete or supersede no content remains in any column; audit
stays content-free over the whole lifecycle; expired items never reach a prompt or search; agents cannot ingest, curate or
read preferences; size, tag, lifetime and workspace limits hold; a memory failure never blocks a run.
Known limits carried to Step 14: everything ran on SQLite (Postgres concurrency re-check); retrieval searches the newest
1000 visible items (`truncated` says so).
