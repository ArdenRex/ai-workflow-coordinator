"""
Server-side trial/payment enforcement, tested through the REAL application
(app.main.app) with real login tokens — not a stand-in router. Needs a migrated
Postgres (skipped otherwise).

Rules under test: after the 7-day trial, a logged-in user gets 402 on the API
unless they paid ("active"), were exempted in the admin panel ("exempt"), are a
freelancer, or are an admin. Blocked users can still log in, see billing status
and pay.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.billing_access import is_billing_blocked, is_open_for_blocked_users

NOW = datetime.now(timezone.utc)
PAST = NOW - timedelta(days=1)
FUTURE = NOW + timedelta(days=3)


class U:  # minimal stand-in for the pure-rule tests
    def __init__(self, status, ends=None, email="someone@example.com"):
        self.subscription_status, self.trial_ends_at, self.email = status, ends, email


# ── pure rules ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize("user,blocked", [
    (U("trialing", FUTURE), False),
    (U("trialing", PAST), True),
    (U("trialing", NOW - timedelta(seconds=1)), True),
    (U("trialing", FUTURE.replace(tzinfo=None)), False),          # naive datetimes from the DB
    (U("trialing", PAST.replace(tzinfo=None)), True),
    (U("trialing", None), True),                                  # (the gate starts the clock first)
    (U("active"), False), (U("exempt"), False), (U("freelancer"), False),
    (U("exempt", PAST), False), (U("active", PAST), False),       # trial date irrelevant once paid/exempt
    (U("cancelled"), True), (U("past_due"), True),
    (U("cancelled", FUTURE), True),
    (U("weird-new-status"), True), (U(None), True), (U(""), True),
    (U("trialing", PAST, email="boss@example.com"), False),       # admin email never blocked
    (U("cancelled", None, email="BOSS@Example.com"), False),      # ...case-insensitively
])
def test_rules(user, blocked):
    assert is_billing_blocked(user) is blocked


@pytest.mark.parametrize("path,open_", [
    ("/auth/me", True), ("/auth/billing-status", True), ("/auth/logout", True), ("/auth/refresh", True),
    ("/auth/login", True), ("/billing/checkout", True), ("/billing/portal", True), ("/billing/cancel", True),
    ("/auth/gmail/status", False), ("/auth/gmail/connect", False), ("/auth/whatsapp/status", False),
    ("/auth/whatsapp/connect", False),
    ("/tasks/", False), ("/tasks/team", False), ("/admin/users", False), ("/teams/x", False),
    ("/integrations/x", False), ("/workspace/settings", False), ("/authx", False), ("/billingx", False),
])
def test_open_paths(path, open_):
    assert is_open_for_blocked_users(path) is open_


# ── through the real app ─────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def client():
    try:
        from sqlalchemy import text
        from app.database import SessionLocal
        s = SessionLocal(); s.execute(text("select 1 from users limit 1")); s.close()
    except Exception as exc:
        pytest.skip(f"migrated Postgres not available: {exc}")
    import app.main as m
    if getattr(m, "_startup_error", None):
        pytest.skip(f"app did not start: {m._startup_error}")
    return TestClient(m.app)


@pytest.fixture
def make_user():
    from app.auth import create_access_token
    from app.database import SessionLocal
    from app.models import User, UserRole, Workspace

    s = SessionLocal()
    created = []

    def make(status, ends=None, email=None, active=True):
        tag = uuid.uuid4().hex[:8]
        ws = Workspace(name=f"ws-{tag}"); s.add(ws); s.commit(); s.refresh(ws)
        u = User(email=email or f"u-{tag}@example.com", name="T", workspace_id=ws.id, role=UserRole.architect,
                 subscription_status=status, trial_ends_at=ends, is_active=active)
        s.add(u); s.commit(); s.refresh(u)
        created.append((u.id, ws.id))
        return u.id, {"Authorization": f"Bearer {create_access_token(u.id)[0]}"}

    def fresh(uid):
        s.expire_all()
        from app.models import User as U_
        return s.get(U_, uid)

    make.fresh = fresh
    yield make

    from app.models import Task
    s.expire_all()
    for uid, wid in created:
        s.query(Task).filter(Task.workspace_id == wid).delete()
        u = s.get(User, uid)
        if u:
            s.delete(u)
        s.commit()
        w = s.get(Workspace, wid)
        if w:
            s.delete(w)
        s.commit()
    s.close()


ALLOWED = [("trialing", FUTURE), ("active", None), ("exempt", None), ("freelancer", None)]
BLOCKED = [("trialing", PAST), ("cancelled", None), ("past_due", None), ("mystery", None)]


@pytest.mark.parametrize("status,ends", ALLOWED)
def test_allowed_users_reach_the_api(client, make_user, status, ends):
    _, h = make_user(status, ends)
    assert client.get("/tasks/", headers=h).status_code == 200


@pytest.mark.parametrize("status,ends", BLOCKED)
def test_blocked_users_get_402_on_the_api(client, make_user, status, ends):
    _, h = make_user(status, ends)
    for path in ("/tasks/", "/tasks/team", "/tasks/graph", "/auth/gmail/status", "/auth/whatsapp/status"):
        r = client.get(path, headers=h)
        assert r.status_code == 402, (path, r.status_code, r.text)
        assert "trial has ended" in r.json()["detail"]
    # writes too (a nonexistent id would be 404 for an allowed user — the gate answers first)
    assert client.delete("/tasks/999999999", headers=h).status_code == 402
    assert client.patch("/tasks/999999999/status", headers=h, json={"status": "completed"}).status_code == 402


@pytest.mark.parametrize("status,ends", BLOCKED)
def test_blocked_users_can_still_log_in_and_see_the_billing_screen(client, make_user, status, ends):
    _, h = make_user(status, ends)
    me = client.get("/auth/me", headers=h)
    assert me.status_code == 200
    bs = client.get("/auth/billing-status", headers=h)
    assert bs.status_code == 200 and bs.json()["show_wall"] is True      # never "no wall" while the API blocks
    assert client.post("/auth/logout", headers=h).status_code != 402


def test_expired_trial_is_flagged_for_the_wall(client, make_user):
    _, h = make_user("trialing", PAST)
    assert client.get("/auth/billing-status", headers=h).json()["trial_expired"] is True


def test_admin_email_is_never_blocked_even_with_expired_trial(client, make_user):
    _, h = make_user("trialing", PAST, email="boss@example.com")
    assert client.get("/tasks/", headers=h).status_code == 200


def test_unauthenticated_and_invalid_tokens_behave_as_before(client):
    assert client.get("/tasks/").status_code == 401
    assert client.get("/tasks/", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_webhooks_without_a_login_are_untouched(client):
    r = client.get("/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "verify-me",
                                                 "hub.challenge": "42"})
    assert r.status_code == 200 and r.text == "42"


def test_deactivated_user_still_gets_403_not_402(client, make_user):
    _, h = make_user("trialing", PAST, active=False)
    assert client.get("/tasks/", headers=h).status_code == 403


def test_user_with_no_trial_date_gets_a_fresh_trial_not_a_lockout(client, make_user):
    uid, h = make_user("trialing", None)
    assert client.get("/tasks/", headers=h).status_code == 200
    u = make_user.fresh(uid)
    assert u.trial_ends_at is not None
    ends = u.trial_ends_at if u.trial_ends_at.tzinfo else u.trial_ends_at.replace(tzinfo=timezone.utc)
    assert timedelta(days=6) < ends - datetime.now(timezone.utc) <= timedelta(days=7, minutes=1)


def test_trial_that_expires_mid_session_starts_blocking_immediately(client, make_user):
    from app.database import SessionLocal
    from app.models import User
    uid, h = make_user("trialing", FUTURE)
    assert client.get("/tasks/", headers=h).status_code == 200
    s = SessionLocal(); s.get(User, uid).trial_ends_at = NOW - timedelta(minutes=1); s.commit(); s.close()
    assert client.get("/tasks/", headers=h).status_code == 402


# ── the two ways back in ─────────────────────────────────────────────────────
def test_paying_restores_access(client, make_user):
    """In this test environment Polar isn't configured, so checkout simulates a successful payment."""
    _, h = make_user("trialing", PAST)
    assert client.get("/tasks/", headers=h).status_code == 402
    pay = client.post("/billing/checkout", headers=h)
    assert pay.status_code == 200, pay.text
    assert client.get("/tasks/", headers=h).status_code == 200


def test_admin_panel_exemption_restores_access_and_removal_blocks_again(client, make_user):
    uid, h = make_user("trialing", PAST)
    _, admin_h = make_user("exempt", None, email="boss@example.com")
    assert client.get("/tasks/", headers=h).status_code == 402

    r = client.patch(f"/admin/users/{uid}", headers=admin_h, json={"subscription_status": "exempt"})
    assert r.status_code == 200, r.text
    assert client.get("/tasks/", headers=h).status_code == 200            # let in without paying

    client.patch(f"/admin/users/{uid}", headers=admin_h, json={"subscription_status": "trialing"})
    assert client.get("/tasks/", headers=h).status_code == 402            # trial date is still in the past


def test_admin_extending_the_trial_restores_access(client, make_user):
    uid, h = make_user("trialing", PAST)
    _, admin_h = make_user("exempt", None, email="boss@example.com")
    nxt = (NOW + timedelta(days=5)).isoformat()
    assert client.patch(f"/admin/users/{uid}", headers=admin_h, json={"trial_ends_at": nxt}).status_code == 200
    assert client.get("/tasks/", headers=h).status_code == 200


def test_non_admin_cannot_exempt_themselves(client, make_user):
    uid, h = make_user("trialing", PAST)
    r = client.patch(f"/admin/users/{uid}", headers=h, json={"subscription_status": "exempt"})
    assert r.status_code in (402, 403)                                    # gate or admin guard — either way, no
    assert make_user.fresh(uid).subscription_status == "trialing"


def test_allowed_users_are_not_blocked_on_write_routes_either(client, make_user):
    _, h = make_user("active", None)
    assert client.delete("/tasks/999999999", headers=h).status_code == 404       # reached the route, not the gate
    assert client.patch("/tasks/999999999/status", headers=h, json={"status": "completed"}).status_code in (404, 422)
