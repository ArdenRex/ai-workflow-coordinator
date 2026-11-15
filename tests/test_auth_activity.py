"""Step 14.8: password change (revokes all tokens) and account activity."""
import pytest
from sqlalchemy import func, select

from app.models.identity import AuthEvent
from tests.test_workspaces_api import PW, signup

NEW = "a-Brand-New-Passphrase-77"


def hdr(token):
    return {"Authorization": f"Bearer {token}"}


def login(client, email, password=PW):
    return client.post("/auth/login", json={"email": email, "password": password})


def types(client, h):
    return [e["event_type"] for e in client.get("/auth/activity", headers=h).json()]


def test_account_activity_is_recorded_and_private(client, db_session):
    a = signup(client, "a@x.com")
    login(client, "a@x.com", "wrong-password-1")
    client.post("/auth/logout", headers=a)
    a2 = hdr(login(client, "a@x.com").json()["access_token"])
    b = signup(client, "b@x.com")
    got = types(client, a2)
    assert sorted(got) == sorted(["register", "login", "login_failed", "logout", "login"]) and len(types(client, b)) == 2
    rows = client.get("/auth/activity?limit=2", headers=a2).json()
    assert len(rows) == 2 and set(rows[0]) == {"event_type", "ip", "created_at"}


def test_an_unknown_email_or_a_missing_token_stores_and_shows_nothing(client, db_session):
    signup(client, "a@x.com")
    n = db_session.scalar(select(func.count()).select_from(AuthEvent))
    assert login(client, "ghost@x.com", "whatever-pass-1").status_code == 401
    assert db_session.scalar(select(func.count()).select_from(AuthEvent)) == n
    assert client.get("/auth/activity").status_code == 401 and client.post("/auth/password", json={}).status_code == 401


def test_password_change_revokes_every_token_and_returns_a_fresh_one(client):
    first = signup(client, "a@x.com")
    other = hdr(login(client, "a@x.com").json()["access_token"])
    r = client.post("/auth/password", json={"current_password": PW, "new_password": NEW}, headers=first)
    assert r.status_code == 200 and PW not in r.text and NEW not in r.text
    fresh = hdr(r.json()["access_token"])
    assert client.get("/auth/me", headers=first).status_code == 401 and client.get("/auth/me", headers=other).status_code == 401
    assert client.get("/auth/me", headers=fresh).status_code == 200
    assert login(client, "a@x.com", PW).status_code == 401 and login(client, "a@x.com", NEW).status_code == 200
    assert "password_changed" in types(client, fresh)


def test_a_wrong_current_password_changes_nothing(client):
    h = signup(client, "a@x.com")
    r = client.post("/auth/password", json={"current_password": "not-the-password-1", "new_password": NEW}, headers=h)
    assert r.status_code == 403 and "not-the-password" not in r.text
    assert client.get("/auth/me", headers=h).status_code == 200 and login(client, "a@x.com", PW).status_code == 200
    assert "password_change_failed" in types(client, h)


@pytest.mark.parametrize("new,status", [(PW, 422), ("short", 422), ("", 422)])
def test_unacceptable_new_passwords_are_refused(client, new, status):
    h = signup(client, "a@x.com")
    r = client.post("/auth/password", json={"current_password": PW, "new_password": new}, headers=h)
    assert r.status_code == status and (new == "" or new not in r.text)
    assert login(client, "a@x.com", PW).status_code == 200


def test_unknown_fields_are_refused(client):
    h = signup(client, "a@x.com")
    assert client.post("/auth/password", json={"current_password": PW, "new_password": NEW, "x": 1}, headers=h).status_code == 422


def test_guessing_the_current_password_is_throttled_like_login(client):
    h = signup(client, "a@x.com")
    codes = [client.post("/auth/password", json={"current_password": f"guess-{i}-guess", "new_password": NEW}, headers=h).status_code for i in range(8)]
    assert set(codes) <= {403, 429} and 429 in codes
    assert client.post("/auth/password", json={"current_password": PW, "new_password": NEW}, headers=h).status_code == 429   # locked, even with the right one
    assert login(client, "a@x.com", PW).status_code in (200, 429)


def test_the_migration_is_reversible(tmp_path):
    import sqlite3
    from alembic import command
    from alembic.config import Config
    path = tmp_path / "m.db"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{path}")
    command.upgrade(cfg, "head")
    con = sqlite3.connect(path)
    assert con.execute("select count(*) from auth_events").fetchone()[0] == 0
    con.close()
    command.downgrade(cfg, "0019")
    command.upgrade(cfg, "head")
