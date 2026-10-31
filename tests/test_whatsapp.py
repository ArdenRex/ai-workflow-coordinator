"""
WhatsApp webhook + task filter tests.

Pure tests need nothing. The pipeline tests need a migrated Postgres at
DATABASE_URL (run `alembic upgrade head` first) and are skipped otherwise.
The AI is always faked — these tests never call Groq.
"""
import asyncio
import hashlib
import hmac
import json
import types
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import whatsapp_bot as bot
from app.routers import whatsapp_router as wr

SECRET = "meta-app-secret"


# ── helpers ──────────────────────────────────────────────────────────────────
def payload(*texts, phone_id="PNID1", field="messages", mids=None):
    key = "messages" if field == "messages" else "message_echoes"
    msgs = [
        {"from": "923001112222", "id": (mids[i] if mids else f"wamid.{uuid.uuid4().hex}"),
         "type": "text", "text": {"body": t}}
        for i, t in enumerate(texts)
    ]
    value = {"messaging_product": "whatsapp", "metadata": {"phone_number_id": phone_id}, key: msgs}
    if field == "messages":
        value["contacts"] = [{"wa_id": "923001112222", "profile": {"name": "Hamza"}}]
    return {"object": "whatsapp_business_account", "entry": [{"changes": [{"field": field, "value": value}]}]}


def sign(raw: bytes, secret=SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


def run(coro):
    return asyncio.run(coro)


# ── prefilter ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("text", ["", "   ", "👍", "ok", "Thanks!", "thank you", "Hi", "Assalamualaikum",
                                  "ok sir", "got it", "12345", "lol", "😂😂"])
def test_prefilter_drops_chatter(text):
    assert bot.prefilter(text)[0] is False


@pytest.mark.parametrize("text", ["Ali fix the login bug", "send me the invoice by Friday",
                                  "Can you review the contract?", "how are you doing today",
                                  "علی کل تک رپورٹ بھیج دو"])
def test_prefilter_lets_real_text_through(text):
    assert bot.prefilter(text)[0] is True


# ── payload parsing ──────────────────────────────────────────────────────────
def test_parse_inbound_text_with_sender_name():
    out = list(bot.iter_text_messages(payload("Ali please send the file")))
    assert len(out) == 1 and out[0]["direction"] == "inbound"
    assert out[0]["sender_name"] == "Hamza" and out[0]["phone_number_id"] == "PNID1"


def test_parse_echo_is_outbound():
    out = list(bot.iter_text_messages(payload("Sara prepare the quote", field="smb_message_echoes")))
    assert len(out) == 1 and out[0]["direction"] == "outbound"


def test_parse_skips_non_text_status_and_garbage():
    p = payload("hello there friend")
    p["entry"][0]["changes"][0]["value"]["messages"].append({"id": "x", "type": "image", "image": {}})
    p["entry"][0]["changes"].append({"field": "messages", "value": {"metadata": {"phone_number_id": "P"},
                                                                    "statuses": [{"id": "s", "status": "read"}]}})
    p["entry"].append({"changes": [{"field": "messages", "value": {}}]})
    assert len(list(bot.iter_text_messages(p))) == 1
    assert list(bot.iter_text_messages({})) == []
    assert list(bot.iter_text_messages({"entry": [{"changes": None}]})) == []


# ── signature + router ───────────────────────────────────────────────────────
def test_verify_signature():
    raw = b'{"a":1}'
    assert wr.verify_signature(raw, sign(raw), SECRET)
    assert not wr.verify_signature(raw, sign(raw, "wrong"), SECRET)
    assert not wr.verify_signature(raw, None, SECRET)
    assert not wr.verify_signature(raw, "sha256=", SECRET)
    assert not wr.verify_signature(raw, "md5=abc", SECRET)
    assert not wr.verify_signature(raw, sign(raw), "")          # no secret configured


@pytest.fixture
def client(monkeypatch):
    seen = []

    async def fake_handle(p):
        seen.append(p)

    monkeypatch.setattr(wr, "handle_webhook_payload", fake_handle)
    app = FastAPI()
    app.include_router(wr.router)
    c = TestClient(app)
    c.seen = seen
    return c


def test_get_verification_ok_and_failures(client):
    ok = client.get("/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "verify-me",
                                                  "hub.challenge": "12345"})
    assert ok.status_code == 200 and ok.text == "12345"
    bad = client.get("/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "nope",
                                                   "hub.challenge": "1"})
    assert bad.status_code == 403
    assert client.get("/webhooks/whatsapp").status_code == 403
    assert client.get("/webhooks/whatsapp", params={"hub.mode": "unsubscribe", "hub.verify_token": "verify-me",
                                                    "hub.challenge": "1"}).status_code == 403


def test_post_requires_valid_signature(client):
    raw = json.dumps(payload("Ali fix the bug today")).encode()
    assert client.post("/webhooks/whatsapp", content=raw).status_code == 401
    assert client.post("/webhooks/whatsapp", content=raw,
                       headers={"X-Hub-Signature-256": sign(raw, "wrong")}).status_code == 401
    assert client.seen == []

    r = client.post("/webhooks/whatsapp", content=raw, headers={"X-Hub-Signature-256": sign(raw)})
    assert r.status_code == 200 and r.json() == {"status": "received"}
    assert len(client.seen) == 1


def test_post_bad_json_with_valid_signature_is_400(client):
    raw = b"not json"
    r = client.post("/webhooks/whatsapp", content=raw, headers={"X-Hub-Signature-256": sign(raw)})
    assert r.status_code == 400 and client.seen == []


def test_disabled_when_not_configured(client, monkeypatch):
    from app.config import get_settings
    s = get_settings()
    monkeypatch.setattr(s, "whatsapp_verify_token", "")
    assert client.get("/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "",
                                                    "hub.challenge": "1"}).status_code == 404
    from pydantic import SecretStr
    monkeypatch.setattr(s, "whatsapp_app_secret", SecretStr(""))
    raw = b"{}"
    assert client.post("/webhooks/whatsapp", content=raw,
                       headers={"X-Hub-Signature-256": sign(raw, "")}).status_code == 404


# ── pipeline against a real database ─────────────────────────────────────────
@pytest.fixture
def db_env():
    try:
        from sqlalchemy import text
        from app.database import SessionLocal
        s = SessionLocal()
        s.execute(text("select 1 from users limit 1"))
        s.execute(text("select whatsapp_message_id, 1 from tasks limit 1"))
        s.close()
    except Exception as exc:
        pytest.skip(f"migrated Postgres not available: {exc}")

    from app.database import SessionLocal
    from app.models import Task, User, Workspace

    s = SessionLocal()
    tag = uuid.uuid4().hex[:8]
    ws = Workspace(name=f"ws-{tag}")
    s.add(ws); s.commit(); s.refresh(ws)
    user = User(email=f"wa-{tag}@example.com", name="Owner", workspace_id=ws.id,
                whatsapp_connected=True, whatsapp_phone_number_id=f"PN-{tag}")
    s.add(user); s.commit(); s.refresh(user)
    env = types.SimpleNamespace(phone_id=user.whatsapp_phone_number_id, user_id=user.id, ws_id=ws.id,
                                factory=SessionLocal)
    yield env

    s.query(Task).filter(Task.workspace_id == ws.id).delete()
    s.delete(user); s.commit()
    s.delete(ws); s.commit()
    s.close()


def fake_extract(assignee=None, confidence=0.9):
    async def _e(text):
        return types.SimpleNamespace(task=f"TASK: {text}", assignee=assignee, deadline="Friday",
                                     priority=None, confidence=confidence)
    return _e


def task_gate(text_has):
    """Fake AI gate: a task iff the text contains the marker word."""
    async def _c(text):
        return text_has in text
    return _c


def tasks_of(env):
    from app.models import Task
    s = env.factory()
    try:
        return s.query(Task).filter(Task.workspace_id == env.ws_id).all()
    finally:
        s.close()


async def no_sleep(_delay):
    pass


def process(env, p, **kw):
    kw.setdefault("sleep", no_sleep)
    kw.setdefault("classify", task_gate("send"))
    kw.setdefault("extract", fake_extract(assignee="Ali"))
    return run(bot.handle_webhook_payload(p, session_factory=env.factory, **kw))


def test_only_task_messages_reach_the_board(db_env):
    p = payload("Ali please send the invoice by Friday",     # task
                "ok thanks",                                   # prefilter
                "how was your weekend with the family",        # AI says not a task
                "👍",                                          # prefilter
                phone_id=db_env.phone_id)
    stats = process(db_env, p)
    assert stats["messages"] == 4 and stats["created"] == 1
    assert stats["skipped_prefilter"] == 2 and stats["skipped_not_task"] == 1
    [t] = tasks_of(db_env)
    assert t.assignee == "Ali" and t.owner_id == db_env.user_id and t.status.value == "to_do"
    assert t.whatsapp_message_id and t.source_message.startswith("Ali please send")


def test_prefiltered_messages_never_call_the_ai(db_env):
    calls = []

    async def spy(text):
        calls.append(text); return True

    process(db_env, payload("ok", "thanks", "👍", "hi", phone_id=db_env.phone_id), classify=spy)
    assert calls == [] and tasks_of(db_env) == []


def test_redelivery_does_not_duplicate(db_env):
    p = payload("Ali send the report now", phone_id=db_env.phone_id, mids=["wamid.dup1" + uuid.uuid4().hex])
    assert process(db_env, p)["created"] == 1
    bot._SEEN.clear()                      # simulate a restart: DB check must still catch it
    assert process(db_env, p)["skipped_duplicate"] == 1
    assert process(db_env, p)["skipped_duplicate"] == 1   # and the in-memory cache path
    assert len(tasks_of(db_env)) == 1


def test_unknown_number_and_disconnected_user_are_ignored(db_env):
    assert process(db_env, payload("Ali send it", phone_id="SOMEONE-ELSE"))["skipped_no_user"] == 1
    s = db_env.factory()
    from app.models import User
    u = s.get(User, db_env.user_id); u.whatsapp_connected = False; s.commit(); s.close()
    assert process(db_env, payload("Ali send it", phone_id=db_env.phone_id))["skipped_no_user"] == 1
    assert tasks_of(db_env) == []


def test_ai_failure_fails_closed_and_retry_works(db_env):
    mid = "wamid.fail" + uuid.uuid4().hex
    p = payload("Ali send the report", phone_id=db_env.phone_id, mids=[mid])

    async def boom(text):
        raise RuntimeError("groq down")

    s1 = process(db_env, p, classify=boom)
    assert s1["errors"] == 1 and s1["created"] == 0 and tasks_of(db_env) == []
    assert process(db_env, p)["created"] == 1          # Meta re-delivers → now succeeds


def test_one_bad_message_does_not_drop_the_rest(db_env):
    async def flaky_extract(text):
        if "bad" in text:
            raise RuntimeError("extract failed")
        return await fake_extract()(text)

    p = payload("send the bad one", "send the good one", phone_id=db_env.phone_id)
    stats = process(db_env, p, classify=task_gate("send"), extract=flaky_extract)
    assert stats["errors"] == 1 and stats["created"] == 1


def test_low_confidence_is_dropped(db_env):
    stats = process(db_env, payload("send the thing", phone_id=db_env.phone_id),
                    extract=fake_extract(confidence=0.3))
    assert stats["skipped_low_confidence"] == 1 and tasks_of(db_env) == []


def test_owner_echo_messages_can_create_tasks(db_env):
    p = payload("Sara send the quote today", field="smb_message_echoes", phone_id=db_env.phone_id)
    assert process(db_env, p, extract=fake_extract(assignee="Sara"))["created"] == 1
    assert tasks_of(db_env)[0].assignee == "Sara"


# ── AI gate response parsing (Groq is faked) ─────────────────────────────────
def _fake_groq(reply):
    class _Completions:
        async def create(self, **kw):
            assert kw["temperature"] == 0
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=reply))])
    return types.SimpleNamespace(chat=types.SimpleNamespace(completions=_Completions()))


@pytest.mark.parametrize("reply,expected", [
    ('{"is_task": true}', True),
    ('{"is_task": false}', False),
    ('```json\n{"is_task": true}\n```', True),
    ('Sure! {"is_task": false} hope that helps', False),
    ('{"is_task": "true"}', False),       # only a real boolean true counts
    ('{}', False),
])
def test_classify_parses_model_output(monkeypatch, reply, expected):
    import app.ai_extractor as ax
    monkeypatch.setattr(ax, "_get_client", lambda: _fake_groq(reply))
    assert run(bot.classify_task_intent("Ali send the report")) is expected


@pytest.mark.parametrize("reply", ["", "yes", "not json at all", "{broken"])
def test_classify_raises_on_unparseable_output(monkeypatch, reply):
    import app.ai_extractor as ax
    monkeypatch.setattr(ax, "_get_client", lambda: _fake_groq(reply))
    with pytest.raises(Exception):
        run(bot.classify_task_intent("Ali send the report"))


# ── retrying transient AI failures ───────────────────────────────────────────
def _retry_run(db_env, classify=None, extract=None, text="Ali send the report now"):
    sleeps = []

    async def fake_sleep(d):
        sleeps.append(d)

    stats = run(bot.handle_webhook_payload(
        payload(text, phone_id=db_env.phone_id), session_factory=db_env.factory,
        classify=classify or task_gate("send"), extract=extract or fake_extract(assignee="Ali"), sleep=fake_sleep))
    return stats, sleeps


def test_a_failing_gate_call_is_retried_and_then_succeeds(db_env):
    n = {"calls": 0}

    async def flaky(text):
        n["calls"] += 1
        if n["calls"] < 3:
            raise RuntimeError("429 rate limited")
        return True

    stats, sleeps = _retry_run(db_env, classify=flaky)
    assert stats["created"] == 1 and stats["retries"] == 2 and stats["errors"] == 0
    assert sleeps == [2.0, 8.0] and n["calls"] == 3 and len(tasks_of(db_env)) == 1


def test_a_failing_extractor_call_is_retried_too(db_env):
    n = {"calls": 0}

    async def flaky_extract(text):
        n["calls"] += 1
        if n["calls"] == 1:
            raise TimeoutError("slow")
        return await fake_extract(assignee="Ali")(text)

    stats, sleeps = _retry_run(db_env, extract=flaky_extract)
    assert stats["created"] == 1 and stats["retries"] == 1 and sleeps == [2.0]


def test_gives_up_after_three_attempts_and_a_later_redelivery_can_still_work(db_env):
    n = {"calls": 0}

    async def always_down(text):
        n["calls"] += 1
        raise RuntimeError("groq down")

    mid = "wamid.retry" + uuid.uuid4().hex
    p = payload("Ali send the report", phone_id=db_env.phone_id, mids=[mid])

    async def fake_sleep(d):
        pass

    s1 = run(bot.handle_webhook_payload(p, session_factory=db_env.factory, classify=always_down,
                                        extract=fake_extract(), sleep=fake_sleep))
    assert n["calls"] == 3 and s1["errors"] == 1 and s1["created"] == 0 and tasks_of(db_env) == []
    s2 = run(bot.handle_webhook_payload(p, session_factory=db_env.factory, classify=task_gate("send"),
                                        extract=fake_extract(), sleep=fake_sleep))
    assert s2["created"] == 1


def test_a_clean_no_is_not_retried_and_nothing_sleeps(db_env):
    n = {"calls": 0}

    async def says_no(text):
        n["calls"] += 1
        return False

    stats, sleeps = _retry_run(db_env, classify=says_no, text="how was the weekend with everyone")
    assert n["calls"] == 1 and sleeps == [] and stats["retries"] == 0 and stats["skipped_not_task"] == 1
