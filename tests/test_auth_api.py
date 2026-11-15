from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.config import get_settings
from app.models.identity import User
from app.security.tokens import create_access_token

PW = "a-good-password-1"


def reg(client, email="Alice@Example.com", password=PW, **kw):
    return client.post("/auth/register", json={"email": email, "password": password, **kw})


def login(client, email="alice@example.com", password=PW):
    return client.post("/auth/login", json={"email": email, "password": password})


def test_register_returns_user_without_secrets(client, db_session):
    r = reg(client, full_name="  Alice  ")
    assert r.status_code == 201
    body = r.json()
    assert body["email"] == "alice@example.com" and body["full_name"] == "Alice" and body["is_active"]
    assert "password" not in str(body).lower()
    stored = db_session.scalar(select(User))
    assert stored.password_hash.startswith("scrypt$") and PW not in stored.password_hash


def test_register_duplicate_case_insensitive(client):
    assert reg(client).status_code == 201
    assert reg(client, email="ALICE@example.COM").status_code == 409


def test_register_validation(client):
    assert reg(client, email="not-an-email").status_code == 422
    assert reg(client, password="short").status_code == 422
    assert reg(client, password=" " * 12).status_code == 422
    assert client.post("/auth/register", json={"email": "a@b.co"}).status_code == 422


def test_login_success_and_me(client, db_session):
    reg(client)
    r = login(client, email="  ALICE@example.com ")
    assert r.status_code == 200
    data = r.json()
    assert data["token_type"] == "bearer" and data["expires_in"] > 0
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {data['access_token']}"})
    assert me.status_code == 200 and me.json()["email"] == "alice@example.com"
    assert db_session.scalar(select(User)).last_login_at is not None


def test_login_failures_are_indistinguishable(client):
    reg(client)
    wrong_pw, unknown = login(client, password="wrong-password-1"), login(client, email="nobody@example.com")
    assert wrong_pw.status_code == unknown.status_code == 401
    assert wrong_pw.json() == unknown.json()


def test_inactive_user_cannot_login_or_use_token(client, db_session):
    reg(client)
    token = login(client).json()["access_token"]
    user = db_session.scalar(select(User))
    user.is_active = False
    db_session.commit()
    assert login(client).status_code == 401
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_me_requires_valid_token(client, db_session):
    assert client.get("/auth/me").status_code == 401
    assert client.get("/auth/me", headers={"Authorization": "Bearer junk"}).status_code == 401
    assert client.get("/auth/me", headers={"Authorization": "Basic abc"}).status_code == 401
    r = client.get("/auth/me")
    assert r.headers["www-authenticate"] == "Bearer"


def test_expired_token_and_deleted_user_rejected(client, db_session):
    reg(client)
    user = db_session.scalar(select(User))
    old, _ = create_access_token(get_settings(), user.id, now=datetime.now(timezone.utc) - timedelta(days=2))
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {old}"}).status_code == 401
    ghost, _ = create_access_token(get_settings(), "no-such-user")
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {ghost}"}).status_code == 401


def test_legacy_hash_is_upgraded_on_login(client, db_session):
    reg(client)
    user = db_session.scalar(select(User))
    from app.security import passwords as pw
    import hashlib, base64, os
    salt = os.urandom(16)
    weak = hashlib.scrypt(PW.encode(), salt=salt, n=1024, r=8, p=1, dklen=32)
    user.password_hash = "scrypt$1024$8$1$%s$%s" % (base64.b64encode(salt).decode(), base64.b64encode(weak).decode())
    db_session.commit()
    assert login(client).status_code == 200
    db_session.refresh(user)
    assert not pw.needs_rehash(user.password_hash)


def test_errors_do_not_leak_password(client, caplog):
    reg(client)
    login(client, password="very-secret-wrong-pw")
    assert "very-secret-wrong-pw" not in caplog.text and PW not in caplog.text
