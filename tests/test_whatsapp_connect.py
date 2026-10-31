"""
"Connect WhatsApp" endpoint tests. Meta's Graph API is replaced by a fake
transport (httpx.MockTransport) that records every call, so these check what we
SEND to Meta and what we SAVE — not Meta itself. Needs a migrated Postgres
(skipped otherwise), like the pipeline tests in test_whatsapp.py.
"""
import json
import re
import types
import uuid

import httpx
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app import whatsapp_connect as wc
from app.database import get_db
from app.auth import get_current_user
from app.routers import whatsapp_router as wr

WABA = "100200300400"
PN1, PN2 = "555000111", "555000222"
TOKEN = "EAAB-SECRET-TOKEN-xyz"


class FakeGraph:
    """Minimal fake of the Graph API endpoints we use. `fail` = set of step names to break."""

    def __init__(self, numbers=None, info=None, fail=()):
        self.numbers = numbers if numbers is not None else [{"id": PN1, "display_phone_number": "+92 300 1112222"}]
        self.info = info or {}
        self.fail = set(fail)
        self.calls = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        parts = request.url.path.strip("/").split("/")[1:]          # drop version
        body = json.loads(request.content) if request.content else None
        self.calls.append({"method": request.method, "parts": parts, "params": dict(request.url.params),
                           "auth": request.headers.get("authorization"), "body": body})

        def err(): return httpx.Response(400, json={"error": {"message": "nope", "code": 100}})
        def ok(d): return httpx.Response(200, json=d)

        if parts == ["oauth", "access_token"]:
            return err() if "token" in self.fail else ok({"access_token": TOKEN, "token_type": "bearer"})
        if len(parts) == 2 and parts[1] == "phone_numbers":
            return err() if "numbers" in self.fail else ok({"data": self.numbers})
        if len(parts) == 2 and parts[1] == "subscribed_apps":
            return err() if "subscribe" in self.fail else ok({"success": True})
        if len(parts) == 2 and parts[1] == "register":
            return err() if "register" in self.fail else ok({"success": True})
        if len(parts) == 1:
            return err() if "info" in self.fail else ok(self.info.get(parts[0], {}))
        return httpx.Response(404, json={"error": {"message": "unexpected"}})

    def steps(self):
        return [(c["method"], "/".join(c["parts"][1:]) or c["parts"][0]) for c in self.calls]


@pytest.fixture
def env(monkeypatch):
    try:
        from sqlalchemy import text
        from app.database import SessionLocal
        s = SessionLocal()
        s.execute(text("select whatsapp_connected, whatsapp_access_token from users limit 1"))
        s.close()
    except Exception as exc:
        pytest.skip(f"migrated Postgres not available: {exc}")

    from app.database import SessionLocal
    from app.models import User, Workspace

    s = SessionLocal()
    tag = uuid.uuid4().hex[:8]
    ws = Workspace(name=f"ws-{tag}"); s.add(ws); s.commit(); s.refresh(ws)
    me = User(email=f"me-{tag}@example.com", name="Me", workspace_id=ws.id)
    other = User(email=f"other-{tag}@example.com", name="Other", workspace_id=ws.id)
    lonely = User(email=f"lonely-{tag}@example.com", name="No Workspace")
    s.add_all([me, other, lonely]); s.commit()
    for u in (me, other, lonely):
        s.refresh(u)

    # unique phone ids per test run so parallel/leftover rows can't collide
    num = str(uuid.uuid4().int)[:9]            # Meta ids are purely numeric
    pn1, pn2 = f"{PN1}{num}", f"{PN2}{num}"
    state = types.SimpleNamespace(me=me.id, other=other.id, lonely=lonely.id, current=me.id, pn1=pn1, pn2=pn2)

    app = FastAPI(); app.include_router(wr.router)

    def _current(db=Depends(get_db)):
        from app.models import User as U
        return db.get(U, state.current)

    app.dependency_overrides[get_current_user] = _current
    client = TestClient(app)

    def install(graph: FakeGraph):
        monkeypatch.setattr(wc, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(graph.handler)))
        return graph

    def row(uid):
        s2 = SessionLocal()
        try:
            return s2.get(User, uid)
        finally:
            s2.close()

    state.client, state.install, state.row, state.PN1, state.PN2 = client, install, row, pn1, pn2
    yield state

    s.expire_all()
    for uid in (me.id, other.id, lonely.id):
        u = s.get(User, uid)
        if u:
            u.whatsapp_phone_number_id = None
    s.commit()
    for uid in (me.id, other.id, lonely.id):
        s.delete(s.get(User, uid))
    s.commit(); s.delete(s.get(Workspace, ws.id)); s.commit(); s.close()


def connect(env, **over):
    body = {"code": "AUTHCODE", "waba_id": WABA, "phone_number_id": env.pn1}
    body.update(over)
    return env.client.post("/auth/whatsapp/connect", json={k: v for k, v in body.items() if v is not None})


def graph_for(env, **kw):
    kw.setdefault("numbers", [{"id": env.pn1, "display_phone_number": "+92 300 1112222"}])
    return env.install(FakeGraph(**kw))


# ── config / status ──────────────────────────────────────────────────────────
def test_config_and_status(env):
    cfg = env.client.get("/auth/whatsapp/config").json()
    assert cfg["enabled"] is True and cfg["app_id"] == "1234567890" and cfg["config_id"] == "9876543210"
    assert "secret" not in json.dumps(cfg).lower()
    assert env.client.get("/auth/whatsapp/status").json() == {"enabled": True, "connected": False, "display_number": None}


def test_config_hides_ids_when_not_enabled(env, monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "whatsapp_config_id", "")
    cfg = env.client.get("/auth/whatsapp/config").json()
    assert cfg["enabled"] is False and cfg["app_id"] is None and cfg["config_id"] is None


# ── happy paths ──────────────────────────────────────────────────────────────
def test_connect_new_number_registers_subscribes_and_saves(env):
    g = graph_for(env, info={env.pn1: {"display_phone_number": "+92 300 1112222", "platform_type": "NOT_APPLICABLE"}})
    r = connect(env)
    assert r.status_code == 200, r.text
    assert r.json() == {"connected": True, "display_number": "+92 300 1112222", "coexistence": False}
    steps = g.steps()
    assert ("GET", "access_token") in steps
    assert ("POST", "register") in steps and ("POST", "subscribed_apps") in steps
    reg = next(c for c in g.calls if c["parts"][-1] == "register")
    assert reg["body"] == {"messaging_product": "whatsapp", "pin": "123456"} and reg["auth"] == f"Bearer {TOKEN}"
    exch = next(c for c in g.calls if c["parts"] == ["oauth", "access_token"])
    assert exch["params"]["code"] == "AUTHCODE" and exch["params"]["client_secret"] == "meta-app-secret"
    u = env.row(env.me)
    assert (u.whatsapp_connected, u.whatsapp_phone_number_id, u.whatsapp_waba_id, u.whatsapp_access_token) == \
           (True, env.pn1, WABA, TOKEN)
    assert env.client.get("/auth/whatsapp/status").json()["display_number"] == "+92 300 1112222"
    assert TOKEN not in r.text and TOKEN not in json.dumps(env.client.get("/auth/whatsapp/status").json())


def test_coexistence_number_is_not_registered(env):
    g = graph_for(env, info={env.pn1: {"is_on_biz_app": True, "platform_type": "CLOUD_API",
                                       "display_phone_number": "+92 300 1112222"}})
    r = connect(env)
    assert r.status_code == 200 and r.json()["coexistence"] is True
    assert ("POST", "register") not in g.steps() and ("POST", "subscribed_apps") in g.steps()


def test_coexistence_without_phone_id_picks_the_business_app_number(env):
    g = graph_for(env, numbers=[{"id": env.pn2, "display_phone_number": "+1 111"},
                                {"id": env.pn1, "display_phone_number": "+92 300 1112222"}],
                  info={env.pn2: {"is_on_biz_app": False, "platform_type": "CLOUD_API"},
                        env.pn1: {"is_on_biz_app": True, "platform_type": "CLOUD_API",
                                  "display_phone_number": "+92 300 1112222"}})
    r = connect(env, phone_number_id=None)
    assert r.status_code == 200
    assert env.row(env.me).whatsapp_phone_number_id == env.pn1


def test_single_number_without_phone_id_is_used(env):
    graph_for(env, info={env.pn1: {"platform_type": "CLOUD_API"}})
    assert connect(env, phone_number_id=None).status_code == 200
    assert env.row(env.me).whatsapp_phone_number_id == env.pn1


def test_reconnecting_same_number_is_allowed(env):
    graph_for(env, info={env.pn1: {"platform_type": "CLOUD_API"}})
    assert connect(env).status_code == 200
    assert connect(env).status_code == 200


# ── refusals ─────────────────────────────────────────────────────────────────
def test_number_not_in_waba_is_forbidden(env):
    graph_for(env, numbers=[{"id": env.pn2}])
    r = connect(env)                         # claims pn1 but WABA only has pn2
    assert r.status_code == 403 and env.row(env.me).whatsapp_connected is False


def test_number_owned_by_another_user_is_409_and_nothing_changes(env):
    g = graph_for(env, info={env.pn1: {"platform_type": "CLOUD_API"}})
    env.current = env.other
    assert connect(env).status_code == 200
    env.current = env.me
    g.calls.clear()
    r = connect(env)
    assert r.status_code == 409 and env.row(env.me).whatsapp_connected is False
    assert ("POST", "subscribed_apps") not in g.steps()           # refused before touching Meta state
    assert env.row(env.other).whatsapp_phone_number_id == env.pn1


def test_new_number_without_pin_is_refused(env, monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "whatsapp_registration_pin", "")
    g = graph_for(env, info={env.pn1: {"platform_type": "NOT_APPLICABLE"}})
    r = connect(env)
    assert r.status_code == 503 and "WHATSAPP_REGISTRATION_PIN" in r.json()["detail"]
    assert ("POST", "subscribed_apps") not in g.steps() and env.row(env.me).whatsapp_connected is False


@pytest.mark.parametrize("fail", ["token", "numbers", "subscribe"])
def test_meta_failures_save_nothing_and_leak_nothing(env, fail):
    graph_for(env, fail={fail}, info={env.pn1: {"platform_type": "CLOUD_API"}})
    r = connect(env)
    assert r.status_code == 502
    assert TOKEN not in r.text and "nope" not in r.text           # Meta's raw error stays in the logs
    u = env.row(env.me)
    assert u.whatsapp_connected is False and u.whatsapp_access_token is None


def test_register_failure_saves_nothing(env):
    g = graph_for(env, fail={"register"}, info={env.pn1: {"platform_type": "NOT_APPLICABLE"}})
    assert connect(env).status_code == 502
    assert ("POST", "subscribed_apps") not in g.steps() and env.row(env.me).whatsapp_connected is False


@pytest.mark.parametrize("over", [{"waba_id": "../etc"}, {"waba_id": "abc"}, {"waba_id": "12"},
                                  {"phone_number_id": "1/2"}, {"phone_number_id": "x" * 10}, {"code": "  "}])
def test_bad_input_is_rejected_before_calling_meta(env, over):
    g = graph_for(env)
    assert connect(env, **over).status_code == 400 and g.calls == []


def test_user_without_workspace_is_refused(env):
    g = graph_for(env)
    env.current = env.lonely
    assert connect(env).status_code == 400 and g.calls == []


def test_disabled_server_refuses(env, monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "whatsapp_app_id", "")
    g = graph_for(env)
    assert connect(env).status_code == 503 and g.calls == []


# ── disconnect ───────────────────────────────────────────────────────────────
def test_disconnect_unsubscribes_and_clears_everything(env):
    g = graph_for(env, info={env.pn1: {"platform_type": "CLOUD_API"}})
    assert connect(env).status_code == 200
    g.calls.clear()
    assert env.client.post("/auth/whatsapp/disconnect").json() == {"status": "disconnected"}
    assert g.steps() == [("DELETE", "subscribed_apps")] and g.calls[0]["auth"] == f"Bearer {TOKEN}"
    u = env.row(env.me)
    assert (u.whatsapp_connected, u.whatsapp_phone_number_id, u.whatsapp_waba_id,
            u.whatsapp_display_number, u.whatsapp_access_token) == (False, None, None, None, None)


def test_disconnect_clears_locally_even_if_meta_fails_and_frees_the_number(env):
    graph_for(env, info={env.pn1: {"platform_type": "CLOUD_API"}})
    connect(env)
    graph_for(env, fail={"subscribe"})                              # DELETE subscribed_apps now fails
    assert env.client.post("/auth/whatsapp/disconnect").status_code == 200
    assert env.row(env.me).whatsapp_connected is False
    env.current = env.other                                         # number can now be claimed by someone else
    graph_for(env, info={env.pn1: {"platform_type": "CLOUD_API"}})
    assert connect(env).status_code == 200


def test_disconnect_when_never_connected_is_a_noop(env):
    g = graph_for(env)
    assert env.client.post("/auth/whatsapp/disconnect").status_code == 200 and g.calls == []
