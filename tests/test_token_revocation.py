"""Step 14.7: logout invalidates every token issued so far (users.token_version)."""
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from sqlalchemy import select

from app.config import get_settings
from app.models.identity import User
from app.security.tokens import InvalidTokenError, create_access_token, decode_access_claims, derive_key
from tests.test_workspaces_api import PW, signup


def login(client, email, password=PW):
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_logout_invalidates_every_earlier_token_but_not_a_new_login(client):
    first = signup(client, "a@x.com")
    second = login(client, "a@x.com")                                  # a second device
    assert client.get("/auth/me", headers=first).status_code == 200 and client.get("/auth/me", headers=second).status_code == 200
    assert client.post("/auth/logout", headers=first).status_code == 204
    for h in (first, second):
        assert client.get("/auth/me", headers=h).status_code == 401
    assert client.post("/auth/logout", headers=first).status_code == 401           # a dead token cannot even log out again
    fresh = login(client, "a@x.com")
    assert client.get("/auth/me", headers=fresh).status_code == 200


def test_logout_only_affects_that_user(client):
    a, b = signup(client, "a@x.com"), signup(client, "b@x.com")
    client.post("/auth/logout", headers=a)
    assert client.get("/auth/me", headers=a).status_code == 401 and client.get("/auth/me", headers=b).status_code == 200


def test_logout_requires_a_token(client):
    assert client.post("/auth/logout").status_code == 401


def test_a_revoked_token_loses_workspace_access_too(client):
    from tests.test_workspaces_api import mkws
    h = signup(client, "a@x.com")
    ws = mkws(client, h)
    assert client.get(f"/workspaces/{ws['id']}/credentials", headers=h).status_code == 200
    client.post("/auth/logout", headers=h)
    assert client.get(f"/workspaces/{ws['id']}/credentials", headers=h).status_code == 401


def test_the_version_claim_is_checked_and_old_tokens_without_it_count_as_version_zero(client, db_session):
    s = get_settings()
    h = signup(client, "a@x.com")
    uid = db_session.scalar(select(User.id))
    legacy = jwt.encode({"sub": uid, "typ": "access", "iss": s.jwt_issuer, "iat": int(datetime.now(timezone.utc).timestamp()),
                         "exp": int((datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp())}, derive_key(s, "jwt"), algorithm="HS256")
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {legacy}"}).status_code == 200
    client.post("/auth/logout", headers=h)
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {legacy}"}).status_code == 401
    future, _ = create_access_token(s, uid, version=99)                             # a version the user never had
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {future}"}).status_code == 401


@pytest.mark.parametrize("tv", [True, -1, "1", 1.5, None])
def test_a_malformed_version_claim_is_rejected(tv):
    s = get_settings()
    now = int(datetime.now(timezone.utc).timestamp())
    tok = jwt.encode({"sub": "u", "typ": "access", "iss": s.jwt_issuer, "iat": now, "exp": now + 60, "tv": tv}, derive_key(s, "jwt"), algorithm="HS256")
    with pytest.raises(InvalidTokenError):
        decode_access_claims(s, tok)


def test_concurrent_logouts_each_count(client, db_session):
    h = signup(client, "a@x.com")
    uid = db_session.scalar(select(User.id))
    fresh = login(client, "a@x.com")
    client.post("/auth/logout", headers=h)
    assert db_session.get(User, uid).token_version == 1
    client.post("/auth/logout", headers=login(client, "a@x.com"))
    db_session.expire_all()
    assert db_session.get(User, uid).token_version == 2 and client.get("/auth/me", headers=fresh).status_code == 401


def test_the_migration_adds_the_column_with_a_safe_default_and_is_reversible(tmp_path):
    import sqlite3
    from alembic import command
    from alembic.config import Config
    path = tmp_path / "m.db"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{path}")
    command.upgrade(cfg, "0018")
    con = sqlite3.connect(path)
    con.execute("insert into users (id, email, is_active, created_at, updated_at) values ('u1', 'a@x.com', 1, '2026-01-01', '2026-01-01')")
    con.commit()
    con.close()
    command.upgrade(cfg, "head")
    con = sqlite3.connect(path)
    assert con.execute("select token_version from users where id='u1'").fetchone()[0] == 0           # existing users keep their tokens valid
    con.close()
    command.downgrade(cfg, "0018")
    command.upgrade(cfg, "head")
