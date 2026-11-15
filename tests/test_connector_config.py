import httpx
import pytest
from pydantic import SecretStr, ValidationError

from app.config import Settings
from app.connectors.aceden.factory import bound_provider, build_aceden_connector
from app.connectors.check import main, run_check
from app.connectors.errors import ConnectorConfigError


def S(**kw):
    return Settings(app_env="test", _env_file=None, **kw)


def ok_transport(key="k"):
    return httpx.MockTransport(lambda r: httpx.Response(200, json={"total": 0, "skip": 0, "limit": 1, "tasks": []})
                               if r.headers.get("x-api-key") == key else httpx.Response(401))


# ---- settings
def test_not_configured_by_default():
    s = S()
    assert s.aceden_configured is False and build_aceden_connector(s) is None


@pytest.mark.parametrize("kw", [{"aceden_base_url": "https://a.test"},
                                {"aceden_api_key": "k"},
                                {"aceden_base_url": "https://a.test", "aceden_api_key": "   "}])
def test_partial_config_rejected(kw):
    with pytest.raises(ValidationError):
        S(**kw)


def test_production_requires_https_for_aceden():
    base = dict(app_env="production", app_secret_key="x" * 40, database_url="postgresql://u:p@h/d",
                aceden_api_key="k", llm_provider="openai", _env_file=None)
    with pytest.raises(ValidationError):
        Settings(aceden_base_url="http://a.test", **base)
    assert Settings(aceden_base_url="https://a.test", **base).aceden_configured


def test_api_key_is_secret_in_settings_repr():
    s = S(aceden_base_url="https://a.test", aceden_api_key="very-secret-key")
    assert "very-secret-key" not in repr(s) and "very-secret-key" not in str(s.model_dump())
    assert isinstance(s.aceden_api_key, SecretStr)


# ---- factory + provider
def test_factory_builds_connector_with_settings():
    s = S(aceden_base_url="https://a.test", aceden_api_key="k", aceden_timeout_seconds=3)
    c = build_aceden_connector(s)
    assert c.config.timeout_seconds == 3 and c.config.base_url == "https://a.test"


def test_bound_provider_only_serves_its_workspace():
    c = build_aceden_connector(S(aceden_base_url="https://a.test", aceden_api_key="k"))
    p = bound_provider("w1", c)
    assert p("w1") is c
    with pytest.raises(ConnectorConfigError):
        p("w2")


# ---- connection check
def test_check_not_configured(capsys):
    assert run_check(S())["message"] == "not_configured"
    assert main() in (0, 1)            # environment may or may not have Aceden vars; must not raise


def test_check_ok_and_failure_never_print_secret():
    good = S(aceden_base_url="https://a.test", aceden_api_key="k")
    r = run_check(good, transport=ok_transport("k"))
    assert r == {"connector": "aceden", "configured": True, "ok": True, "message": "Connected"}
    bad = run_check(S(aceden_base_url="https://a.test", aceden_api_key="wrong"), transport=ok_transport("k"))
    assert bad["ok"] is False and bad["message"] == "connector_auth_failed" and "wrong" not in str(bad)
