"""Step 5.2: OpenAI-compatible provider, workspace LLM credentials, per-workspace resolution."""
import json
import logging
import socket

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from app.config import Settings, get_settings
from app.connectors import netguard
from app.llm import credentials as llm_creds
from app.llm.errors import (LLMAuthError, LLMBadResponseError, LLMConfigError, LLMError, LLMInputError,
                            LLMRateLimitedError, LLMTimeoutError, LLMUnavailableError)
from app.llm.openai_compatible import OpenAICompatibleProvider
from app.llm.registry import build_provider
from app.llm.types import LLMRequest, Message, MessageRole
from tests.test_workspaces_api import mkws, signup

KEY = "sk-super-secret-platform-key"
URL = "https://llm.example.test/v1"


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    monkeypatch.setattr(netguard, "_getaddrinfo",
                        lambda host, port, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))])
    monkeypatch.setattr(get_settings(), "connection_test_cooldown_seconds", 0)


def ok_body(text="hello", usage=(11, 7), finish="stop"):
    return {"choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": finish}],
            "usage": {"prompt_tokens": usage[0], "completion_tokens": usage[1]}}


def server(handler_or_json, status=200, seen=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if callable(handler_or_json):
            return handler_or_json(request)
        return httpx.Response(status, json=handler_or_json)
    return httpx.MockTransport(handler)


def provider(transport, key=KEY, url=URL, model="m-1", **kw):
    return OpenAICompatibleProvider(url, SecretStr(key), model, transport=transport, **kw)


def req(text="hi", **kw):
    return LLMRequest(messages=[Message(role=MessageRole.SYSTEM, content="be brief"),
                                Message(role=MessageRole.USER, content=text)], **kw)


# ------------------------------------------------------------------ request/response shape
def test_request_shape_and_auth_header():
    seen = []
    p = provider(server(ok_body(), seen=seen))
    r = p.complete(req(max_output_tokens=50, json_mode=True), timeout=5)
    sent = seen[0]
    body = json.loads(sent.content)
    assert sent.method == "POST" and sent.url.path == "/v1/chat/completions"
    assert sent.headers["authorization"] == f"Bearer {KEY}"
    assert body == {"model": "m-1", "temperature": 0.0, "max_tokens": 50,
                    "response_format": {"type": "json_object"},
                    "messages": [{"role": "system", "content": "be brief"}, {"role": "user", "content": "hi"}]}
    assert KEY not in sent.content.decode()
    assert (r.text, r.provider, r.model, r.finish_reason) == ("hello", "openai_compatible", "m-1", "stop")
    assert (r.usage.input_tokens, r.usage.output_tokens) == (11, 7)


def test_optional_fields_omitted_and_finish_reason_mapping():
    seen = []
    p = provider(server(ok_body(finish="content_filter"), seen=seen))
    r = p.complete(req(), timeout=5)
    body = json.loads(seen[0].content)
    assert "max_tokens" not in body and "response_format" not in body
    assert r.finish_reason == "other"
    assert provider(server(ok_body(finish="length"))).complete(req(), timeout=5).finish_reason == "length"


def test_missing_or_garbage_usage_becomes_zero():
    body = ok_body()
    body["usage"] = {"prompt_tokens": "x", "completion_tokens": -4}
    assert provider(server(body)).complete(req(), timeout=5).usage.total_tokens == 0
    del body["usage"]
    assert provider(server(body)).complete(req(), timeout=5).usage.total_tokens == 0


# ------------------------------------------------------------------ error mapping
@pytest.mark.parametrize("status,exc", [(401, LLMAuthError), (403, LLMAuthError), (429, LLMRateLimitedError),
                                        (500, LLMUnavailableError), (503, LLMUnavailableError),
                                        (408, LLMUnavailableError), (400, LLMInputError), (422, LLMInputError),
                                        (302, LLMBadResponseError), (204, LLMBadResponseError)])
def test_status_codes_map_to_generic_errors(status, exc):
    p = provider(server({"error": {"message": f"leaked {KEY} prompt-text"}}, status=status))
    with pytest.raises(exc) as ei:
        p.complete(req("prompt-text"), timeout=5)
    assert KEY not in str(ei.value) and "prompt-text" not in str(ei.value)


def test_retryable_flags_match_the_service_retry_rules():
    assert LLMRateLimitedError.retryable and LLMTimeoutError.retryable and LLMUnavailableError.retryable
    assert not LLMAuthError.retryable and not LLMInputError.retryable and not LLMBadResponseError.retryable


def test_timeout_and_transport_failures():
    def timeout(request):
        raise httpx.ReadTimeout("slow", request=request)

    def down(request):
        raise httpx.ConnectError("refused", request=request)
    with pytest.raises(LLMTimeoutError):
        provider(server(timeout)).complete(req(), timeout=1)
    with pytest.raises(LLMUnavailableError):
        provider(server(down)).complete(req(), timeout=1)


@pytest.mark.parametrize("payload", [b"not json", b"{}", b'{"choices": []}', b'{"choices": [{}]}',
                                     b'{"choices": [{"message": {"content": null}}]}',
                                     b'{"choices": [{"message": {"content": 5}}]}', b'[1,2]'])
def test_unusable_200_bodies_are_bad_response(payload):
    p = provider(server(lambda r: httpx.Response(200, content=payload)))
    with pytest.raises(LLMBadResponseError):
        p.complete(req(), timeout=5)


def test_oversized_response_is_refused():
    p = provider(server(lambda r: httpx.Response(200, content=b"x" * 200)), max_response_bytes=100)
    with pytest.raises(LLMBadResponseError):
        p.complete(req(), timeout=5)
    declared = provider(server(lambda r: httpx.Response(200, headers={"content-length": "999999"}, content=b"{}")),
                        max_response_bytes=100)
    with pytest.raises(LLMBadResponseError):
        declared.complete(req(), timeout=5)


def test_redirects_are_never_followed():
    seen = []

    def redirect(request):
        seen.append(str(request.url))
        return httpx.Response(307, headers={"location": "https://evil.example/steal"})
    with pytest.raises(LLMBadResponseError):
        provider(server(redirect)).complete(req(), timeout=5)
    assert seen == [URL + "/chat/completions"]


# ------------------------------------------------------------------ safety
def test_key_never_appears_in_repr_errors_or_logs(caplog):
    caplog.set_level(logging.DEBUG)
    p = provider(server({}, status=401))
    assert KEY not in repr(p) and KEY not in str(p.__dict__.get("_client", ""))
    with pytest.raises(LLMAuthError):
        p.complete(req(), timeout=5)
    assert KEY not in caplog.text


@pytest.mark.parametrize("url", ["http://127.0.0.1/v1", "https://169.254.169.254/v1", "https://localhost/v1",
                                 "https://u:p@llm.example.test/v1", "https://llm.example.test/v1?x=1", "ftp://x.test"])
def test_bad_or_private_endpoints_refused(url):
    with pytest.raises(LLMConfigError):
        provider(None, url=url)


def test_dns_resolving_to_private_address_is_refused(monkeypatch):
    monkeypatch.setattr(netguard, "_getaddrinfo",
                        lambda host, port, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 0))])
    with pytest.raises(LLMConfigError):
        provider(None)


def test_https_required_in_production_and_private_allowed_for_dev():
    with pytest.raises(LLMConfigError):
        provider(None, url="http://llm.example.test/v1", require_https=True)
    assert provider(None, url="http://127.0.0.1:8000/v1", allow_private_host=True)


@pytest.mark.parametrize("key,model", [("  ", "m"), ("k", ""), ("k", "has space"), ("k", "x" * 101)])
def test_blank_key_and_bad_model_refused(key, model):
    with pytest.raises(LLMConfigError):
        provider(None, key=key, model=model)


# ------------------------------------------------------------------ settings + registry
def test_openai_compatible_requires_url_and_key():
    with pytest.raises(ValidationError):
        Settings(llm_provider="openai_compatible", _env_file=None)
    with pytest.raises(ValidationError):
        Settings(llm_provider="openai_compatible", llm_base_url=URL, llm_api_key="  ", _env_file=None)
    s = Settings(llm_provider="openai_compatible", llm_base_url=URL, llm_api_key=KEY, _env_file=None)
    assert KEY not in repr(s)


def test_production_requires_https_llm_url():
    base = dict(app_env="production", app_secret_key="x" * 40, database_url="postgresql://u:p@h/d",
                llm_provider="openai_compatible", llm_api_key=KEY, _env_file=None)
    with pytest.raises(ValidationError):
        Settings(llm_base_url="http://llm.example.test/v1", **base)
    assert Settings(llm_base_url=URL, **base).is_production


def test_registry_builds_platform_provider_from_settings():
    s = Settings(llm_provider="openai_compatible", llm_base_url=URL, llm_api_key=KEY, llm_model="gpt-x", _env_file=None)
    p = build_provider(s, transport=server(ok_body("hey")))
    assert p.model == "gpt-x" and p.complete(req(), timeout=5).text == "hey"


# ------------------------------------------------------------------ workspace credentials via API
def mk_llm_cred(client, h, ws, key, name="llm-main", url=URL, model="gpt-ws", **extra):
    return client.post(f"/workspaces/{ws['id']}/credentials", headers=h, json={
        "provider": "llm", "name": name, "secret": key, "config": {"base_url": url, "model": model, **extra}})


@pytest.fixture
def two(client):
    ha, hb = signup(client, "a@x.com"), signup(client, "b@x.com")
    return ha, mkws(client, ha, "A"), hb, mkws(client, hb, "B")


def test_llm_credential_create_validation(client, two):
    ha, a, _, _ = two
    assert mk_llm_cred(client, ha, a, "sk-aaaaaaaa").status_code == 201
    bad = [dict(name="n1", url="http://127.0.0.1/v1"), dict(name="n2", url="https://localhost/v1"),
           dict(name="n3", model=""), dict(name="n4", timeout_seconds=9999), dict(name="n5", extra_key=1)]
    for kw in bad:
        r = mk_llm_cred(client, ha, a, "sk-bbbbbbbb", **kw)
        assert r.status_code == 422, kw
        assert "sk-bbbbbbbb" not in r.text
    r = client.post(f"/workspaces/{a['id']}/credentials", headers=ha,
                    json={"provider": "llm", "name": "n6", "secret": "sk-cccccccc", "config": {"model": "m"}})
    assert r.status_code == 422


def test_workspace_without_credential_uses_platform_provider(client, db_session, two):
    _, a, _, _ = two
    s = Settings(_env_file=None)                                  # fake platform provider
    assert llm_creds.resolve_provider(db_session, s, a["id"]).name == "fake"


def test_each_workspace_uses_only_its_own_key(client, db_session, two):
    ha, a, hb, b = two
    mk_llm_cred(client, ha, a, "sk-key-of-A", url="https://a.llm.test/v1", model="model-a")
    mk_llm_cred(client, hb, b, "sk-key-of-B", url="https://b.llm.test/v1", model="model-b")
    seen = []
    s = get_settings()
    for ws in (a, b):
        with llm_creds.workspace_llm(db_session, s, ws["id"], transport=server(ok_body(), seen=seen)) as svc:
            svc.complete(workspace_id=ws["id"], actor=None, purpose="t", request=req())
    assert [(r.url.host, r.headers["authorization"], json.loads(r.content)["model"]) for r in seen] == [
        ("a.llm.test", "Bearer sk-key-of-A", "model-a"), ("b.llm.test", "Bearer sk-key-of-B", "model-b")]


def test_revoked_credential_falls_back_and_rotation_takes_effect(client, db_session, two):
    ha, a, _, _ = two
    cid = mk_llm_cred(client, ha, a, "sk-old-key-A").json()["id"]
    s, seen = get_settings(), []
    client.post(f"/workspaces/{a['id']}/credentials/{cid}/rotate", json={"secret": "sk-new-key-A"}, headers=ha)
    with llm_creds.workspace_llm(db_session, s, a["id"], transport=server(ok_body(), seen=seen)) as svc:
        svc.complete(workspace_id=a["id"], actor=None, purpose="t", request=req())
    assert seen[0].headers["authorization"] == "Bearer sk-new-key-A"
    client.delete(f"/workspaces/{a['id']}/credentials/{cid}", headers=ha)
    assert llm_creds.resolve_provider(db_session, s, a["id"]).name == "fake"


def test_multiple_active_llm_credentials_are_refused(client, db_session, two):
    ha, a, _, _ = two
    mk_llm_cred(client, ha, a, "sk-one-aaaa", name="one")
    mk_llm_cred(client, ha, a, "sk-two-aaaa", name="two")
    with pytest.raises(LLMConfigError):
        llm_creds.resolve_provider(db_session, get_settings(), a["id"])


def test_tampered_ciphertext_cannot_be_used(client, db_session, two):
    from app.models.credentials import Credential
    ha, a, hb, b = two
    mk_llm_cred(client, ha, a, "sk-key-of-A")
    cb = mk_llm_cred(client, hb, b, "sk-key-of-B").json()["id"]
    row_a = db_session.query(Credential).filter_by(workspace_id=a["id"]).one()
    db_session.get(Credential, cb).secret_ciphertext = row_a.secret_ciphertext
    db_session.commit()
    with pytest.raises(Exception):
        llm_creds.resolve_provider(db_session, get_settings(), b["id"])


def test_connection_test_endpoint_for_llm_credential(client, db_session, two, monkeypatch):
    ha, a, hb, b = two
    cid = mk_llm_cred(client, ha, a, "sk-key-of-A").json()["id"]
    real = llm_creds._build
    monkeypatch.setattr(llm_creds, "_build", lambda c, sec, st, **kw: real(c, sec, st, transport=server(ok_body("OK")), **kw))
    r = client.post(f"/workspaces/{a['id']}/credentials/{cid}/test", headers=ha)
    assert r.status_code == 200 and r.json()["ok"] is True
    assert client.get(f"/workspaces/{a['id']}/credentials/{cid}", headers=ha).json()["last_test_ok"] is True
    assert client.post(f"/workspaces/{b['id']}/credentials/{cid}/test", headers=hb).status_code == 404
    monkeypatch.setattr(llm_creds, "_build", lambda c, sec, st, **kw: real(c, sec, st, transport=server({}, status=401), **kw))
    bad = client.post(f"/workspaces/{a['id']}/credentials/{cid}/test", headers=ha).json()
    assert bad["ok"] is False and bad["message"] == "llm_auth_failed"


def test_service_over_real_provider_audits_without_content(client, db_session, two):
    from sqlalchemy import select
    from app.models import SystemEvent
    ha, a, _, _ = two
    mk_llm_cred(client, ha, a, "sk-key-of-A")
    with llm_creds.workspace_llm(db_session, get_settings(), a["id"],
                                 transport=server(ok_body("SECRET-COMPLETION"))) as svc:
        svc.complete(workspace_id=a["id"], actor=None, purpose="t", request=req("SECRET-PROMPT"))
    ev = db_session.scalars(select(SystemEvent).where(SystemEvent.event_type == "llm.completed")).one()
    assert ev.payload["provider"] == "openai_compatible" and ev.payload["usage"] == {"input": 11, "output": 7}
    blob = json.dumps(ev.payload)
    assert "SECRET" not in blob and "sk-key-of-A" not in blob
