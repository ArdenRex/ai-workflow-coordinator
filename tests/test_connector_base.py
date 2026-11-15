import httpx
import pytest
from pydantic import SecretStr

from app.connectors.base import Capability, ConnectorConfig, HttpConnector
from app.connectors.errors import (ConnectorAuthError, ConnectorBadResponseError, ConnectorConfigError,
                                   ConnectorNotFoundError, ConnectorRateLimitedError, ConnectorRequestError,
                                   ConnectorTimeoutError, ConnectorUnavailableError)


class Dummy(HttpConnector):
    name = "dummy"
    probe_path = "/ping"

    def capabilities(self):
        return [Capability("thing.read", "read things")]

    def tools(self):
        return []


def make(handler, **cfg):
    sleeps = []
    c = Dummy(ConnectorConfig(base_url="https://api.example.com", auth_token=SecretStr("tok-123"), **cfg),
              transport=httpx.MockTransport(handler), sleep=sleeps.append)
    c.sleeps = sleeps
    return c


# ---- config
@pytest.mark.parametrize("url", ["ftp://x.com", "api.example.com", "https://u:p@x.com", "https://x.com?a=1", ""])
def test_bad_base_urls_rejected(url):
    with pytest.raises(ConnectorConfigError):
        ConnectorConfig(base_url=url)


def test_config_limits_and_https_requirement():
    with pytest.raises(ConnectorConfigError):
        ConnectorConfig(base_url="http://x.com", require_https=True)
    for kw in ({"timeout_seconds": 0}, {"timeout_seconds": 999}, {"max_retries": 9}):
        with pytest.raises(ConnectorConfigError):
            ConnectorConfig(base_url="https://x.com", **kw)


def test_token_never_in_repr():
    c = make(lambda r: httpx.Response(200, json={}))
    cfg = ConnectorConfig(base_url="https://x.com", auth_token=SecretStr("super-secret"))
    assert "super-secret" not in repr(c) and "super-secret" not in repr(cfg)


# ---- success + auth header
def test_get_success_sends_bearer_and_parses_json():
    seen = {}

    def h(req):
        seen["auth"], seen["url"] = req.headers["authorization"], str(req.url)
        return httpx.Response(200, json={"ok": 1})
    c = make(h)
    assert c._request("GET", "/v1/items", params={"a": "b"}) == {"ok": 1}
    assert seen["auth"] == "Bearer tok-123" and seen["url"].endswith("/v1/items?a=b")


def test_204_returns_none():
    assert make(lambda r: httpx.Response(204))._request("GET", "/x") is None


# ---- path safety (no SSRF / host override)
@pytest.mark.parametrize("path", ["v1/x", "//evil.com/x", "https://evil.com/x", "/a/../b", "/a\\b", "/a?b=1", "/a b"])
def test_unsafe_paths_rejected_without_network(path):
    called = []
    c = make(lambda r: called.append(1) or httpx.Response(200, json={}))
    with pytest.raises(ConnectorRequestError):
        c._request("GET", path)
    assert called == []


# ---- error mapping (bodies never leaked)
@pytest.mark.parametrize("status,exc", [(401, ConnectorAuthError), (403, ConnectorAuthError),
                                        (404, ConnectorNotFoundError), (400, ConnectorRequestError),
                                        (422, ConnectorRequestError)])
def test_status_mapping(status, exc):
    c = make(lambda r: httpx.Response(status, text="SECRET-BODY tok-123"))
    with pytest.raises(exc) as e:
        c._request("POST", "/x", json_body={})
    assert "SECRET-BODY" not in str(e.value) and "tok-123" not in str(e.value)


def test_redirects_not_followed():
    c = make(lambda r: httpx.Response(302, headers={"location": "https://evil.com"}))
    with pytest.raises(ConnectorBadResponseError):
        c._request("GET", "/x")


def test_invalid_json_and_oversize():
    with pytest.raises(ConnectorBadResponseError):
        make(lambda r: httpx.Response(200, text="<html>"))._request("GET", "/x")
    with pytest.raises(ConnectorBadResponseError):
        make(lambda r: httpx.Response(200, content=b"x" * 100), max_response_bytes=10)._request("GET", "/x")


# ---- retries
def test_get_retries_5xx_then_succeeds():
    n = {"c": 0}

    def h(req):
        n["c"] += 1
        return httpx.Response(503) if n["c"] == 1 else httpx.Response(200, json={"ok": True})
    c = make(h)
    assert c._request("GET", "/x") == {"ok": True} and n["c"] == 2 and len(c.sleeps) == 1


def test_get_gives_up_after_max_retries():
    n = {"c": 0}
    c = make(lambda r: (n.__setitem__("c", n["c"] + 1), httpx.Response(500))[1], max_retries=2)
    with pytest.raises(ConnectorUnavailableError):
        c._request("GET", "/x")
    assert n["c"] == 3


def test_writes_are_never_retried():
    n = {"c": 0}
    c = make(lambda r: (n.__setitem__("c", n["c"] + 1), httpx.Response(503))[1])
    with pytest.raises(ConnectorUnavailableError):
        c._request("POST", "/x", json_body={})
    assert n["c"] == 1 and c.sleeps == []


def test_auth_errors_not_retried():
    n = {"c": 0}
    c = make(lambda r: (n.__setitem__("c", n["c"] + 1), httpx.Response(401))[1], max_retries=3)
    with pytest.raises(ConnectorAuthError):
        c._request("GET", "/x")
    assert n["c"] == 1


def test_rate_limit_honours_retry_after_capped():
    n = {"c": 0}

    def h(req):
        n["c"] += 1
        return httpx.Response(429, headers={"retry-after": "999"}) if n["c"] == 1 else httpx.Response(200, json={})
    c = make(h)
    c._request("GET", "/x")
    assert c.sleeps == [5.0]                     # capped


def test_rate_limit_exhausted_raises_with_retry_after():
    c = make(lambda r: httpx.Response(429, headers={"retry-after": "7"}), max_retries=0)
    with pytest.raises(ConnectorRateLimitedError) as e:
        c._request("GET", "/x")
    assert e.value.retry_after == 7


# ---- transport failures
def test_timeout_and_network_errors_mapped():
    def timeout(req):
        raise httpx.ReadTimeout("slow")

    def down(req):
        raise httpx.ConnectError("refused")
    with pytest.raises(ConnectorTimeoutError):
        make(timeout, max_retries=0)._request("GET", "/x")
    with pytest.raises(ConnectorUnavailableError):
        make(down, max_retries=0)._request("GET", "/x")


# ---- connection validation never raises
def test_validate_connection_ok_and_failures():
    assert make(lambda r: httpx.Response(200, json={})).validate_connection().ok is True
    bad = make(lambda r: httpx.Response(401)).validate_connection()
    assert bad.ok is False and bad.message == "connector_auth_failed"
    assert make(lambda r: (_ for _ in ()).throw(RuntimeError("boom"))).validate_connection().ok is False
