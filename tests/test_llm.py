"""Step 5.1: LLM abstraction, fake provider, limits, retries, content-free audit."""
import logging

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.config import Settings
from app.llm.errors import (LLMAuthError, LLMBadResponseError, LLMConfigError, LLMError,
                            LLMInputTooLargeError, LLMRateLimitedError, LLMTimeoutError)
from app.llm.fake import FakeProvider
from app.llm.registry import build_provider
from app.llm.service import MAX_MESSAGES, LLMService
from app.llm.types import LLMRequest, Message, MessageRole
from app.models import SystemEvent

pytestmark = pytest.mark.usefixtures("seed_workspaces")

SECRET_PROMPT = "my-confidential-prompt-text-12345"
SECRET_REPLY = "my-confidential-completion-67890"


def req(text="hello", **kw):
    return LLMRequest(messages=[Message(role=MessageRole.USER, content=text)], **kw)


def svc(db, provider=None, **overrides):
    settings = Settings(app_env="test", database_url="sqlite:///:memory:", _env_file=None, **overrides)
    sleeps = []
    s = LLMService(db, provider or FakeProvider(), settings, sleep=sleeps.append)
    s.sleeps = sleeps
    return s


def go(s, request=None, ws="w1"):
    return s.complete(workspace_id=ws, actor="u1", purpose="test_purpose", request=request or req())


def events(db, ws="w1"):
    return list(db.scalars(select(SystemEvent).where(SystemEvent.workspace_id == ws).order_by(SystemEvent.created_at)))


# ------------------------------------------------------------------ types
def test_blank_message_and_empty_request_rejected():
    with pytest.raises(ValidationError):
        Message(role=MessageRole.USER, content="   ")
    with pytest.raises(ValidationError):
        LLMRequest(messages=[])


def test_request_is_deterministic_by_default_and_validates_ranges():
    assert req().temperature == 0.0
    with pytest.raises(ValidationError):
        req(temperature=5)
    with pytest.raises(ValidationError):
        req(max_output_tokens=0)
    with pytest.raises(ValidationError):
        LLMRequest(messages=[Message(role=MessageRole.USER, content="x")], surprise=1)


# ------------------------------------------------------------------ fake provider
def test_fake_echoes_and_reports_usage(db_session):
    r = go(svc(db_session), req("ping"))
    assert r.text == "[FAKE] ping" and r.provider == "fake" and r.usage.total_tokens > 0


def test_fake_script_text_callable_and_error(db_session):
    fp = FakeProvider(["one", lambda rq: "two:" + rq.messages[-1].content, LLMAuthError("no")])
    s = svc(db_session, fp)
    assert go(s).text == "one" and go(s, req("x")).text == "two:x"
    with pytest.raises(LLMAuthError):
        go(s)


def test_fake_without_user_message_is_bad_response(db_session):
    only_system = LLMRequest(messages=[Message(role=MessageRole.SYSTEM, content="rules")])
    with pytest.raises(LLMBadResponseError):
        go(svc(db_session), only_system)


# ------------------------------------------------------------------ registry + config
def test_registry_builds_fake_and_rejects_unknown():
    assert build_provider(Settings(_env_file=None)).name == "fake"
    with pytest.raises(LLMConfigError):
        build_provider(Settings(llm_provider="nope", _env_file=None))


def test_production_rejects_fake_provider():
    base = dict(app_env="production", app_secret_key="x" * 40, database_url="postgresql://u:p@h/d", _env_file=None)
    with pytest.raises(ValidationError):
        Settings(**base)
    assert Settings(llm_provider="openai", **base).llm_provider == "openai"


@pytest.mark.parametrize("field,value", [("llm_timeout_seconds", 0), ("llm_timeout_seconds", 999),
                                         ("llm_max_retries", -1), ("llm_max_retries", 9),
                                         ("llm_max_input_chars", 0), ("llm_max_output_tokens", 0)])
def test_llm_settings_bounds(field, value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})


# ------------------------------------------------------------------ limits
def test_input_over_size_limit_is_refused_before_provider(db_session):
    fp = FakeProvider()
    s = svc(db_session, fp, llm_max_input_chars=100)
    with pytest.raises(LLMInputTooLargeError):
        go(s, req("x" * 101))
    assert fp.requests == []


def test_too_many_messages_refused(db_session):
    fp = FakeProvider()
    many = LLMRequest(messages=[Message(role=MessageRole.USER, content="a")] * (MAX_MESSAGES + 1))
    with pytest.raises(LLMInputTooLargeError):
        go(svc(db_session, fp), many)
    assert fp.requests == []


def test_output_tokens_are_always_capped(db_session):
    fp = FakeProvider()
    s = svc(db_session, fp, llm_max_output_tokens=100)
    go(s, req(max_output_tokens=99999))
    go(s, req())
    go(s, req(max_output_tokens=10))
    assert [r.max_output_tokens for r in fp.requests] == [100, 100, 10]


# ------------------------------------------------------------------ retries
def test_transient_errors_are_retried_with_backoff(db_session):
    fp = FakeProvider([LLMRateLimitedError("x"), LLMTimeoutError("x"), "ok"])
    s = svc(db_session, fp, llm_max_retries=2)
    assert go(s).text == "ok"
    assert s.sleeps == [0.5, 1.0]
    assert events(db_session)[-1].payload["attempts"] == 3


def test_retries_are_bounded(db_session):
    fp = FakeProvider([LLMTimeoutError("x")] * 5)
    s = svc(db_session, fp, llm_max_retries=1)
    with pytest.raises(LLMTimeoutError):
        go(s)
    assert len(fp.requests) == 2
    ev = events(db_session)[-1]
    assert ev.event_type == "llm.failed" and ev.payload["code"] == "llm_timeout"


def test_non_retryable_errors_are_not_retried(db_session):
    fp = FakeProvider([LLMAuthError("x"), "never reached"])
    s = svc(db_session, fp)
    with pytest.raises(LLMAuthError):
        go(s)
    assert len(fp.requests) == 1 and s.sleeps == []


def test_unexpected_provider_exception_is_wrapped_generically(db_session):
    def boom(rq):
        raise RuntimeError(SECRET_PROMPT)
    with pytest.raises(LLMError) as ei:
        go(svc(db_session, FakeProvider([boom])))
    assert SECRET_PROMPT not in str(ei.value) and ei.value.__cause__ is None
    assert events(db_session)[-1].event_type == "llm.failed"


# ------------------------------------------------------------------ audit + privacy
def test_audit_event_is_scoped_and_content_free(db_session, caplog):
    caplog.set_level(logging.DEBUG)
    fp = FakeProvider([SECRET_REPLY])
    go(svc(db_session, fp), req(SECRET_PROMPT), ws="w2")
    ev = events(db_session, "w2")[-1]
    assert ev.event_type == "llm.completed" and ev.actor == "u1"
    assert ev.payload["purpose"] == "test_purpose" and ev.payload["provider"] == "fake"
    assert {"usage", "latency_ms", "attempts"} <= set(ev.payload)
    assert ev.payload["usage"]["input"] > 0 and ev.payload["usage"]["output"] > 0     # not [REDACTED]
    assert SECRET_PROMPT not in str(ev.payload) and SECRET_REPLY not in str(ev.payload)
    assert SECRET_PROMPT not in caplog.text and SECRET_REPLY not in caplog.text
    assert events(db_session, "w1") == []                      # nothing leaked to another workspace


def test_failure_audit_has_code_only(db_session):
    with pytest.raises(LLMAuthError):
        go(svc(db_session, FakeProvider([LLMAuthError(SECRET_PROMPT)])), req(SECRET_PROMPT))
    assert SECRET_PROMPT not in str(events(db_session)[-1].payload)


def test_purpose_label_is_truncated(db_session):
    svc(db_session).complete(workspace_id="w1", actor=None, purpose="p" * 500, request=req())
    assert len(events(db_session)[-1].payload["purpose"]) == 64
