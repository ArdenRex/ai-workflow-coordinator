"""Substep 8.4: retrieval service - visibility, provenance, freshness honesty, bounds, audit."""
import logging
from datetime import timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from app.config import Settings
from app.memory import store as store_mod
from app.memory.errors import InvalidMemoryError, MemoryForbiddenError
from app.memory.ingest import DocumentIngestor
from app.memory.model import Freshness, MemoryKind as K, SourceKind as SK
from app.memory.retrieval import RetrievalService
from app.memory.store import MemoryService
from app.models import Role, SystemEvent
from app.models.memory import MemoryRecord
from tests.test_memory_store import ADMIN, AG, CANARY, D, P, Clock, clock, users  # noqa: F401

pytestmark = pytest.mark.usefixtures("seed_workspaces")
VIEWER = lambda ws="w1": P("u3", ws, Role.VIEWER)  # noqa: E731


def mk(**kw):
    return Settings(app_env="test", database_url="sqlite:///:memory:", _env_file=None, **kw)


@pytest.fixture
def svc(db_session, clock, users):  # noqa: F811
    return MemoryService(db_session, mk(memory_chunk_chars=200), clock=clock)


@pytest.fixture
def ret(svc):
    return RetrievalService(svc)


def know(svc, title, content, who=None, **kw):
    return svc.create(who or ADMIN(), D(K.KNOWLEDGE, title=title, content=content, uid="u2", **kw))


def events(db, t="memory.retrieved"):
    return list(db.scalars(select(SystemEvent).where(SystemEvent.event_type == t)))


def test_returns_relevant_hits_with_full_provenance(svc, ret, clock):
    k = know(svc, "Refund policy", "Refunds are issued within 14 days.", tags=("policy",))
    know(svc, "Office hours", "We are open on weekdays.")
    res = ret.retrieve(VIEWER(), "how many days for refunds")
    assert [h.memory_id for h in res.hits] == [k.id] and res.considered == 2 and not res.truncated
    h = res.hits[0]
    assert (h.kind, h.title, h.source_kind, h.source_ref, h.freshness, h.stale, h.tags) == (
        K.KNOWLEDGE, "Refund policy", SK.USER, "u2", Freshness.FRESH, False, ("policy",))
    assert h.observed_at == clock.now and h.expires_at is None and h.score > 0 and not res.has_stale


def test_document_chunks_report_their_document(svc, ret):
    DocumentIngestor(svc).ingest(ADMIN(), document_id="handbook", title="Staff handbook",
                                 text="Employees receive 20 days of paid leave per year.")
    h = ret.retrieve(VIEWER(), "paid leave").hits[0]
    assert (h.source_kind, h.source_ref, h.source_label) == (SK.DOCUMENT, "handbook", "Staff handbook")


def test_is_read_only_except_for_one_audit_event(svc, ret, db_session):
    know(svc, "Refund policy", "Refunds are issued within 14 days.")
    before = db_session.scalar(select(func.count()).select_from(MemoryRecord))
    snap = [(r.id, r.status, r.version, r.observed_at) for r in db_session.scalars(select(MemoryRecord))]
    ret.retrieve(VIEWER(), "refunds")
    assert db_session.scalar(select(func.count()).select_from(MemoryRecord)) == before
    assert snap == [(r.id, r.status, r.version, r.observed_at) for r in db_session.scalars(select(MemoryRecord))]
    assert len(events(db_session)) == 1


def test_workspaces_are_isolated(svc, ret):
    know(svc, "Refund policy", "Refunds are issued within 14 days.")
    assert ret.retrieve(P("u3", "w2", Role.VIEWER), "refunds").hits == ()
    assert len(ret.retrieve(VIEWER(), "refunds").hits) == 1


def test_needs_memory_read(svc, ret):
    know(svc, "Refund policy", "Refunds are issued within 14 days.")
    for who in (P("u3", role=Role.VIEWER, agent="a", scope=("tasks:read",)), AG(scope=("memory:write",))):
        with pytest.raises(MemoryForbiddenError):
            ret.retrieve(who, "refunds")


def test_preferences_are_private_and_never_given_to_agents(svc, ret):
    svc.create(P("u1"), D(K.PREFERENCE, title="Report style", content="Summaries as short bullet lists.", uid="u1"))
    assert len(ret.retrieve(P("u1"), "summaries bullet").hits) == 1
    assert ret.retrieve(ADMIN(), "summaries bullet").hits == ()            # not even admins
    assert ret.retrieve(P("u2", role=Role.MEMBER), "summaries bullet").hits == ()
    agent = P("u1", agent="ops_agent", scope=("memory:read",))
    assert ret.retrieve(agent, "summaries bullet").hits == ()
    assert ret.retrieve(agent, "summaries bullet", kinds=[K.PREFERENCE]).reason == "no_permitted_kinds"


def test_short_term_visibility_follows_the_store(svc, ret):
    svc.create(P("u1"), D(K.SHORT_TERM, title="Scratch", content="Draft quote for Acme pending.", ttl_seconds=3600))
    assert len(ret.retrieve(P("u1"), "acme quote").hits) == 1
    assert len(ret.retrieve(ADMIN(), "acme quote").hits) == 1
    assert ret.retrieve(P("u4", role=Role.MEMBER), "acme quote").hits == ()
    assert ret.retrieve(VIEWER(), "acme quote").hits == ()


def test_expired_deleted_and_superseded_content_is_never_returned(svc, ret, clock):
    a = svc.create(P("u1"), D(K.OPERATIONAL, title="Old plan", content="Launch is on Friday.", ttl_seconds=None))
    gone = svc.create(P("u1"), D(K.OPERATIONAL, title="Gone", content="Obsolete vendor note."))
    svc.delete(P("u1"), gone.id)
    svc.supersede(P("u1"), a.id, D(K.OPERATIONAL, title="Old plan", content="Launch moved to Monday."))
    assert ret.retrieve(VIEWER(), "obsolete vendor").hits == ()
    assert [h.content for h in ret.retrieve(VIEWER(), "launch").hits] == ["Launch moved to Monday."]
    clock.advance(days=31)                                                  # operational default life is 30 days
    assert ret.retrieve(VIEWER(), "launch").hits == ()


def test_stale_is_flagged_downranked_and_can_be_excluded(svc, ret, clock):
    old = know(svc, "Pricing", "Standard plan costs 20 dollars.")
    clock.advance(days=200)                                                 # knowledge goes stale after 180 days
    new = know(svc, "Pricing update", "Standard plan costs 25 dollars.")
    res = ret.retrieve(VIEWER(), "standard plan costs")
    assert [h.memory_id for h in res.hits] == [new.id, old.id] and res.has_stale
    assert [(h.stale, h.freshness) for h in res.hits] == [(False, Freshness.FRESH), (True, Freshness.STALE)]
    cur = ret.retrieve(VIEWER(), "standard plan costs", current_only=True)
    assert [h.memory_id for h in cur.hits] == [new.id] and not cur.has_stale


def test_one_source_cannot_crowd_out_the_rest(svc, ret):
    DocumentIngestor(svc).ingest(ADMIN(), document_id="big", title="Big doc",
                                 text="\n\n".join(f"Shipping rule {i}: " + "parcel " * 25 for i in range(8)))
    know(svc, "Shipping summary", "Shipping is free over 50 dollars.")
    res = ret.retrieve(VIEWER(), "shipping parcel rule", limit=10)
    assert sum(h.source_ref == "big" for h in res.hits) == 3 and any(h.source_ref == "u2" for h in res.hits)
    assert sum(h.source_ref == "big" for h in ret.retrieve(VIEWER(), "shipping parcel rule", limit=10, max_per_source=5).hits) == 5


def test_text_budget_cuts_the_list_and_says_so(db_session, clock, users):  # noqa: F811
    s = MemoryService(db_session, mk(memory_retrieval_max_chars=500), clock=clock)
    for i in range(4):
        know(s, f"Note {i}", f"alpha beta {i} " + "x" * 300 + f" {i}")
    res = RetrievalService(s).retrieve(VIEWER(), "alpha beta", limit=10)
    assert 1 <= len(res.hits) < 4 and res.budget_truncated
    assert sum(len(h.content) for h in res.hits) <= 500 or len(res.hits) == 1


def test_window_truncation_is_reported(svc, ret, monkeypatch):
    for i in range(5):
        know(svc, f"Fact {i}", f"widget fact number {i}")
    monkeypatch.setattr(store_mod, "MAX_CANDIDATES", 3)
    res = ret.retrieve(VIEWER(), "widget fact")
    assert res.truncated and res.considered == 3


def test_kinds_filter_and_limit(svc, ret):
    know(svc, "Policy A", "refund handling steps")
    svc.create(P("u1"), D(K.OPERATIONAL, title="Task note", content="refund handling in progress"))
    assert {h.kind for h in ret.retrieve(VIEWER(), "refund handling").hits} == {K.KNOWLEDGE, K.OPERATIONAL}
    assert {h.kind for h in ret.retrieve(VIEWER(), "refund handling", kinds=[K.KNOWLEDGE]).hits} == {K.KNOWLEDGE}
    assert len(ret.retrieve(VIEWER(), "refund handling", limit=1).hits) == 1


@pytest.mark.parametrize("kw", [dict(query=""), dict(query="   "), dict(query="x" * 501), dict(query=5),
                                dict(query="ok", limit=0), dict(query="ok", limit=21), dict(query="ok", limit=True),
                                dict(query="ok", max_per_source=0), dict(query="ok", kinds="knowledge"),
                                dict(query="ok", kinds=["knowledge"])])
def test_invalid_arguments_are_rejected(ret, kw):
    q = kw.pop("query")
    with pytest.raises(InvalidMemoryError):
        ret.retrieve(VIEWER(), q, **kw)


def test_query_without_searchable_words_returns_nothing_with_a_reason(svc, ret):
    know(svc, "Policy", "refund handling")
    res = ret.retrieve(VIEWER(), "the and of ?!")
    assert res.hits == () and res.reason == "no_searchable_terms"


def test_audit_is_content_free_and_lists_ids(svc, ret, db_session, caplog):
    caplog.set_level(logging.DEBUG)
    k = know(svc, f"Title {CANARY}", f"Body {CANARY} refunds apply.")
    q = f"refunds {CANARY}"
    ret.retrieve(AG(scope=("memory:read",)), q)
    ret.retrieve(VIEWER(), "nothing matches zzzz")
    ev = events(db_session)
    assert [e.payload["results"] for e in ev] == [1, 0] and ev[0].payload["memory_ids"] == [k.id]
    assert ev[0].payload["query_chars"] == len(q) and ev[0].payload["agent"] == "ops_agent"
    assert all(CANARY not in str(e.payload) for e in ev) and CANARY not in caplog.text


def test_results_are_deterministic(svc, ret):
    for i in range(4):
        know(svc, f"Fact {i}", "gadget warranty covers repairs")
    a = [h.memory_id for h in ret.retrieve(VIEWER(), "gadget warranty").hits]
    assert a == [h.memory_id for h in ret.retrieve(VIEWER(), "gadget warranty").hits]


def test_retrieval_setting_is_bounded():
    for v in (499, 100001):
        with pytest.raises(ValidationError):
            mk(memory_retrieval_max_chars=v)
    assert mk().memory_retrieval_max_chars == 8000
