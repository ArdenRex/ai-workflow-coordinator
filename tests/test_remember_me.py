"""Step F1: optional long-lived sign-in ("remember me")."""
import pytest
from pydantic import ValidationError

from app.config import Settings
from tests.test_auth_api import PW


def login(client, email, **extra):
    return client.post("/auth/login", json={"email": email, "password": PW, **extra})


@pytest.fixture
def user(client):
    email = "rem@example.com"
    assert client.post("/auth/register", json={"email": email, "password": PW}).status_code == 201
    return email


def test_default_login_keeps_the_short_lifetime(client, user):
    assert login(client, user).json()["expires_in"] == 60 * 60


def test_remember_me_gives_the_configured_long_lifetime_and_it_works(client, user):
    r = login(client, user, remember_me=True).json()
    assert r["expires_in"] == 30 * 86400
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {r['access_token']}"}).status_code == 200


def test_remember_me_must_be_a_boolean(client, user):
    assert login(client, user, remember_me="maybe").status_code == 422


def test_logout_still_revokes_a_remembered_token(client, user):
    h = {"Authorization": f"Bearer {login(client, user, remember_me=True).json()['access_token']}"}
    assert client.post("/auth/logout", headers=h).status_code == 204
    assert client.get("/auth/me", headers=h).status_code == 401


def test_a_password_change_can_keep_the_session_remembered(client, user):
    h = {"Authorization": f"Bearer {login(client, user, remember_me=True).json()['access_token']}"}
    new = "Another-Strong-Pass-77!"
    r = client.post("/auth/password", headers=h, json={"current_password": PW, "new_password": new, "remember_me": True})
    assert r.status_code == 200 and r.json()["expires_in"] == 30 * 86400
    short = client.post("/auth/password", headers={"Authorization": f"Bearer {r.json()['access_token']}"},
                        json={"current_password": new, "new_password": PW})
    assert short.json()["expires_in"] == 60 * 60
    assert client.get("/auth/me", headers=h).status_code == 401           # the old token is dead either way


@pytest.mark.parametrize("days", [0, 91, -1])
def test_the_lifetime_setting_is_bounded(days):
    with pytest.raises(ValidationError):
        Settings(app_env="test", remember_me_ttl_days=days, _env_file=None)
