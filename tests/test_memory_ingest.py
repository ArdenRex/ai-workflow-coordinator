"""Substep 8.3: knowledge ingestion - chunking, source tracking, replace-on-update, purge-on-delete, atomicity, audit."""
import logging
from datetime import timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import select, text

from app.config import Settings
from app.memory.errors import InvalidMemoryError, MemoryForbiddenError, MemoryLimitError
from app.memory.ingest import DocumentIngestor, chunk_text, normalize_text
from app.memory.model import Freshness, contains_secret, MemoryDraft, MemoryKind as K, SourceKind as SK, SourceRef, freshness, rank
from app.memory.store import MemoryService, parse_chunk_scope, to_item
from app.models import Role, SystemEvent
from app.models.enums import MemoryStatus as M
from app.models.memory import MemoryRecord
from tests.test_memory_store import ADMIN, AG, CANARY, D, P, T0, Clock, clock, users  # noqa: F401  (fixtures reused)

pytestmark = pytest.mark.usefixtures("seed_workspaces")
POLICY = ("Refunds are issued within 14 days of purchase when the item is unused and returned in its original "
          "packaging with the receipt.\n\nShipping takes 3 to 5 business days inside the country. Express shipping "
          "is available for an extra fee and arrives within 2 days.\n\nSupport is open on weekdays from 9 to 5 and "
          "answers every email within one business day, including public holidays.")


def mk_settings(**kw):
    return Settings(app_env="test", database_url="sqlite:///:memory:", _env_file=None, **kw)


@pytest.fixture
def svc(db_session, clock, users):  # noqa: F811
    return MemoryService(db_session, mk_settings(memory_chunk_chars=200), clock=clock)


@pytest.fixture
def ing(svc):
    return DocumentIngestor(svc)


def rows(db, ws="w1", **where):
    q = select(MemoryRecord).where(MemoryRecord.workspace_id == ws, MemoryRecord.source_kind == SK.DOCUMENT)
    for k, v in where.items():
        q = q.where(getattr(MemoryRecord, k) == v)
    return list(db.scalars(q.order_by(MemoryRecord.scope_ref, MemoryRecord.id)))


def events(db, prefix="memory.document"):
    return list(db.scalars(select(SystemEvent).where(SystemEvent.event_type.like(prefix + "%"))))


def ingest(ing, text_=POLICY, doc="refund-policy", who=None, **kw):
    kw.setdefault("title", "Refund policy")
    return ing.ingest(who or ADMIN(), document_id=doc, text=text_, **kw)


LONG = " ".join(f"Sentence number {i} talks about topic {i % 7} in some detail." for i in range(40))


# ------------------------------------------------------------------ pure chunking
def test_short_text_is_one_chunk():
    assert chunk_text("Hello world.", 200) == ["Hello world."]


def test_paragraphs_are_packed_up_to_target_and_never_exceed_it():
    paras = "\n\n".join(f"Paragraph {i} " + "word " * 20 for i in range(10))
    chunks = chunk_text(paras.strip(), 250)
    assert len(chunks) > 1 and all(0 < len(c) <= 250 for c in chunks)


def test_oversized_paragraph_is_cut_at_sentences_then_whitespace_then_hard():
    chunks = chunk_text(LONG, 200)
    assert all(0 < len(c) <= 200 for c in chunks) and all(c.endswith(".") for c in chunks)
    blob = "x" * 950
    hard = chunk_text(blob, 200)
    assert all(len(c) <= 200 for c in hard) and "".join(hard) == blob
    spaced = chunk_text("alpha " * 100, 50)
    assert all(len(c) <= 50 and not c.startswith(" ") and not c.endswith(" ") for c in spaced)


def test_every_character_lands_in_exactly_one_chunk_in_order():
    for t in (POLICY, LONG, "a b c\n\n" * 50, "zz" * 400 + " tail words here"):
        assert "".join("".join(chunk_text(t.strip(), 120)).split()) == "".join(t.split())
    assert chunk_text(LONG, 150) == chunk_text(LONG, 150)                       # deterministic


def test_chunk_size_must_be_in_range():
    for bad in (0, -1, 4001):
        with pytest.raises(InvalidMemoryError) as e:
            chunk_text("x", bad)
        assert e.value.code == "invalid_chunk_size"


def test_normalize_cleans_line_endings_and_rejects_control_characters_empty_and_huge():
    assert normalize_text("a\r\nb\rc\x0cd\t \n\n\n\n e  ", max_chars=100) == "a\nb\nc\nd\n\n e"
    for bad, code in (("a\x00b", "invalid_document"), ("a\x1bb", "invalid_document"), ("  \n ", "invalid_document"),
                      (123, "invalid_document"), ("x" * 11, "document_too_large")):
        with pytest.raises(InvalidMemoryError) as e:
            normalize_text(bad, max_chars=10)
        assert e.value.code == code


# ------------------------------------------------------------------ ingestion
def test_ingest_creates_source_tracked_knowledge_chunks(ing, db_session):
    r = ingest(ing, tags=("policy",))
    recs = rows(db_session)
    assert r.status == "created" and r.chunks == len(recs) >= 2 and r.added == r.chunks
    for i, rec in enumerate(sorted(recs, key=lambda x: parse_chunk_scope(x.scope_ref)[1])):
        assert (rec.kind, rec.status, rec.source_kind, rec.source_ref, rec.source_label) == (
            K.KNOWLEDGE, M.ACTIVE, SK.DOCUMENT, "refund-policy", "Refund policy")
        assert rec.title == f"Refund policy [{i + 1}/{r.chunks}]" and rec.tags == ["policy"] and rec.expires_at is None
        assert parse_chunk_scope(rec.scope_ref)[1:] == (i, r.chunks) and rec.created_by == "u2" and rec.version == 1
        assert rec.lineage_id == rec.id


def test_single_chunk_document_keeps_its_plain_title(ing, db_session):
    ingest(ing, "Short and sweet.")
    assert [r.title for r in rows(db_session)] == ["Refund policy"]


def test_every_reader_can_retrieve_the_chunks_with_provenance(ing, svc):
    ingest(ing)
    for role in (Role.VIEWER, Role.MEMBER, Role.ADMIN):
        items = svc.candidates(P("u3", role=role))
        hits = rank("how long do refunds take", items, T0)
        assert hits and "14 days" in hits[0].item.content
        assert (hits[0].item.source.kind, hits[0].item.source.ref, hits[0].item.source.label) == (
            SK.DOCUMENT, "refund-policy", "Refund policy")


def test_only_human_admins_may_ingest_and_nothing_is_written_otherwise(ing, db_session):
    attempts = [P("u1", role=Role.MEMBER), P("u3", role=Role.VIEWER), AG(scope=("memory:read", "memory:write")),
                AG(scope=("memory:read", "memory:write", "memory:manage", "memory:*"))]
    for who in attempts:
        with pytest.raises(MemoryForbiddenError):
            ingest(ing, who=who)
    assert rows(db_session) == [] and events(db_session) == []


@pytest.mark.parametrize("kw,code", [
    (dict(doc="Bad Id"), "invalid_document_id"), (dict(doc="../x"), "invalid_document_id"),
    (dict(doc="x" * 65), "invalid_document_id"), (dict(doc=""), "invalid_document_id"),
    (dict(title=""), "invalid_document_title"), (dict(title="t" * 101), "invalid_document_title"),
    (dict(title="two\nlines"), "invalid_document_title"), (dict(title=5), "invalid_document_title"),
    (dict(kind=K.SHORT_TERM), "invalid_kind"), (dict(kind=K.PREFERENCE), "invalid_kind"),
    (dict(tags=("Bad Tag",)), "invalid_tags"), (dict(ttl_seconds=3600), "ttl_not_allowed"),
    (dict(kind=K.OPERATIONAL, ttl_seconds=5), "invalid_ttl"),
])
def test_invalid_input_is_rejected_with_a_fixed_code_and_stores_nothing(ing, db_session, kw, code):
    with pytest.raises(InvalidMemoryError) as e:
        ingest(ing, **kw)
    assert e.value.code == code and rows(db_session) == []


def test_credential_in_a_document_rejects_the_whole_document_without_echo(ing, db_session):
    for secret in ("api_key = " + CANARY + "-abcdef", "sk-" + "a1b2c3d4" * 4):
        with pytest.raises(InvalidMemoryError) as e:
            ingest(ing, POLICY + "\n\nInternal note: " + secret)
        assert e.value.code == "secret_detected" and CANARY not in str(e.value) and secret not in str(e.value)
    assert rows(db_session) == []


def test_credential_straddling_a_chunk_boundary_is_still_caught(ing, db_session):
    body = "-" * 190 + "password=hunter22hunter22"                       # one unbroken token: cut falls inside "password=h|unter..."
    pieces = chunk_text(body, 200)
    assert len(pieces) == 2 and not any(contains_secret(p) for p in pieces)    # neither half looks like a secret alone
    with pytest.raises(InvalidMemoryError) as e:
        ingest(ing, body)
    assert e.value.code == "secret_detected" and rows(db_session) == []


def test_size_ceilings(db_session, clock, users):  # noqa: F811
    small = DocumentIngestor(MemoryService(db_session, mk_settings(memory_chunk_chars=200, memory_max_document_chars=1000,
                                                                   memory_max_chunks_per_document=3), clock=clock))
    for body, code in (("a" * 1001, "document_too_large"), (LONG[:900], "too_many_chunks")):
        with pytest.raises(InvalidMemoryError) as e:
            ingest(small, body)
        assert e.value.code == code
    assert rows(db_session) == []


def test_operational_documents_take_a_lifetime(ing, db_session):
    ingest(ing, kind=K.OPERATIONAL, ttl_seconds=3600)
    assert all(r.kind == K.OPERATIONAL and r.expires_at is not None for r in rows(db_session))


# ------------------------------------------------------------------ replace on update
def test_identical_reupload_changes_nothing_but_marks_knowledge_reviewed(ing, svc, db_session, clock):
    ingest(ing)
    before = {r.id: (r.version, r.content) for r in rows(db_session)}
    clock.advance(days=170)
    r = ingest(ing)
    after = rows(db_session)
    assert r.status == "refreshed" and {x.id: (x.version, x.content) for x in after} == before
    assert all(x.observed_at.replace(tzinfo=None) == (T0 + timedelta(days=170)).replace(tzinfo=None) for x in after)
    clock.advance(days=100)                                            # 270 days after first upload, 100 after review
    assert all(freshness(i, clock.now) != Freshness.STALE for i in svc.candidates(P("u3", role=Role.VIEWER)))
    assert [e.event_type for e in events(db_session)] == ["memory.document_ingested", "memory.document_refreshed"]


def test_identical_operational_reupload_is_a_plain_noop(ing, db_session):
    ingest(ing, kind=K.OPERATIONAL, ttl_seconds=3600)
    assert ingest(ing, kind=K.OPERATIONAL, ttl_seconds=3600).status == "unchanged"
    assert len(events(db_session)) == 1


def test_update_purges_old_chunks_and_carries_version_and_lineage(ing, db_session):
    ingest(ing)
    old = {parse_chunk_scope(r.scope_ref)[1]: r for r in rows(db_session)}
    old_ids = {i: (r.id, r.lineage_id) for i, r in old.items()}
    new_text = POLICY.replace("14 days", "30 days").replace(CANARY, "")
    r = ingest(ing, new_text)
    assert r.status == "updated" and r.replaced == len(old) and r.added == 0 and r.removed == 0
    active = [x for x in rows(db_session) if x.status == M.ACTIVE]
    assert len(active) == r.chunks
    for x in active:
        i = parse_chunk_scope(x.scope_ref)[1]
        assert (x.version, x.supersedes_id, x.lineage_id) == (2, old_ids[i][0], old_ids[i][1])
    dead = [x for x in rows(db_session) if x.status == M.SUPERSEDED]
    assert len(dead) == len(old) and all((x.title, x.content, x.tags, x.dedupe_key) == ("", "", [], None) for x in dead)
    assert all("30 days" in " ".join(x.content for x in active) for _ in [0])
    assert "14 days" not in " ".join(x.content for x in rows(db_session))


def test_shorter_document_leaves_no_leftover_chunks(ing, db_session):
    first = ingest(ing, LONG)
    second = ingest(ing, "Only one short paragraph now.")
    assert second.status == "updated" and second.chunks == 1 and second.removed == first.chunks - 1
    recs = rows(db_session)
    assert [r.status for r in recs if r.status == M.ACTIVE] == [M.ACTIVE]
    assert sum(r.status == M.DELETED for r in recs) == first.chunks - 1
    assert all(r.content == "" for r in recs if r.status != M.ACTIVE)


def test_longer_document_adds_chunks_with_new_lineages(ing, db_session):
    first = ingest(ing, "Tiny.")
    second = ingest(ing, LONG)
    assert second.replaced == 1 and second.added == second.chunks - 1 and first.chunks == 1
    active = [r for r in rows(db_session) if r.status == M.ACTIVE]
    assert sorted(r.version for r in active) == [1] * (second.chunks - 1) + [2]
    assert len({r.lineage_id for r in active}) == second.chunks


def test_changing_kind_tags_or_title_counts_as_an_update(ing):
    ingest(ing)
    assert ingest(ing, tags=("a",)).status == "updated"
    assert ingest(ing, tags=("a",), title="Renamed policy").status == "updated"
    assert ingest(ing, tags=("a",), title="Renamed policy", kind=K.OPERATIONAL).status == "updated"
    assert ingest(ing, tags=("a",), title="Renamed policy", kind=K.OPERATIONAL).status == "unchanged"


def test_same_text_in_two_documents_stays_two_sets_of_memories(ing, db_session):
    ingest(ing, doc="policy-a")
    ingest(ing, doc="policy-b")
    a, b = rows(db_session, source_ref="policy-a"), rows(db_session, source_ref="policy-b")
    assert a and len(a) == len(b) and not {x.id for x in a} & {x.id for x in b}
    ing.delete(ADMIN(), "policy-a")
    assert all(x.status == M.ACTIVE for x in rows(db_session, source_ref="policy-b"))


def test_a_failed_replace_leaves_the_old_version_intact(db_session, clock, users):  # noqa: F811
    tight = DocumentIngestor(MemoryService(db_session, mk_settings(memory_chunk_chars=200, memory_max_items=4), clock=clock))
    first = ingest(tight, POLICY)
    assert first.chunks <= 3
    with pytest.raises(MemoryLimitError):
        ingest(tight, LONG)
    recs = rows(db_session)
    assert len(recs) == first.chunks and all(r.status == M.ACTIVE and r.content and r.version == 1 for r in recs)


# ------------------------------------------------------------------ delete
def test_delete_purges_everything_and_is_idempotent(ing, svc, db_session):
    ingest(ing, POLICY + f"\n\nNote {CANARY}.")
    n = len(rows(db_session))
    assert ing.delete(ADMIN(), "refund-policy") == n
    assert ing.delete(ADMIN(), "refund-policy") == 0
    assert svc.candidates(P("u3", role=Role.VIEWER)) == []
    recs = rows(db_session)
    assert all(r.status == M.DELETED and (r.title, r.content, r.tags, r.dedupe_key) == ("", "", [], None) for r in recs)
    assert all(r.ended_by == "u2" and r.ended_at is not None for r in recs)
    raw = db_session.execute(text("select count(*) from memory_items where content like :c or title like :c"),
                             {"c": f"%{CANARY}%"}).scalar()
    assert raw == 0
    assert ingest(ing).status == "created"                             # the same document can be uploaded again


def test_delete_needs_a_human_admin(ing, db_session):
    ingest(ing)
    for who in (P("u1", role=Role.MEMBER), P("u3", role=Role.VIEWER), AG(scope=("memory:read", "memory:write", "memory:manage"))):
        with pytest.raises(MemoryForbiddenError):
            ing.delete(who, "refund-policy")
    assert all(r.status == M.ACTIVE for r in rows(db_session))
    with pytest.raises(InvalidMemoryError):
        ing.delete(ADMIN(), "Bad Id")


def test_workspaces_are_isolated_for_ingest_update_and_delete(ing, db_session):
    ingest(ing)
    ingest(ing, who=ADMIN("u2", "w2"), text_="Other company policy text.")
    assert ing.delete(ADMIN("u2", "w2"), "refund-policy") == 1         # w2's own document with the same id
    assert all(r.status == M.ACTIVE for r in rows(db_session, "w1"))
    assert [r.status for r in rows(db_session, "w2")] == [M.DELETED]
    assert ing.delete(ADMIN("u2", "w3"), "refund-policy") == 0


# ------------------------------------------------------------------ expiry
def test_expired_operational_document_vanishes_and_reupload_is_new(ing, svc, db_session, clock):
    ingest(ing, kind=K.OPERATIONAL, ttl_seconds=3600)
    clock.advance(hours=2)
    assert svc.candidates(P("u3", role=Role.VIEWER)) == [] and ing.documents(P("u3", role=Role.VIEWER)) == []
    assert ingest(ing, kind=K.OPERATIONAL, ttl_seconds=3600).status == "updated"   # not "unchanged": it had lapsed
    assert len(svc.candidates(P("u3", role=Role.VIEWER))) == len([r for r in rows(db_session) if r.status == M.ACTIVE])
    clock.advance(hours=2)
    assert svc.expire_overdue("w1") == len([r for r in rows(db_session) if r.status == M.EXPIRED]) > 0
    assert all(r.content == "" for r in rows(db_session) if r.status == M.EXPIRED)


# ------------------------------------------------------------------ listing
def test_documents_listing_shows_no_content_and_respects_workspace(ing):
    ingest(ing, doc="policy-a", title="Policy A")
    ingest(ing, "One paragraph.", doc="faq", title="FAQ", kind=K.OPERATIONAL)
    ingest(ing, who=ADMIN("u2", "w2"), text_="Elsewhere.", doc="other", title="Other")
    docs = ing.documents(P("u3", role=Role.VIEWER))
    assert [(d.document_id, d.title, d.kind, d.chunks > 0) for d in docs] == [
        ("faq", "FAQ", K.OPERATIONAL, True), ("policy-a", "Policy A", K.KNOWLEDGE, True)]
    assert not hasattr(docs[0], "content")
    assert [d.document_id for d in ing.documents(ADMIN("u2", "w2"))] == ["other"]
    with pytest.raises(MemoryForbiddenError):
        ing.documents(P("u3", role=Role.VIEWER, agent="x", scope=("tasks:read",)))


# ------------------------------------------------------------------ audit and leaks
def test_one_content_free_event_per_call(ing, db_session, caplog):
    caplog.set_level(logging.DEBUG)
    body = POLICY + f"\n\nSecret-ish marker {CANARY}."
    r = ingest(ing, body, title=f"Title {CANARY}")
    ingest(ing, body.replace("14", "21"), title=f"Title {CANARY}")
    ing.delete(ADMIN(), "refund-policy")
    ev = events(db_session)
    assert [e.event_type for e in ev] == ["memory.document_ingested"] * 2 + ["memory.document_deleted"]
    assert ev[0].payload["chunks"] == r.chunks and ev[0].payload["document_id"] == "refund-policy"
    assert set(ev[0].payload) == {"document_id", "kind", "chunks", "replaced", "added", "removed", "content_chars"}
    assert all(CANARY not in str(e.payload) and e.actor == "u2" for e in ev)
    assert CANARY not in caplog.text
    assert not [e for e in events(db_session, "memory.created")]       # bulk path: one event per document, not per chunk


def test_document_chunks_cannot_be_forged_through_the_normal_write_path(svc):
    draft = MemoryDraft(kind=K.KNOWLEDGE, title="t", content="c", source=SourceRef(SK.DOCUMENT, "refund-policy"))
    with pytest.raises(MemoryForbiddenError):
        svc.replace_document(P("u1", role=Role.MEMBER), "refund-policy", [draft])
    with pytest.raises(MemoryForbiddenError):
        svc.replace_document(ADMIN(), "other-doc", [draft])           # source does not match the document id
    with pytest.raises(InvalidMemoryError):
        svc.replace_document(ADMIN(), "refund-policy", [])
    with pytest.raises(MemoryForbiddenError):                         # agent/user sources are never document chunks
        svc.replace_document(ADMIN(), "u2", [MemoryDraft(kind=K.OPERATIONAL, title="t", content="c", source=SourceRef(SK.USER, "u2"))])


def test_trusted_document_dedupe_is_per_document_and_still_repeatable(svc):
    mk = lambda ref: MemoryDraft(kind=K.KNOWLEDGE, title="Same", content="Same text.", source=SourceRef(SK.DOCUMENT, ref))  # noqa: E731
    a1, a2, b = svc.create_trusted(ADMIN(), mk("doc-a")), svc.create_trusted(ADMIN(), mk("doc-a")), svc.create_trusted(ADMIN(), mk("doc-b"))
    assert a1.id == a2.id and b.id != a1.id


def test_new_settings_are_bounded():
    for kw in ({"memory_max_document_chars": 999}, {"memory_max_document_chars": 2000001},
               {"memory_max_chunks_per_document": 0}, {"memory_max_chunks_per_document": 501},
               {"memory_chunk_chars": 199}, {"memory_chunk_chars": 4001}):
        with pytest.raises(ValidationError):
            mk_settings(**kw)
    s = mk_settings()
    assert (s.memory_max_document_chars, s.memory_max_chunks_per_document, s.memory_chunk_chars) == (100000, 100, 1000)


def test_chunks_are_ordinary_pure_items_for_the_ranker(ing, db_session):
    ingest(ing)
    items = [to_item(r) for r in rows(db_session)]
    assert all(i.source.kind == SK.DOCUMENT and i.scope_ref for i in items)
    assert rank("shipping express", items, T0)[0].item.content.startswith("Shipping")
