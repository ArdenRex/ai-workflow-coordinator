import socket

import httpx
import pytest
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.connectors import netguard
from app.connectors import registry as creg
from app.connectors.registry import ConnectorSpec
from app.connectors.workspace import WorkspaceConnectors, register_workspace_tools
from app.identity.context import load_context
from app.kernel.registry import ToolRegistry
from app.kernel.service import ToolExecutionService
from app.models import ExecutionStatus
from app.models.identity import User
from sqlalchemy import select
from tests.test_aceden_connector import fake_aceden
from tests.test_workspaces_api import mkws, signup

SECRET = "key-A"


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    monkeypatch.setattr(netguard, "_getaddrinfo",
                        lambda host, port, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))])
    monkeypatch.setattr(get_settings(), "connection_test_cooldown_seconds", 0)


@pytest.fixture
def team(client):
    hs = {n: signup(client, f"{n}@x.com") for n in ("owner", "admin", "member", "outsider")}
    ws = mkws(client, hs["owner"])
    for n in ("admin", "member"):
        client.post(f"/workspaces/{ws['id']}/members", json={"email": f"{n}@x.com", "role": n}, headers=hs["owner"])
    return hs, ws


def add_cred(client, h, ws, key=SECRET, name="prod", url="https://aceden.test", **kw):
    r = client.post(f"/workspaces/{ws['id']}/credentials", headers=h,
                    json={"provider": "aceden", "name": name, "secret": key, "config": {"base_url": url}, **kw})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def mock_spec(monkeypatch, server_key=SECRET, log=None):
    """Make the aceden connector talk to an in-memory fake server."""
    real = creg._aceden
    monkeypatch.setitem(creg.SPECS, "aceden", ConnectorSpec(
        "aceden", lambda config, secret, settings, **kw: real(
            config, secret, settings, transport=fake_aceden(log, key=server_key), sleep=lambda s: None)))


@pytest.fixture
def rig(db_session, monkeypatch):
    class Rig:
        logs = []
    mock_spec(monkeypatch, log=Rig.logs)
    sf = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    wc = WorkspaceConnectors(sf, get_settings())
    reg = register_workspace_tools(ToolRegistry(), wc)
    Rig.svc, Rig.wc, Rig.db = ToolExecutionService(db_session, reg), wc, db_session
    yield Rig
    wc.close()


def principal(db, email, ws_id):
    return load_context(db, db.scalar(select(User).where(User.email == email)), ws_id).principal()


def run(rig, email, ws, tool="aceden.task.list", data=None):
    return rig.svc.submit(principal(rig.db, email, ws["id"]), tool, data or {})


# ---------------------------------------------------------- construction + kernel
def test_tool_runs_with_workspace_credential(client, team, rig):
    hs, ws = team
    add_cred(client, hs["owner"], ws)
    ex = run(rig, "owner@x.com", ws)
    assert ex.status == ExecutionStatus.SUCCEEDED and ex.output["tasks"][0]["id"] == 5
    assert rig.logs[-1][2] == SECRET


def test_two_workspaces_use_their_own_keys(client, team, rig, monkeypatch):
    hs, ws = team
    other = mkws(client, hs["outsider"], "Other")
    add_cred(client, hs["owner"], ws, key="key-A")
    add_cred(client, hs["outsider"], other, key="key-B", url="https://other.test")
    monkeypatch.setitem(creg.SPECS, "aceden", ConnectorSpec("aceden", lambda config, secret, settings, **kw: creg._aceden(
        config, secret, settings, transport=fake_aceden(rig.logs, key=secret), sleep=lambda s: None)))
    run(rig, "owner@x.com", ws)
    run(rig, "outsider@x.com", other)
    assert [l[2] for l in rig.logs[-2:]] == ["key-A", "key-B"]


def test_workspace_without_connection_fails_safely(client, team, rig):
    hs, ws = team
    other = mkws(client, hs["outsider"], "Other")
    add_cred(client, hs["outsider"], other)                       # only the OTHER workspace is connected
    ex = run(rig, "owner@x.com", ws)
    assert ex.status == ExecutionStatus.FAILED and "ConnectorConfigError" in ex.error
    assert SECRET not in (ex.error or "")


def test_connector_is_cached_and_rebuilt_after_rotation(client, team, rig):
    hs, ws = team
    cid = add_cred(client, hs["owner"], ws)
    c1, c2 = rig.wc.get(ws["id"], "aceden"), rig.wc.get(ws["id"], "aceden")
    assert c1 is c2
    client.post(f"/workspaces/{ws['id']}/credentials/{cid}/rotate", json={"secret": "key-A2-rotated"}, headers=hs["owner"])
    c3 = rig.wc.get(ws["id"], "aceden")
    assert c3 is not c1 and c3.config.auth_token.get_secret_value() == "key-A2-rotated"


def test_revoked_credential_stops_working_immediately(client, team, rig):
    hs, ws = team
    cid = add_cred(client, hs["owner"], ws)
    assert run(rig, "owner@x.com", ws).status == ExecutionStatus.SUCCEEDED
    client.delete(f"/workspaces/{ws['id']}/credentials/{cid}", headers=hs["owner"])
    assert run(rig, "owner@x.com", ws).status == ExecutionStatus.FAILED


def test_multiple_active_credentials_are_refused_not_guessed(client, team, rig):
    hs, ws = team
    add_cred(client, hs["owner"], ws, name="one")
    add_cred(client, hs["owner"], ws, name="two")
    assert run(rig, "owner@x.com", ws).status == ExecutionStatus.FAILED


def test_private_host_blocked_at_build_time(client, team, rig, monkeypatch):
    hs, ws = team
    add_cred(client, hs["owner"], ws)
    monkeypatch.setattr(netguard, "_getaddrinfo",             # DNS now points at the metadata service
                        lambda host, port, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 0))])
    assert run(rig, "owner@x.com", ws).status == ExecutionStatus.FAILED
    assert rig.logs == []                                     # no request ever left


# ---------------------------------------------------------- create-time validation
@pytest.mark.parametrize("config", [{}, {"base_url": "ftp://x.test"}, {"base_url": "https://u:p@x.test"},
                                    {"base_url": "https://127.0.0.1"}, {"base_url": "http://169.254.169.254"},
                                    {"base_url": "https://localhost"}, {"base_url": "https://x.test", "timeout_seconds": 999}])
def test_bad_config_rejected_at_creation(client, team, config):
    hs, ws = team
    r = client.post(f"/workspaces/{ws['id']}/credentials", headers=hs["owner"],
                    json={"provider": "aceden", "name": "p", "secret": SECRET, "config": config})
    assert r.status_code == 422 and SECRET not in r.text


def test_provider_without_connector_is_stored_but_cannot_be_tested(client, team):
    hs, ws = team
    r = client.post(f"/workspaces/{ws['id']}/credentials", headers=hs["owner"],
                    json={"provider": "mailchimp", "name": "crm", "secret": "tok-123456"})
    assert r.status_code == 201
    t = client.post(f"/workspaces/{ws['id']}/credentials/{r.json()['id']}/test", headers=hs["owner"])
    assert t.status_code == 400


# ---------------------------------------------------------- connection test endpoint
def test_connection_test_ok_records_status_and_audits(client, team, monkeypatch, db_session):
    hs, ws = team
    mock_spec(monkeypatch)
    cid = add_cred(client, hs["admin"], ws)
    r = client.post(f"/workspaces/{ws['id']}/credentials/{cid}/test", headers=hs["admin"])
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["provider"] == "aceden" and body["capabilities"] == ["task.list", "task.get"]
    got = client.get(f"/workspaces/{ws['id']}/credentials/{cid}", headers=hs["admin"]).json()
    assert got["last_test_ok"] is True and got["last_tested_at"] and got["last_test_message"] == "Connected"
    from app.models.kernel import SystemEvent
    ev = db_session.scalars(select(SystemEvent).where(SystemEvent.event_type == "connection.tested")).all()
    assert len(ev) == 1 and ev[0].payload["ok"] is True and SECRET not in str(ev[0].payload)
    assert SECRET not in r.text


def test_connection_test_failure_reports_code_not_details(client, team, monkeypatch):
    hs, ws = team
    mock_spec(monkeypatch, server_key="different-key")                 # remote rejects our key
    cid = add_cred(client, hs["owner"], ws)
    r = client.post(f"/workspaces/{ws['id']}/credentials/{cid}/test", headers=hs["owner"]).json()
    assert r["ok"] is False and r["message"] == "connector_auth_failed" and r["capabilities"] == []
    got = client.get(f"/workspaces/{ws['id']}/credentials/{cid}", headers=hs["owner"]).json()
    assert got["last_test_ok"] is False


def test_connection_test_blocked_host_is_a_failed_test_not_a_call(client, team, monkeypatch):
    hs, ws = team
    log = []
    mock_spec(monkeypatch, log=log)
    cid = add_cred(client, hs["owner"], ws)
    monkeypatch.setattr(netguard, "_getaddrinfo",
                        lambda host, port, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.1.2.3", 0))])
    r = client.post(f"/workspaces/{ws['id']}/credentials/{cid}/test", headers=hs["owner"]).json()
    assert r["ok"] is False and r["message"] == "connector_config_invalid" and log == []


def test_connection_test_permissions_and_isolation(client, team, monkeypatch):
    hs, ws = team
    mock_spec(monkeypatch)
    cid = add_cred(client, hs["owner"], ws)
    url = f"/workspaces/{ws['id']}/credentials/{cid}/test"
    assert client.post(url, headers=hs["member"]).status_code == 403
    assert client.post(url, headers=hs["outsider"]).status_code == 404
    assert client.post(url).status_code == 401
    other = mkws(client, hs["outsider"], "Other")
    assert client.post(f"/workspaces/{other['id']}/credentials/{cid}/test", headers=hs["outsider"]).status_code == 404


def test_connection_test_cooldown_and_revoked(client, team, monkeypatch):
    hs, ws = team
    mock_spec(monkeypatch)
    monkeypatch.setattr(get_settings(), "connection_test_cooldown_seconds", 60)
    cid = add_cred(client, hs["owner"], ws)
    url = f"/workspaces/{ws['id']}/credentials/{cid}/test"
    assert client.post(url, headers=hs["owner"]).status_code == 200
    assert client.post(url, headers=hs["owner"]).status_code == 429
    client.delete(f"/workspaces/{ws['id']}/credentials/{cid}", headers=hs["owner"])
    assert client.post(url, headers=hs["owner"]).status_code == 409
