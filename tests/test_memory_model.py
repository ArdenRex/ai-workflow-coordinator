"""Step 8.1: the pure memory model: validation, governed writes, freshness, ranking."""
import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.memory.errors import InvalidMemoryError
from app.memory.model import (MAX_CONTENT_CHARS, MAX_TAGS, TRUST, Freshness, MemoryDraft, MemoryItem, MemoryKind as K,
                              SourceKind as SK, SourceRef, contains_secret, explain, freshness, rank, tokenize)

NOW = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)
DAY = timedelta(days=1)


def src(kind=SK.USER, ref="u1", label=None):
    return SourceRef(kind, ref, label)


def draft(kind=K.KNOWLEDGE, title="Refund policy", content="Refunds are issued within 14 days.", source=None, **kw):
    return MemoryDraft(kind=kind, title=title, content=content, source=source or src(), **kw)


def item(d=None, id="m1", ws="w1", now=NOW):
    return MemoryItem.from_draft(d or draft(), id=id, workspace_id=ws, now=now)


def code(fn):
    with pytest.raises(InvalidMemoryError) as e:
        fn()
    return e.value.code


# ------------------------------------------------------------------ validation
def test_a_valid_draft_is_normalised_and_immutable():
    d = draft(title="  Refund policy  ", tags=("policy", "refunds"))
    assert d.title == "Refund policy" and d.tags == ("policy", "refunds")
    with pytest.raises(Exception):
        d.title = "x"


@pytest.mark.parametrize("kw,expected", [
    ({"title": "  "}, "invalid_title"), ({"title": "x" * 121}, "invalid_title"), ({"title": 5}, "invalid_title"),
    ({"content": ""}, "invalid_content"), ({"content": "x" * (MAX_CONTENT_CHARS + 1)}, "invalid_content"),
    ({"content": "bad\x00byte"}, "invalid_content"), ({"content": "bell\x07"}, "invalid_content"),
    ({"tags": ("Upper",)}, "invalid_tags"), ({"tags": ("a b",)}, "invalid_tags"), ({"tags": ("a", "a")}, "invalid_tags"),
    ({"tags": tuple(f"t{i}" for i in range(MAX_TAGS + 1))}, "invalid_tags"),
    ({"ttl_seconds": 3600}, "ttl_not_allowed"),                                   # knowledge takes no ttl
    ({"owner_user_id": "u1"}, "owner_not_allowed"), ({"scope_ref": " "}, "invalid_scope"),
])
def test_invalid_drafts_are_refused_with_fixed_codes(kw, expected):
    assert code(lambda: draft(**kw)) == expected


def test_newlines_and_tabs_are_allowed_but_other_control_characters_are_not():
    assert draft(content="line one\nline two\tend").content.startswith("line one")


@pytest.mark.parametrize("ttl,ok", [(59, False), (60, True), (86400, True), (86401, False), (True, False), (3600.5, False)])
def test_short_term_ttl_bounds(ttl, ok):
    make = lambda: draft(K.SHORT_TERM, ttl_seconds=ttl)
    if ok:
        assert make().ttl_seconds == ttl
    else:
        assert code(make) == "invalid_ttl"


def test_default_lifetimes_by_kind():
    assert draft(K.SHORT_TERM).effective_ttl() == 3600
    assert draft(K.OPERATIONAL).effective_ttl() == 30 * 86400
    assert draft(K.KNOWLEDGE).effective_ttl() is None
    assert item(draft(K.KNOWLEDGE)).expires_at is None
    assert item(draft(K.SHORT_TERM)).expires_at == NOW + timedelta(hours=1)


# ------------------------------------------------------------------ governed writes
@pytest.mark.parametrize("kind", [K.KNOWLEDGE, K.PREFERENCE])
@pytest.mark.parametrize("source", [SK.AGENT, SK.SYSTEM])
def test_agents_and_the_system_can_never_create_durable_memory(kind, source):
    kw = {"owner_user_id": "u1"} if kind == K.PREFERENCE else {}
    assert code(lambda: draft(kind, source=src(source, "u1"), **kw)) == "source_not_allowed"


@pytest.mark.parametrize("kind", [K.SHORT_TERM, K.OPERATIONAL])
def test_agents_may_write_short_term_and_operational_memory(kind):
    assert draft(kind, source=src(SK.AGENT, "ops_agent")).kind == kind


def test_documents_and_connectors_may_write_knowledge_but_never_preferences():
    assert draft(K.KNOWLEDGE, source=src(SK.DOCUMENT, "doc1")).kind == K.KNOWLEDGE
    assert draft(K.KNOWLEDGE, source=src(SK.CONNECTOR, "crm")).kind == K.KNOWLEDGE
    for s in (SK.DOCUMENT, SK.CONNECTOR):
        assert code(lambda: draft(K.PREFERENCE, source=src(s, "u1"), owner_user_id="u1")) == "source_not_allowed"


def test_a_preference_belongs_to_exactly_the_user_who_states_it():
    assert draft(K.PREFERENCE, owner_user_id="u1").owner_user_id == "u1"
    assert code(lambda: draft(K.PREFERENCE)) == "owner_required"
    assert code(lambda: draft(K.PREFERENCE, owner_user_id="u2")) == "source_not_allowed"      # u1 cannot record u2's


def test_a_draft_needs_a_real_source():
    assert code(lambda: MemoryDraft(kind=K.KNOWLEDGE, title="t", content="c", source=None)) == "invalid_source"


@pytest.mark.parametrize("ref,label", [("", None), ("x" * 201, None), ("a\x00b", None), ("ok", "y" * 121), ("ok", "a\x07")])
def test_source_refs_are_validated(ref, label):
    assert code(lambda: SourceRef(SK.USER, ref, label)) == "invalid_source"


# ------------------------------------------------------------------ secrets
@pytest.mark.parametrize("text", [
    "key is sk-abcdef0123456789abcdef", "-----BEGIN RSA PRIVATE KEY-----", "AKIAABCDEFGHIJKLMNOP",
    "password: hunter2hunter2", "api_key=abcd1234efgh", "Authorization: Bearer abcdefghijklmnopqrstuvwx",
    "ghp_abcdefghijklmnopqrstuvwxyz0123", "xoxb-1234567890-abcdefghij",
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijk"])
def test_credential_looking_content_is_rejected_without_echoing_it(text):
    assert contains_secret(text)
    with pytest.raises(InvalidMemoryError) as e:
        draft(content=text)
    assert e.value.code == "secret_detected" and text not in str(e.value)
    assert code(lambda: draft(title=text)) == "secret_detected"


@pytest.mark.parametrize("text", ["Our refund window is 14 days", "The token budget is a planning concept",
                                  "Call the sales team on Monday", "Password reset is handled by IT"])
def test_ordinary_business_text_is_not_flagged(text):
    assert not contains_secret(text)


# ------------------------------------------------------------------ freshness
def at(days, kind=K.KNOWLEDGE, ttl=None, **kw):
    d = draft(kind, ttl_seconds=ttl, **kw)
    return freshness(item(d, now=NOW - timedelta(days=days)), NOW)


def test_knowledge_goes_aging_then_stale_never_expired():
    assert at(0) == Freshness.FRESH and at(134) == Freshness.FRESH
    assert at(136) == Freshness.AGING and at(179) == Freshness.AGING
    assert at(180) == Freshness.STALE and at(5000) == Freshness.STALE


def test_operational_and_short_term_expire():
    assert at(1, K.OPERATIONAL) == Freshness.FRESH and at(23, K.OPERATIONAL) == Freshness.AGING
    assert at(29, K.OPERATIONAL) == Freshness.AGING and at(31, K.OPERATIONAL) == Freshness.EXPIRED
    assert at(0, K.SHORT_TERM, ttl=3600) == Freshness.FRESH
    old = item(draft(K.SHORT_TERM), now=NOW - timedelta(hours=2))
    assert freshness(old, NOW) == Freshness.EXPIRED


def test_aging_starts_in_the_last_quarter_of_a_bounded_lifetime():
    it = item(draft(K.OPERATIONAL, ttl_seconds=1000), now=NOW)
    assert freshness(it, NOW + timedelta(seconds=749)) == Freshness.FRESH
    assert freshness(it, NOW + timedelta(seconds=750)) == Freshness.AGING
    assert freshness(it, NOW + timedelta(seconds=1000)) == Freshness.EXPIRED


def test_a_future_dated_observation_is_never_fresher_than_now():
    it = item(now=NOW + timedelta(days=400))
    assert freshness(it, NOW) == Freshness.FRESH


# ------------------------------------------------------------------ explain
def test_explain_answers_what_where_current_and_whose():
    it = item(draft(source=src(SK.DOCUMENT, "doc-7", "Employee handbook")), ws="acme")
    e = explain(it, NOW + timedelta(days=200))
    assert e["workspace_id"] == "acme" and e["source"] == {"kind": "document", "ref": "doc-7", "label": "Employee handbook"}
    assert e["freshness"] == "stale" and e["observed_at"].startswith("2026-11-08") and e["title"] == "Refund policy"
    assert "content" not in e


# ------------------------------------------------------------------ ranking
def mk(id, title, content="", tags=(), kind=K.KNOWLEDGE, source=None, days=0):
    return item(draft(kind, title, content or "generic text here", source=source or src(), tags=tags), id=id,
                now=NOW - timedelta(days=days))


def ids(r):
    return [x.item.id for x in r]


def test_tokenize_drops_stopwords_and_punctuation():
    assert tokenize("What is OUR refund policy?!") == ["refund", "policy"]


def test_title_beats_tags_beats_content():
    items = [mk("c", "other", "refund details"), mk("t", "refund rules"), mk("g", "other", tags=("refund",))]
    assert ids(rank("refund", items, NOW)) == ["t", "g", "c"]


def test_more_matching_tokens_rank_higher_and_zero_matches_are_dropped():
    items = [mk("one", "refund"), mk("two", "refund policy"), mk("none", "shipping times")]
    assert ids(rank("refund policy", items, NOW)) == ["two", "one"]
    assert rank("", items, NOW) == [] and rank("the of a", items, NOW) == []


def test_expired_items_never_appear_and_stale_ones_are_flagged_and_down_ranked():
    fresh, stale = mk("f", "refund policy"), mk("s", "refund policy", days=200)
    expired = mk("e", "refund policy", kind=K.SHORT_TERM, days=2)
    r = rank("refund policy", [stale, expired, fresh], NOW)
    assert ids(r) == ["f", "s"] and r[1].freshness == Freshness.STALE and r[0].score > r[1].score
    assert ids(rank("refund policy", [stale, fresh], NOW, include_stale=False)) == ["f"]


def test_agent_sourced_memory_ranks_below_equal_human_sourced_memory():
    human = mk("h", "refund policy", kind=K.OPERATIONAL, source=src(SK.USER, "u1"))
    agent = mk("a", "refund policy", kind=K.OPERATIONAL, source=src(SK.AGENT, "ops_agent"))
    assert ids(rank("refund policy", [agent, human], NOW)) == ["h", "a"] and TRUST[SK.AGENT] < TRUST[SK.USER]


def test_ranking_is_deterministic_regardless_of_input_order():
    items = [mk("b", "refund", days=1), mk("a", "refund", days=1), mk("z", "refund", days=0)]
    expected = ["z", "a", "b"]                                  # same score: newest first, then id
    for perm in (items, items[::-1], [items[1], items[2], items[0]]):
        assert ids(rank("refund", perm, NOW)) == expected


@pytest.mark.parametrize("limit", [0, 51, True, "5"])
def test_limits_are_bounded(limit):
    assert code(lambda: rank("x", [], NOW, limit)) == "invalid_limit"


def test_limit_and_query_size_are_enforced():
    items = [mk(f"i{k}", "refund") for k in range(5)]
    assert len(rank("refund", items, NOW, 2)) == 2
    assert code(lambda: rank("x" * 501, items, NOW)) == "invalid_query"
    assert code(lambda: rank(None, items, NOW)) == "invalid_query"


# ------------------------------------------------------------------ digests / purity
def test_digest_is_stable_across_whitespace_case_tags_and_source_but_not_content():
    a = draft(content="Refunds  are issued within 14 days.", tags=("a",))
    b = draft(content="refunds are issued within 14 days.", tags=("b",), source=src(SK.DOCUMENT, "d"))
    assert a.content_digest() == b.content_digest()
    assert a.content_digest() != draft(content="Refunds within 30 days.").content_digest()
    assert a.content_digest() != draft(K.OPERATIONAL, content="Refunds  are issued within 14 days.").content_digest()


def test_the_memory_model_is_pure_no_database_llm_or_io_imports():
    for f in ("model.py", "errors.py"):
        tree = ast.parse((Path(__file__).parent.parent / "app" / "memory" / f).read_text())
        mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        mods |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        banned = ("sqlalchemy", "app.models", "app.llm", "app.database", "requests", "httpx", "os", "socket", "subprocess")
        assert not [m for m in mods if m.split(".")[0] in {b.split(".")[0] for b in banned} and
                    not m.startswith("app.memory")], mods
