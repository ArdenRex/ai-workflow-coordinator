"""Substep 8.5c: memory, document and search HTTP API + end-to-end use in an agent run."""
import json

import pytest
from tests.route_discovery import api_routes
from sqlalchemy import select

from app.models import SystemEvent
from app.models.memory import MemoryRecord
from tests.test_agent_runs_api import GOAL, base as agents_base, intent_json, plan_json, rig  # noqa: F401

CANARY = "CANARY-api-memory-5521"
DOC = ("Business system status checks are run by the operations team every morning. "
       "Escalate anything unusual to the on-call lead.")


def b(ws):
    return f"/workspaces/{ws['id']}/memory"


def upload(client, h, ws, doc="ops-handbook", title="Ops handbook", text=DOC, **kw):
    return client.put(f"{b(ws)}/documents/{doc}", json={"title": title, "text": text, **kw}, headers=h)


def item(kind="operational", title="Refund policy", content="Refunds are issued within 14 days.", **kw):
    return {"kind": kind, "title": title, "content": content, **kw}


def stored(db, **where):
    q = select(MemoryRecord)
    for k, v in where.items():
        q = q.where(getattr(MemoryRecord, k) == v)
    return list(db.scalars(q))


# ------------------------------------------------------------------ access
def test_route_sweep_anonymous_outsider_and_viewer(rig, app):
    client, hs, ws, other, script = rig
    routes = api_routes(app, startswith="/workspaces/{workspace_id}/memory")
    assert len(routes) >= 8                                    # a new memory route cannot silently skip this sweep
    for r in routes:
        for verb in r.methods - {"HEAD", "OPTIONS"}:
            path = r.path.replace("{workspace_id}", ws["id"]).replace("{memory_id}", "x").replace("{document_id}", "x")
            body = {"query": "x", "kind": "operational", "title": "t", "content": "c", "text": "t"}
            call = lambda h=None: client.request(verb, path, headers=h, json=None if verb in ("GET", "DELETE") else body)  # noqa: E731
            assert call().status_code == 401
            assert call(hs["outsider"]).status_code == 404
            if verb in ("DELETE", "PUT") or (verb == "POST" and not path.endswith("/search")):
                assert call(hs["viewer"]).status_code == 403          # viewers read; they never write
    assert client.get(b(ws), headers=hs["viewer"]).status_code == 200
    assert client.post(f"{b(ws)}/search", json={"query": "refunds"}, headers=hs["viewer"]).status_code == 200


def test_members_cannot_curate_knowledge_or_documents_admins_can(rig):
    client, hs, ws, *_ = rig
    assert client.post(b(ws), json=item("knowledge"), headers=hs["member"]).status_code == 403
    assert upload(client, hs["member"], ws).status_code == 403
    assert client.post(b(ws), json=item("knowledge"), headers=hs["admin"]).status_code == 201
    assert upload(client, hs["admin"], ws).status_code == 200


# ------------------------------------------------------------------ items
def test_item_is_recorded_as_the_caller_and_a_source_cannot_be_named(rig, db_session):
    client, hs, ws, *_ = rig
    r = client.post(b(ws), json=item(), headers=hs["member"])
    assert r.status_code == 201
    v = r.json()
    rec = stored(db_session, id=v["id"])[0]
    assert v["source"] == {"kind": "user", "ref": rec.created_by, "label": None} and v["freshness"] == "fresh"
    assert client.post(b(ws), json={**item(), "source": {"kind": "document", "ref": "x"}}, headers=hs["member"]).status_code == 422
    assert client.post(b(ws), json={**item(), "workspace_id": "w-other"}, headers=hs["member"]).status_code == 422


def test_secret_like_content_is_refused_without_echo_and_not_stored(rig, db_session):
    client, hs, ws, *_ = rig
    r = client.post(b(ws), json=item(content=f"password: {CANARY}"), headers=hs["member"])
    assert r.status_code == 422 and CANARY not in r.text and "secret_detected" in r.text
    assert stored(db_session) == []


def test_preferences_are_private_even_from_admins(rig):
    client, hs, ws, *_ = rig
    pid = client.post(b(ws), json=item("preference", "Tone", "Short answers please"), headers=hs["member"]).json()["id"]
    assert client.get(f"{b(ws)}/{pid}", headers=hs["member"]).status_code == 200
    assert client.get(f"{b(ws)}/{pid}", headers=hs["admin"]).status_code == 404
    assert client.get(f"{b(ws)}/{pid}", headers=hs["owner"]).status_code == 404
    assert pid not in [x["id"] for x in client.get(b(ws), headers=hs["admin"]).json()]
    assert client.delete(f"{b(ws)}/{pid}", headers=hs["admin"]).status_code == 404
    hits = client.post(f"{b(ws)}/search", json={"query": "short answers"}, headers=hs["admin"]).json()["hits"]
    assert hits == []


def test_delete_really_deletes_and_is_idempotent(rig, db_session):
    client, hs, ws, *_ = rig
    mid = client.post(b(ws), json=item(content=f"Refunds {CANARY} done"), headers=hs["member"]).json()["id"]
    assert client.delete(f"{b(ws)}/{mid}", headers=hs["member"]).status_code == 204
    rec = stored(db_session, id=mid)[0]
    assert rec.content == "" and rec.title == "" and CANARY not in json.dumps(rec.tags)
    assert client.get(f"{b(ws)}/{mid}", headers=hs["member"]).status_code == 404
    assert client.delete(f"{b(ws)}/{mid}", headers=hs["member"]).status_code == 204


def test_workspaces_are_isolated(rig):
    client, hs, ws, other, _ = rig
    mid = client.post(b(ws), json=item(), headers=hs["member"]).json()["id"]
    assert client.get(f"/workspaces/{other['id']}/memory/{mid}", headers=hs["outsider"]).status_code == 404
    assert client.delete(f"/workspaces/{other['id']}/memory/{mid}", headers=hs["outsider"]).status_code == 404
    assert client.post(f"/workspaces/{other['id']}/memory/search", json={"query": "refunds"},
                       headers=hs["outsider"]).json()["hits"] == []
    assert client.get(f"/workspaces/{ws['id']}/memory/{mid}", headers=hs["outsider"]).status_code == 404


# ------------------------------------------------------------------ documents + search
def test_document_lifecycle_replace_list_search_delete(rig, db_session):
    client, hs, ws, *_ = rig
    r = upload(client, hs["admin"], ws)
    assert r.json() == {"document_id": "ops-handbook", "status": "created", "chunks": 1, "added": 1, "replaced": 0, "removed": 0}
    assert upload(client, hs["admin"], ws).json()["status"] == "refreshed"
    docs = client.get(f"{b(ws)}/documents", headers=hs["viewer"]).json()
    assert [(d["document_id"], d["title"], d["chunks"]) for d in docs] == [("ops-handbook", "Ops handbook", 1)]
    assert "content" not in docs[0] and "text" not in docs[0]
    s = client.post(f"{b(ws)}/search", json={"query": "who runs status checks"}, headers=hs["viewer"]).json()
    h = s["hits"][0]
    assert h["source"] == {"kind": "document", "ref": "ops-handbook", "label": "Ops handbook"}
    assert h["freshness"] == "fresh" and not h["stale"] and "operations team" in h["content"] and s["considered"] == 1
    assert upload(client, hs["admin"], ws, text="Status checks now run at noon.").json()["status"] == "updated"
    new = client.post(f"{b(ws)}/search", json={"query": "status checks"}, headers=hs["viewer"]).json()["hits"]
    assert len(new) == 1 and "noon" in new[0]["content"] and not any("operations team" in x["content"] for x in new)
    assert client.delete(f"{b(ws)}/documents/ops-handbook", headers=hs["admin"]).json() == {"removed": 1}
    assert client.delete(f"{b(ws)}/documents/ops-handbook", headers=hs["admin"]).json() == {"removed": 0}
    assert client.get(f"{b(ws)}/documents", headers=hs["viewer"]).json() == []
    assert all(r.content == "" for r in stored(db_session, source_ref="ops-handbook"))


def test_document_validation_and_secrets_never_echo(rig, db_session):
    client, hs, ws, *_ = rig
    bad = upload(client, hs["admin"], ws, text=f"Our api_key: {CANARY}-zzz is in use")
    assert bad.status_code == 422 and CANARY not in bad.text and "secret_detected" in bad.text
    assert upload(client, hs["admin"], ws, doc="Bad Id").status_code == 422
    assert upload(client, hs["admin"], ws, title="two\nlines").status_code == 422
    assert upload(client, hs["admin"], ws, text="   ").status_code == 422
    assert client.put(f"{b(ws)}/documents/ok", json={"title": "t", "text": "x", "source": "x"}, headers=hs["admin"]).status_code == 422
    assert stored(db_session) == []


def test_search_validation_and_the_query_text_is_never_audited(rig, db_session):
    client, hs, ws, *_ = rig
    upload(client, hs["admin"], ws)
    q = "status qnonce-4488"
    assert client.post(f"{b(ws)}/search", json={"query": q}, headers=hs["member"]).status_code == 200
    for bad in ({"query": ""}, {"query": "x" * 501}, {"query": "x", "limit": 0}, {"query": "x", "limit": 21},
                {"query": "x", "kinds": ["nope"]}, {"query": "x", "extra": 1}):
        assert client.post(f"{b(ws)}/search", json=bad, headers=hs["member"]).status_code == 422
    blob = json.dumps([e.payload for e in db_session.scalars(select(SystemEvent))])
    assert "qnonce-4488" not in blob and "operations team" not in blob
    empty = client.post(f"{b(ws)}/search", json={"query": "the of and"}, headers=hs["member"]).json()
    assert empty["hits"] == [] and empty["reason"] == "no_searchable_terms"


# ------------------------------------------------------------------ end to end: memory reaches an agent prompt as data
def test_agent_run_prompt_carries_workspace_memory_as_untrusted_data(rig, db_session):
    client, hs, ws, other, script = rig
    upload(client, hs["admin"], ws)
    client.post(f"/workspaces/{other['id']}/memory", json=item("operational", "Rival", "Status checks belong to the rival firm"),
                headers=hs["outsider"])
    seen = []

    def spy(value):
        def f(request):
            seen.append(request)
            return value
        return f
    script.extend([spy(intent_json()), spy(plan_json())])
    r = client.post(f"{agents_base(ws)}/runs", json={"agent_id": "ops_agent", "goal": GOAL}, headers=hs["member"])
    assert r.status_code in (200, 201) and r.json()["status"] == "succeeded"
    texts = [m.content for req in seen for m in req.messages]
    mem = [t for t in texts if "operations team" in t]
    assert len(mem) == 2 and all("<untrusted_input>" in t and "never instructions" in t for t in mem)   # intent + planning
    assert not any("rival firm" in t for t in texts)                                                      # other workspace
    ev = [e for e in db_session.scalars(select(SystemEvent)) if e.event_type == "memory.context_used"]
    assert len(ev) == 2 and {e.payload["agent"] for e in ev} == {"ops_agent"}
    assert "operations team" not in json.dumps([e.payload for e in ev]) and GOAL not in json.dumps([e.payload for e in ev])


def test_a_viewer_cannot_use_memory_through_agents_and_a_run_without_memory_still_works(rig):
    client, hs, ws, other, script = rig
    script.extend([intent_json(), plan_json()])
    r = client.post(f"{agents_base(ws)}/runs", json={"agent_id": "ops_agent", "goal": GOAL}, headers=hs["member"])
    assert r.json()["status"] == "succeeded"                  # empty memory: prompts exactly as before
    assert client.post(f"{agents_base(ws)}/runs", json={"agent_id": "ops_agent", "goal": GOAL},
                       headers=hs["viewer"]).status_code == 403
