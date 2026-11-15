"""Step 14.4: credential security and real-foreign-id sweeps.

Part 1: a canary secret is pushed through every credential flow and must never appear in a response, an error, an audit event,
a log line, a repr, or a backup file. Part 2: resources that really exist in workspace A are addressed by id from workspace B's
owner on every workflow and memory route that takes an id: always a clean not-found, and A's data is never changed or shown."""
import logging
import sqlite3

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import backup as bk
from app.config import Settings, get_settings
from app.security.crypto import CredentialCipher, credential_aad
from tests.test_agent_runs_api import rig  # noqa: F401
from tests.test_memory_api import DOC, b as mem_base, item, upload
from tests.test_workflow_api import base as wf_base, define, sched_body, start, wf
from tests.test_workspace_connectors import mock_spec, public_dns  # noqa: F401

CANARY = "CANARY-cred-sec-7f3a91-do-not-leak"
PASSWORD = "Hunter2-canary-pass-4471"


def cbase(ws):
    return f"/workspaces/{ws['id']}/credentials"


def make(client, h, ws, secret=CANARY, name="prod"):
    r = client.post(cbase(ws), json={"provider": "aceden", "name": name, "secret": secret,
                                     "config": {"base_url": "https://aceden.test"}}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def all_tables_text(db):
    names = [r[0] for r in db.execute(text("select name from sqlite_master where type='table'")).all()] \
        if db.get_bind().dialect.name == "sqlite" else \
        [r[0] for r in db.execute(text("select tablename from pg_tables where schemaname='public'")).all()]
    out = []
    for t in names:
        for row in db.execute(text(f'select * from "{t}"')).all():
            out.extend(str(v) for v in row)
    return "\n".join(out)


# ============================================================ Part 1: secrets never leak
def test_canary_never_appears_in_any_response_event_log_or_table(client, rig, monkeypatch, caplog, db_session):
    _, hs, ws, _, _ = rig
    mock_spec(monkeypatch, server_key=CANARY)
    caplog.set_level(logging.DEBUG)
    seen = []
    cid = make(client, hs["admin"], ws)
    for r in (client.get(cbase(ws), headers=hs["admin"]), client.get(f"{cbase(ws)}/{cid}", headers=hs["admin"]),
              client.post(f"{cbase(ws)}/{cid}/test", headers=hs["admin"]),
              client.post(f"{cbase(ws)}/{cid}/rotate", json={"secret": CANARY + "-v2"}, headers=hs["admin"]),
              client.post(f"{cbase(ws)}/{cid}/rotate", json={"secret": CANARY + "-v2", "extra": CANARY}, headers=hs["admin"]),
              client.post(cbase(ws), json={"provider": "aceden", "name": "prod", "secret": CANARY}, headers=hs["admin"]),   # duplicate
              client.get(f"{cbase(ws)}/{cid}", headers=hs["viewer"]), client.delete(f"{cbase(ws)}/{cid}", headers=hs["admin"]),
              client.post(f"{cbase(ws)}/{cid}/rotate", json={"secret": CANARY}, headers=hs["admin"])):         # rotate a revoked one
        seen.append(r.text)
    assert all(CANARY not in t for t in seen)
    assert CANARY not in caplog.text
    assert CANARY not in all_tables_text(db_session), "plaintext secret found in a table"


@pytest.mark.parametrize("path,body,status", [
    ("/auth/login", {"password": PASSWORD}, 422),                              # missing email
    ("/auth/login", {"email": "not-an-email", "password": PASSWORD}, 401),
    ("/auth/register", {"password": PASSWORD}, 422),
    ("/auth/register", {"email": "x@x.com", "password": PASSWORD[:4]}, 422),   # too short
])
def test_auth_errors_never_echo_passwords(client, path, body, status):
    r = client.post(path, json=body)
    assert r.status_code == status and PASSWORD not in r.text and PASSWORD[:4] + "\"" not in r.text
    if status == 422:
        assert all(set(e) <= {"loc", "msg", "type"} for e in r.json()["detail"])


@pytest.mark.parametrize("body", [
    {"provider": "aceden", "secret": CANARY},                                                  # missing name
    {"provider": "aceden", "name": "x", "secret": CANARY, "config": {"api_key": CANARY}},     # secret in config
    {"provider": "aceden", "name": "bad name!!", "secret": CANARY},
    {"provider": "aceden", "name": "x", "secret": CANARY, "nope": CANARY},
    {"provider": "aceden", "name": "x", "secret": CANARY * 400},                               # too long
])
def test_credential_validation_errors_never_echo_the_secret(client, rig, body):
    _, hs, ws, _, _ = rig
    r = client.post(cbase(ws), json=body, headers=hs["owner"])
    assert r.status_code == 422 and CANARY not in r.text


def test_unexpected_server_errors_are_generic(app, rig, monkeypatch):
    _, hs, ws, _, _ = rig
    from app.credentials_service import CredentialService

    def boom(self, workspace_id):
        raise RuntimeError(f"connection string with {CANARY}")
    monkeypatch.setattr(CredentialService, "list", boom)
    r = TestClient(app, raise_server_exceptions=False).get(cbase(ws), headers=hs["owner"])
    assert r.status_code == 500 and r.json() == {"detail": "Internal server error"} and CANARY not in r.text


def test_settings_repr_and_str_hide_the_root_secrets():
    root, old = "r" * 40 + "ROOT-CANARY", "p" * 40 + "OLD-CANARY"
    s = Settings(app_env="test", app_secret_key=root, app_secret_key_previous=old, _env_file=None)
    for shown in (repr(s), str(s), f"{s!r}", repr(get_settings())):
        assert "ROOT-CANARY" not in shown and "OLD-CANARY" not in shown and get_settings().app_secret_key not in shown
    assert s.app_secret_key == root                                                            # the value itself is untouched


def test_credential_rows_and_audit_payloads_hold_no_plaintext(client, rig, db_session):
    from sqlalchemy import select
    from app.models.credentials import Credential
    from app.models.kernel import SystemEvent
    _, hs, ws, _, _ = rig
    cid = make(client, hs["admin"], ws)
    client.post(f"{cbase(ws)}/{cid}/rotate", json={"secret": CANARY + "-2"}, headers=hs["admin"])
    row = db_session.get(Credential, cid)
    assert CANARY not in repr(row) and CANARY not in (row.secret_ciphertext or "") and row.secret_ciphertext.startswith("v1.")
    events = db_session.scalars(select(SystemEvent).where(SystemEvent.event_type.like("credential.%"))).all()
    assert len(events) == 2 and all(CANARY not in str(e.payload) and "ciphertext" not in str(e.payload) for e in events)
    client.delete(f"{cbase(ws)}/{cid}", headers=hs["admin"])
    db_session.expire_all()
    assert db_session.get(Credential, cid).secret_ciphertext is None                           # revoke wipes the stored secret


def test_a_backup_file_holds_ciphertext_never_plaintext_or_root_key(tmp_path):
    settings = Settings(app_env="test", _env_file=None)
    live = tmp_path / "live.db"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{live}")
    command.upgrade(cfg, "head")
    blob = CredentialCipher(settings).encrypt(CANARY, credential_aad("w1", "c1"))
    con = sqlite3.connect(live)
    con.execute("create table probe (v text)")
    con.execute("insert into probe values (?)", (blob,))
    con.commit()
    con.close()
    out = tmp_path / "b.db"
    bk.backup(str(live), str(out))
    data = out.read_bytes()
    assert blob.encode() in data and CANARY.encode() not in data and settings.app_secret_key.encode() not in data


def test_a_credential_blob_is_bound_to_its_own_workspace_and_row():
    from app.security.crypto import DecryptionError
    c = CredentialCipher(Settings(app_env="test", _env_file=None))
    blob = c.encrypt(CANARY, credential_aad("w1", "c1"))
    assert c.decrypt(blob, credential_aad("w1", "c1")) == CANARY
    for aad in (credential_aad("w2", "c1"), credential_aad("w1", "c2")):
        with pytest.raises(DecryptionError) as exc:
            c.decrypt(blob, aad)
        assert CANARY not in str(exc.value)


# ============================================================ Part 2: real foreign ids
@pytest.fixture
def victim(rig, db_session):
    """Workspace `ws` (the victim) holds real workflow, run, event, schedule, memory and document records."""
    client, hs, ws, other, _ = rig
    assert define(client, hs["admin"], ws, wf("nightly", triggers=[{"type": "manual"}, {"type": "schedule", "interval_seconds": 3600},
                                                                  {"type": "event", "event_type": "lead.created"}])).status_code == 200
    run = start(client, hs["member"], ws).json()
    ev = client.post(f"{wf_base(ws)}/workflow-events", json={"event_type": "lead.created", "event_ref": "lead-1"}, headers=hs["member"]).json()["event"]
    assert client.post(f"{wf_base(ws)}/workflow-schedules", json=sched_body(), headers=hs["admin"]).status_code == 200
    mem = client.post(mem_base(ws), json=item(content=f"{CANARY} refunds"), headers=hs["owner"]).json()
    assert upload(client, hs["owner"], ws, doc="handbook", text=DOC + " " + CANARY).status_code == 200
    return client, hs, ws, other, {"run": run["id"], "event": ev["id"], "memory": mem["id"], "doc": "handbook"}


def snapshot(db, ws_id):
    from sqlalchemy import select
    from app.models.memory import MemoryRecord
    from app.models.workflows import WorkflowEventRecord, WorkflowRecord, WorkflowRunRecord, WorkflowScheduleRecord
    db.expire_all()
    out = []
    for m in (WorkflowRecord, WorkflowRunRecord, WorkflowEventRecord, WorkflowScheduleRecord, MemoryRecord):
        out.append(sorted(str(vars_) for vars_ in db.execute(select(m.__table__).where(m.__table__.c.workspace_id == ws_id)).all()))
    return out


def test_foreign_ids_on_every_workflow_route_are_not_found_and_change_nothing(victim, db_session):
    client, hs, ws, other, ids = victim
    attacker, b = hs["outsider"], wf_base(other)               # an owner of ANOTHER workspace, using their own workspace id
    before = snapshot(db_session, ws["id"])
    calls = [("get", f"{b}/workflows/nightly"), ("get", f"{b}/workflows/nightly/versions"),
             ("post", f"{b}/workflows/nightly/versions/1/archive"), ("post", f"{b}/workflows/nightly/runs"),
             ("get", f"{b}/workflow-runs/{ids['run']}"), ("post", f"{b}/workflow-runs/{ids['run']}/drive"),
             ("post", f"{b}/workflow-runs/{ids['run']}/cancel"), ("get", f"{b}/workflow-events/{ids['event']}")]
    ghost = client.get(f"{b}/workflow-runs/00000000-0000-0000-0000-000000000000", headers=attacker)
    for verb, path in calls:
        r = getattr(client, verb)(path, headers=attacker, **({"json": {}} if verb == "post" else {}))
        assert r.status_code == 404, (verb, path, r.status_code, r.text)
        assert CANARY not in r.text and ids["run"] not in r.text.replace(path, "")
    assert (ghost.status_code, ghost.json()) == (404, client.get(f"{b}/workflow-runs/{ids['run']}", headers=attacker).json())   # no oracle
    for path in ("workflow-runs", "workflow-events", "workflow-schedules", "workflows"):
        assert client.get(f"{b}/{path}", headers=attacker).json() == []
    assert client.post(f"{b}/workflow-schedules/disarm", json=sched_body(), headers=attacker).status_code == 404
    assert client.post(f"{b}/workflow-events", json={"event_type": "lead.created", "event_ref": "lead-1"}, headers=attacker).json()["event"]["matched"] == 0
    assert client.post(f"{b}/workflow-tick", json={"drive": False}, headers=attacker).status_code == 200
    assert snapshot(db_session, ws["id"]) == before


def test_foreign_ids_on_every_memory_route_are_not_found_and_change_nothing(victim, db_session):
    client, hs, ws, other, ids = victim
    attacker, m = hs["outsider"], mem_base(other)
    before = snapshot(db_session, ws["id"])
    assert client.get(f"{m}/{ids['memory']}", headers=attacker).status_code == 404
    gone = client.delete(f"{m}/{ids['memory']}", headers=attacker)
    assert gone.status_code in (204, 404)
    assert client.delete(f"{m}/documents/{ids['doc']}", headers=attacker).json().get("removed", 0) == 0
    assert client.put(f"{m}/documents/{ids['doc']}", json={"title": "mine", "text": "attacker text " * 20}, headers=attacker).status_code == 200
    for r in (client.get(m, headers=attacker), client.get(f"{m}/documents", headers=attacker),
              client.post(f"{m}/search", json={"query": "refunds handbook business system status"}, headers=attacker)):
        assert CANARY not in r.text, r.url
    assert client.get(f"{m}/{ids['memory']}", headers=hs["owner"]).status_code == 404            # still scoped to the victim's workspace
    assert client.get(f"{mem_base(ws)}/{ids['memory']}", headers=hs["owner"]).status_code == 200
    assert CANARY in client.get(f"{mem_base(ws)}/{ids['memory']}", headers=hs["owner"]).text
    docs = {d["document_id"]: d for d in client.get(f"{mem_base(ws)}/documents", headers=hs["owner"]).json()}
    assert "handbook" in docs and docs["handbook"]["title"] == "Ops handbook"                       # the attacker's PUT made its own copy
    assert snapshot(db_session, ws["id"]) == before
