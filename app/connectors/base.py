"""Connector base classes.

BaseConnector      contract every connector implements (auth, validation, capabilities, tools)
HttpConnector      shared, hardened HTTP behaviour (timeouts, error mapping, size caps)
"""
import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

import httpx
from pydantic import SecretStr

from app.connectors.ratelimit import CallLimiter
from app.connectors.errors import (ConnectorAuthError, ConnectorBadResponseError, ConnectorConfigError,
                                   ConnectorError, ConnectorNotFoundError, ConnectorRateLimitedError,
                                   ConnectorRequestError, ConnectorTimeoutError, ConnectorUnavailableError)
from app.kernel.registry import ToolDefinition

logger = logging.getLogger(__name__)
MAX_TIMEOUT = 60.0


@dataclass(frozen=True)
class Capability:
    name: str            # e.g. "customer.read"
    description: str
    write: bool = False


@dataclass(frozen=True)
class ConnectionStatus:
    ok: bool
    message: str


@dataclass(frozen=True)
class ConnectorConfig:
    base_url: str
    auth_token: Optional[SecretStr] = None
    timeout_seconds: float = 10.0
    max_response_bytes: int = 1_000_000
    max_retries: int = 1                 # applied to GET only
    require_https: bool = False          # True in production
    max_calls_per_minute: int = 0        # outbound limit per connection; 0 = unlimited (see ratelimit.py)

    def __post_init__(self) -> None:
        u = urlparse(self.base_url)
        if u.scheme not in ("http", "https") or not u.netloc:
            raise ConnectorConfigError("base_url must be an absolute http(s) URL")
        if u.username or u.password or u.query or u.fragment:
            raise ConnectorConfigError("base_url must not contain credentials, query or fragment")
        if self.require_https and u.scheme != "https":
            raise ConnectorConfigError("https is required")
        if not (0 < self.timeout_seconds <= MAX_TIMEOUT):
            raise ConnectorConfigError("timeout_seconds out of range")
        if not (0 <= self.max_calls_per_minute <= 100_000):
            raise ConnectorConfigError("max_calls_per_minute out of range")
        if not (0 <= self.max_retries <= 3) or self.max_response_bytes <= 0:
            raise ConnectorConfigError("invalid retry or size limit")


class BaseConnector(ABC):
    name: str = ""

    @abstractmethod
    def capabilities(self) -> List[Capability]: ...

    @abstractmethod
    def validate_connection(self) -> ConnectionStatus:
        """Cheap authenticated call proving credentials and reachability. Never raises."""

    @abstractmethod
    def tools(self) -> List[ToolDefinition]:
        """Kernel tools this connector provides (registered by the kernel, not called directly)."""


class HttpConnector(BaseConnector):
    def __init__(self, config: ConnectorConfig, *, transport: Optional[httpx.BaseTransport] = None,
                 sleep: Callable[[float], None] = time.sleep):
        self.config = config
        self._sleep = sleep
        self._limiter = CallLimiter(config.max_calls_per_minute)
        self._client = httpx.Client(
            base_url=config.base_url.rstrip("/"),
            timeout=httpx.Timeout(config.timeout_seconds),
            follow_redirects=False,          # never forward credentials to another host
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __repr__(self) -> str:               # never reveals credentials
        return f"<{type(self).__name__} base_url={self.config.base_url}>"

    # -- auth (override for other schemes) ------------------------------------
    def _auth_headers(self) -> Dict[str, str]:
        if self.config.auth_token is None:
            return {}
        return {"Authorization": f"Bearer {self.config.auth_token.get_secret_value()}"}

    # -- request ---------------------------------------------------------------
    @staticmethod
    def _check_path(path: str) -> None:
        if (not path.startswith("/") or path.startswith("//") or "://" in path
                or ".." in path or "\\" in path or "?" in path or "#" in path
                or any(ord(c) < 33 for c in path)):
            raise ConnectorRequestError("Invalid request path")

    def _request(self, method: str, path: str, *, params: Optional[dict] = None,
                 json_body: Optional[Any] = None) -> Any:
        self._check_path(path)
        self._limiter.acquire()                  # refused locally (no request) when this connection is over its limit
        method = method.upper()
        attempts = 1 + (self.config.max_retries if method == "GET" else 0)   # never retry writes
        last: ConnectorError | None = None
        for attempt in range(attempts):
            try:
                return self._send(method, path, params, json_body)
            except ConnectorError as exc:
                last = exc
                if not exc.retryable or attempt == attempts - 1:
                    break
                delay = exc.retry_after if isinstance(exc, ConnectorRateLimitedError) and exc.retry_after else 0.2 * (attempt + 1)
                self._sleep(min(float(delay), 5.0))
        assert last is not None
        raise last

    def _send(self, method: str, path: str, params, json_body) -> Any:
        headers = {"Accept": "application/json", **self._auth_headers()}
        try:
            with self._client.stream(method, path, params=params, json=json_body, headers=headers) as resp:
                status = resp.status_code
                body = self._read_capped(resp) if status < 400 or status in (429,) else b""
        except httpx.TimeoutException:
            raise ConnectorTimeoutError("External system timed out") from None
        except httpx.TransportError:
            raise ConnectorUnavailableError("External system unreachable") from None

        if 300 <= status < 400:
            raise ConnectorBadResponseError("Unexpected redirect from external system")
        if status in (401, 403):
            raise ConnectorAuthError("External system rejected the credentials")
        if status == 404:
            raise ConnectorNotFoundError("Resource not found in external system")
        if status == 429:
            ra = resp.headers.get("retry-after", "")
            raise ConnectorRateLimitedError(retry_after=int(ra) if ra.isdigit() else None)
        if 400 <= status < 500:
            raise ConnectorRequestError("External system rejected the request")
        if status >= 500:
            raise ConnectorUnavailableError("External system error")
        if status == 204 or not body:
            return None
        try:
            return json.loads(body)
        except ValueError:
            raise ConnectorBadResponseError("External system returned invalid JSON") from None

    def _read_capped(self, resp: httpx.Response) -> bytes:
        cap = self.config.max_response_bytes
        declared = resp.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > cap:
            raise ConnectorBadResponseError("Response too large")
        buf = bytearray()
        for chunk in resp.iter_bytes():
            buf.extend(chunk)
            if len(buf) > cap:
                raise ConnectorBadResponseError("Response too large")
        return bytes(buf)

    # -- default connection test built on a connector-defined probe ------------
    probe_path: str = "/"
    probe_params: Optional[dict] = None

    def validate_connection(self) -> ConnectionStatus:
        try:
            self._request("GET", self.probe_path, params=self.probe_params)
            return ConnectionStatus(True, "Connected")
        except ConnectorError as exc:
            return ConnectionStatus(False, f"{exc.code}")
        except Exception:                       # never raise from a status check
            logger.exception("Unexpected error validating connection")
            return ConnectionStatus(False, "connector_error")
