"""Substep 8.2: memory persistence, access rules, lifecycle, purge-on-end, content-free audit."""
import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.config import Settings
from app.identity.roles import permissions_for
from app.kernel.permissions import Principal
from app.memory.errors import (InvalidMemoryError, MemoryConflictError, MemoryForbiddenError, MemoryLimitError,
                               MemoryNotFoundError)
from app.memory.model import MemoryDraft, MemoryKind as K, SourceKind as SK, SourceRef, rank
from app.memory.store import MemoryService
from app.models import Role, SystemEvent
from app.models.enums import MemoryStatus as M
from app.models.identity import User
from app.models.memory import MemoryRecord

pytestmark = pytest.mark.usefixtures("seed_workspaces")
CANARY = "CANARY-memory-4417"
T0 = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now

    def advance(self, **kw):
        self.now += timedelta(**kw)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def users(db_session):
    for u in ("u1", "u2", "u3", "u4"):
        db_session.add(User(id=u, email=f"{u}@x.com", password_hash="h"))
    db_session.commit()


@pytest.fixture
def svc(db_session, clock, users):
    return MemoryService(db_session, Settings(app_env="test", database_url="sqlite:///:memory:", _env_file=None),
                         clock=clock)


def P(uid="u1", ws="w1", role=Role.MEMBER, agent=None, scope=None):
    perms = permissions_for(role)
    if agent:
        perms = frozenset(p for p in perms if scope is None or p in scope or (p.endswith(":*") and any(
            s.startswith(p[:-1]) for s in scope)))
    return Principal(user_id=uid, workspace_id=ws, permissions=perms, agent=agent,
                     agent_scope=frozenset(scope) if scope is not None else None)


ADMIN = lambda uid="u2", ws="w1": P(uid, ws, Role.ADMIN)          # noqa: E731


def D(kind=K.OPERATIONAL, title="Refund policy", content="Refunds are issued within 14 days.", uid="u1", **kw):
    src = kw.pop("source", SourceRef(SK.USER, uid))
    if kind == K.PREFERENCE:
        kw.setdefault("owner_user_id", uid)
    return MemoryDraft(kind=kind, title=title, content=content, source=src, **kw)


def agent_draft(agent="ops_agent", kind=K.OPERATIONAL, content="Run finished fine"):
    return MemoryDraft(kind=kind, title="Agent note", content=content, source=SourceRef(SK.AGENT, agent))


def AG(agent="ops_agent", uid="u1", scope=("memory:read", "memory:write")):
    return Principal(user_id=uid, workspace_id="w1", permissions=frozenset(scope), agent=agent,
                     agent_scope=frozenset(scope))


def n(db, **where):
    q = select(func.count()).select_from(MemoryRecord)
    for k, v in where.items():
        q = q.where(getattr(MemoryRecord, k) == v)
    return db.scalar(q)


def events(db, prefix="memory."):
    return list(db.scalars(select(SystemEvent).where(SystemEvent.event_type.like(prefix + "%"))))


# ------------------------------------------------------------------ roles
def test_role_permissions_for_memory():
    assert permissions_for(Role.VIEWER) >= {"memory:read"} and "memory:write" not in permissions_for(Role.VIEWER)
    assert {"memory:read", "memory:write"} <= permissions_for(Role.MEMBER) and "memory:*" not in permissions_for(Role.MEMBER)
    assert "memory:*" in permissions_for(Role.ADMIN)
    assert P(role=Role.ADMIN).can("memory:manage") and not P().can("memory:manage")


# ------------------------------------------------------------------ create / read
def test_create_stores_with_provenance_ownership_and_expiry(svc, db_session):
    rec = svc.create(P(), D(tags=("policy",)))
    assert rec.workspace_id == "w1" and rec.status == M.ACTIVE and rec.version == 1 and rec.lineage_id == rec.id
    assert (rec.source_kind, rec.source_ref, rec.created_by) == (SK.USER, "u1", "u1")
    assert rec.expires_at is not None and rec.observed_at is not None and rec.tags == ["policy"]
    assert svc.get(P(), rec.id).id == rec.id


def test_viewer_cannot_write_but_can_read(svc):
    rec = svc.create(P(), D())
    v = P("u3", role=Role.VIEWER)
    assert svc.get(v, rec.id).id == rec.id
    with pytest.raises(MemoryForbiddenError):
        svc.create(v, D(uid="u3"))


def test_a_source_must_be_the_person_actually_writing(svc, db_session):
    with pytest.raises(MemoryForbiddenError):
        svc.create(P("u1"), D(source=SourceRef(SK.USER, "u2")))
    with pytest.raises(MemoryForbiddenError):
        svc.create(P("u1"), D(source=SourceRef(SK.AGENT, "ops_agent")))
    with pytest.raises(MemoryForbiddenError):                       # documents/connectors/system are not callers
        svc.create(ADMIN(), D(K.KNOWLEDGE, source=SourceRef(SK.DOCUMENT, "doc1")))
    assert n(db_session) == 0


def test_knowledge_needs_admin_but_operational_does_not(svc):
    with pytest.raises(MemoryForbiddenError):
        svc.create(P(), D(K.KNOWLEDGE))
    assert svc.create(ADMIN(), D(K.KNOWLEDGE, uid="u2")).kind == K.KNOWLEDGE
    assert svc.create(P(), D(K.OPERATIONAL)).kind == K.OPERATIONAL


def test_trusted_ingestion_is_admin_only_and_never_for_user_or_agent_sources(svc):
    doc = D(K.KNOWLEDGE, source=SourceRef(SK.DOCUMENT, "doc-1", "Handbook"))
    rec = svc.create_trusted(ADMIN(), doc)
    assert (rec.source_kind, rec.source_label) == (SK.DOCUMENT, "Handbook")
    for bad in (P(), AG(scope=("memory:read", "memory:write", "memory:manage"))):
        with pytest.raises(MemoryForbiddenError):
            svc.create_trusted(bad, D(K.KNOWLEDGE, source=SourceRef(SK.DOCUMENT, "d2")))
    with pytest.raises(MemoryForbiddenError):
        svc.create_trusted(ADMIN(), D(K.OPERATIONAL, uid="u2"))     # a USER source must use create()


def test_duplicate_writes_return_the_existing_item(svc, db_session):
    a = svc.create(P(), D())
    b = svc.create(P("u3"), D(uid="u3"))                                  # same content, shared kind: same item
    assert a.id == b.id and n(db_session) == 1 and len(events(db_session, "memory.created")) == 1


def test_short_term_and_preferences_dedupe_per_person(svc, db_session):
    a, b = svc.create(P("u1"), D(K.SHORT_TERM)), svc.create(P("u3"), D(K.SHORT_TERM, uid="u3"))
    p1, p2 = svc.create(P("u1"), D(K.PREFERENCE)), svc.create(P("u3"), D(K.PREFERENCE, uid="u3"))
    assert a.id != b.id and p1.id != p2.id and n(db_session) == 4


# ------------------------------------------------------------------ visibility
def test_preferences_are_private_even_from_admins_and_owners(svc):
    pref = svc.create(P("u1"), D(K.PREFERENCE))
    for who in (P("u3"), ADMIN(), P("u9", role=Role.OWNER)):
        with pytest.raises(MemoryNotFoundError):
            svc.get(who, pref.id)
        assert svc.list(who) == []
        with pytest.raises(MemoryNotFoundError):
            svc.delete(who, pref.id)
    assert [r.id for r in svc.list(P("u1"))] == [pref.id]


def test_short_term_is_visible_to_its_creator_and_admins_only(svc):
    st = svc.create(P("u1"), D(K.SHORT_TERM))
    assert svc.get(ADMIN(), st.id).id == st.id and svc.get(P("u1"), st.id).id == st.id
    with pytest.raises(MemoryNotFoundError):
        svc.get(P("u3"), st.id)
    assert svc.list(P("u3")) == []


def test_operational_and_knowledge_are_visible_to_every_reader(svc):
    a, b = svc.create(P(), D()), svc.create(ADMIN(), D(K.KNOWLEDGE, content="We sell widgets.", uid="u2"))
    ids = {r.id for r in svc.list(P("u3", role=Role.VIEWER))}
    assert ids == {a.id, b.id}
    assert {r.id for r in svc.list(P("u3"), kind=K.KNOWLEDGE)} == {b.id}


def test_other_workspaces_are_invisible_and_isolated(svc, db_session):
    a = svc.create(P(ws="w1"), D())
    b = svc.create(P(ws="w2"), D())                                      # same content, other workspace: own item
    assert a.id != b.id
    for verb in (svc.get, svc.delete):
        with pytest.raises(MemoryNotFoundError):
            verb(P(ws="w2"), a.id)
    assert [r.id for r in svc.list(P(ws="w2"))] == [b.id] and [i.id for i in svc.candidates(P(ws="w1"))] == [a.id]
    with pytest.raises(MemoryNotFoundError):
        svc.supersede(P(ws="w2"), a.id, D())
    assert svc.get(P(ws="w1"), a.id).content.startswith("Refunds")


def test_reading_needs_the_read_permission(svc):
    rec = svc.create(P(), D())
    nobody = Principal(user_id="u1", workspace_id="w1", permissions=frozenset())
    for call in (lambda: svc.get(nobody, rec.id), lambda: svc.list(nobody), lambda: svc.candidates(nobody)):
        with pytest.raises(MemoryForbiddenError):
            call()


def test_expired_but_unswept_items_are_already_invisible(svc, clock):
    rec = svc.create(P(), D(K.SHORT_TERM, ttl_seconds=60))
    clock.advance(seconds=61)
    with pytest.raises(MemoryNotFoundError):
        svc.get(P(), rec.id)
    assert svc.list(P()) == [] and svc.candidates(P()) == []


def test_candidates_feed_the_pure_ranker(svc, clock):
    svc.create(P(), D(title="Refund policy", content="Refunds within 14 days"))
    svc.create(P(), D(title="Shipping", content="Ships in 3 days"))
    r = rank("refund policy", svc.candidates(P()), clock())
    assert [x.item.title for x in r] == ["Refund policy"]


# ------------------------------------------------------------------ agents
def test_agents_write_only_as_themselves_only_short_term_or_operational_and_only_with_scope(svc):
    rec = svc.create(AG(), agent_draft())
    assert rec.created_by_agent == "ops_agent" and rec.created_by == "u1" and rec.source_kind == SK.AGENT
    with pytest.raises(MemoryForbiddenError):
        svc.create(AG(), agent_draft(agent="insight_agent"))                        # another agent's name
    with pytest.raises(MemoryForbiddenError):
        svc.create(AG(), D(K.OPERATIONAL))                                          # a USER source
    with pytest.raises(MemoryForbiddenError):
        svc.create(AG(scope=("memory:read",)), agent_draft(content="x"))            # no write in scope
    with pytest.raises(InvalidMemoryError):
        agent_draft(kind=K.KNOWLEDGE)                                               # the pure rule too


def test_an_agent_can_change_only_what_it_created(svc):
    mine = svc.create(AG(), agent_draft())
    human = svc.create(P(), D(content="Human note"))
    new = svc.supersede(AG(), mine.id, agent_draft(content="Updated"))
    assert new.version == 2
    with pytest.raises(MemoryForbiddenError):
        svc.supersede(AG(), human.id, agent_draft(content="Overwrite"))
    with pytest.raises(MemoryForbiddenError):
        svc.delete(AG(), human.id)
    assert svc.get(P(), human.id).content == "Human note"
    with pytest.raises(MemoryForbiddenError):
        svc.delete(AG("insight_agent"), new.id)


# ------------------------------------------------------------------ supersede / delete / purge
def test_supersede_creates_a_new_version_and_purges_the_old_content(svc, db_session):
    old = svc.create(P(), D(content=f"Old policy {CANARY}", tags=("t",)))
    new = svc.supersede(P(), old.id, D(content="New policy text"))
    assert new.version == 2 and new.lineage_id == old.lineage_id and new.supersedes_id == old.id
    db_session.refresh(old)
    assert old.status == M.SUPERSEDED and old.content == "" and old.title == "" and old.tags == [] and old.dedupe_key is None
    assert old.content_chars > 0 and old.source_ref == "u1" and old.ended_by == "u1"      # metadata stays
    with pytest.raises(MemoryNotFoundError):
        svc.get(P(), old.id)
    with pytest.raises(MemoryNotFoundError):
        svc.supersede(P(), old.id, D(content="again"))                                     # cannot revive
    assert CANARY not in str(db_session.execute(text("select title, content, tags from memory_items")).all())


def test_supersede_rules(svc):
    rec = svc.create(P(), D())
    with pytest.raises(InvalidMemoryError):
        svc.supersede(P(), rec.id, D(K.SHORT_TERM))                                         # kind must match
    other = svc.create(P(), D(content="Different note"))
    with pytest.raises(MemoryConflictError):
        svc.supersede(P(), rec.id, D(content="Different note"))                              # would duplicate another
    with pytest.raises(MemoryForbiddenError):
        svc.supersede(P("u3", role=Role.VIEWER), rec.id, D(uid="u3", content="x"))
    with pytest.raises(MemoryForbiddenError):
        svc.supersede(P("u3"), rec.id, D(uid="u3", content="x"))                             # not the creator, not admin
    assert svc.supersede(ADMIN(), rec.id, D(uid="u2", content="Admin edit")).created_by == "u2"
    assert other.status == M.ACTIVE


def test_supersede_with_identical_content_keeps_one_active_row(svc, db_session):
    rec = svc.create(P(), D(tags=("a",)))
    new = svc.supersede(P(), rec.id, D(tags=("b",)))                                         # same text, new tags
    assert new.tags == ["b"] and n(db_session, status=M.ACTIVE) == 1


def test_knowledge_and_preference_edit_rules(svc):
    k = svc.create(ADMIN(), D(K.KNOWLEDGE, uid="u2"))
    with pytest.raises(MemoryForbiddenError):
        svc.supersede(P(), k.id, D(K.KNOWLEDGE, content="member edit"))
    with pytest.raises(MemoryForbiddenError):
        svc.delete(P(), k.id)
    pref = svc.create(P("u1"), D(K.PREFERENCE))
    new = svc.supersede(P("u1"), pref.id, D(K.PREFERENCE, content="I prefer short emails"))
    assert new.owner_user_id == "u1"
    with pytest.raises(MemoryNotFoundError):
        svc.supersede(ADMIN(), new.id, D(K.PREFERENCE, uid="u2"))


def test_delete_really_deletes_is_idempotent_and_frees_the_content(svc, db_session):
    rec = svc.create(P(), D(content=f"Secret plan {CANARY}"))
    out = svc.delete(P(), rec.id)
    assert out.status == M.DELETED and out.content == "" and out.title == "" and out.ended_by == "u1"
    assert svc.delete(P(), rec.id).status == M.DELETED and len(events(db_session, "memory.deleted")) == 1
    assert CANARY not in str(db_session.execute(text("select title, content from memory_items")).all())
    with pytest.raises(MemoryNotFoundError):
        svc.get(P(), rec.id)
    again = svc.create(P(), D(content=f"Secret plan {CANARY}"))                              # the content may be recorded anew
    assert again.id != rec.id and again.status == M.ACTIVE


def test_delete_authority(svc):
    mine = svc.create(P("u1"), D())
    with pytest.raises(MemoryForbiddenError):
        svc.delete(P("u3"), mine.id)                                                         # a peer cannot delete it
    assert svc.delete(ADMIN(), mine.id).status == M.DELETED
    with pytest.raises(MemoryForbiddenError):
        svc.delete(P("u3", role=Role.VIEWER), svc.create(P(), D(content="other")).id)


# ------------------------------------------------------------------ expiry sweep
def test_expire_overdue_purges_content_and_is_scoped_and_repeatable(svc, db_session, clock):
    a = svc.create(P(ws="w1"), D(K.SHORT_TERM, content=f"temp {CANARY}", ttl_seconds=60))
    b = svc.create(P(ws="w2"), D(K.SHORT_TERM, content="other workspace temp", ttl_seconds=60))
    keep = svc.create(P(ws="w1"), D(K.OPERATIONAL))
    clock.advance(seconds=120)
    assert svc.expire_overdue("w1") == 1 and svc.expire_overdue("w1") == 0
    db_session.refresh(a), db_session.refresh(b), db_session.refresh(keep)
    assert a.status == M.EXPIRED and a.content == "" and b.status == M.ACTIVE and b.content and keep.status == M.ACTIVE
    assert len(events(db_session, "memory.expired")) == 1


# ------------------------------------------------------------------ limits
def test_workspace_and_preference_limits(db_session, clock, users):
    s = MemoryService(db_session, Settings(app_env="test", database_url="sqlite:///:memory:", _env_file=None,
                                           memory_max_items=3, memory_max_preferences_per_user=1), clock=clock)
    s.create(P(), D(content="one")), s.create(P(), D(content="two"))
    s.create(P(), D(K.PREFERENCE, content="pref one"))
    with pytest.raises(MemoryLimitError):
        s.create(P(), D(content="three"))
    other = P(ws="w2")
    s.create(other, D(content="w2 one"))                                                     # per-workspace, not global
    s2 = MemoryService(db_session, Settings(app_env="test", database_url="sqlite:///:memory:", _env_file=None,
                                            memory_max_preferences_per_user=1), clock=clock)
    with pytest.raises(MemoryLimitError):
        s2.create(P(), D(K.PREFERENCE, content="pref two"))
    s.delete(P(), s.list(P(), kind=K.OPERATIONAL)[0].id)
    assert s.create(P(), D(content="three")).status == M.ACTIVE                              # deleting frees capacity


@pytest.mark.parametrize("limit", [0, 201, True, "5"])
def test_list_limit_is_bounded(svc, limit):
    with pytest.raises(InvalidMemoryError):
        svc.list(P(), limit=limit)


# ------------------------------------------------------------------ database guarantees
def test_database_blocks_ownerless_preferences_and_owned_non_preferences(svc, db_session):
    base = dict(workspace_id="w1", title="t", content="c", tags=[], content_chars=1, content_digest="d",
                source_kind=SK.USER, source_ref="u1", observed_at=T0, created_by="u1", version=1, lineage_id="l")
    for kind, owner in ((K.PREFERENCE, None), (K.OPERATIONAL, "u1")):
        db_session.add(MemoryRecord(kind=kind, owner_user_id=owner, **base))
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()


def test_database_enforces_one_active_row_per_dedupe_key(svc, db_session):
    rec = svc.create(P(), D())
    clone = MemoryRecord(workspace_id="w1", kind=K.OPERATIONAL, title="t", content="c", tags=[], content_chars=1,
                         content_digest="d", dedupe_key=rec.dedupe_key, source_kind=SK.USER, source_ref="u1",
                         observed_at=T0, created_by="u1", version=1, lineage_id="l")
    db_session.add(clone)
    with pytest.raises(IntegrityError):
        db_session.commit()


# ------------------------------------------------------------------ audit / leaks
def test_audit_is_content_free_and_complete(svc, db_session, caplog):
    with caplog.at_level("DEBUG"):
        r = svc.create(P(), D(title=f"Title {CANARY}", content=f"Body {CANARY}", tags=("secret-tag",)))
        r2 = svc.supersede(P(), r.id, D(title=f"Title2 {CANARY}", content=f"Body2 {CANARY}"))
        svc.delete(P(), r2.id)
        svc.create(P(), D(K.SHORT_TERM, content=f"temp {CANARY}", ttl_seconds=60))
    types = [x.event_type for x in events(db_session)]
    assert types == ["memory.created", "memory.superseded", "memory.deleted", "memory.created"]
    blob = json.dumps([x.payload for x in events(db_session)]) + caplog.text
    assert CANARY not in blob and "secret-tag" not in blob
    first = events(db_session)[0].payload
    assert set(first) == {"memory_id", "kind", "source_kind", "version", "content_chars", "agent"}
    assert {x.workspace_id for x in events(db_session)} == {"w1"}
