"""OAuth2 refresh-token support for connectors whose access tokens expire (Step 10.4).

Stored secret (one encrypted string, so the credential store is unchanged):  client_id:client_secret:refresh_token
Config: `base_url` (the API host) and optional `oauth_url` (the token endpoint; default: Google's). The token URL gets the same https rule and
SSRF guard as `base_url`.

TokenManager   exchanges the refresh token for short-lived access tokens, caches the token in memory only, refreshes it
               shortly before it expires (one refresh at a time, even with many threads), and refuses tokens that carry
               more access than the connector allows. After a failed refresh it does not call the identity provider
               again for FAILURE_COOLDOWN seconds, so a revoked grant cannot be hammered.
OAuthConnector KitConnector whose bearer token comes from a TokenManager. If the API rejects a token that is older than
               MIN_TOKEN_AGE it is dropped and the request is retried exactly once with a fresh one; a freshly issued
               token that is rejected is a real permission problem and is not retried.

Errors are fixed text; neither the token endpoint's body nor any secret is ever echoed. Refresh tokens that the provider
rotates are kept in memory only (Google does not rotate them); persisting a rotated token is not built.
"""
import json
import re
import threading
import time
from typing import Any, Callable, Dict, FrozenSet, Optional, Tuple

import httpx
from pydantic import SecretStr

from app.config import Settings
from app.connectors import netguard
from app.connectors.base import ConnectorConfig, HttpConnector
from app.connectors.errors import (ConnectorAuthError, ConnectorBadResponseError, ConnectorConfigError,
                                   ConnectorError, ConnectorRateLimitedError, ConnectorTimeoutError,
                                   ConnectorUnavailableError)
from app.connectors.kit import KitConnector, MAX_SECRET_CHARS
from app.connectors.writes import WriteGate, check_write_flag

DEFAULT_TOKEN_URL = "https://oauth2.googleapis.com/token"
REFRESH_SKEW = 60.0               # refresh this many seconds before the token really expires
MIN_TOKEN_AGE = 30.0              # a younger token that the API rejects is not refreshed and retried
FAILURE_COOLDOWN = 30.0           # no new refresh attempt this long after a failed one
MAX_TOKEN_RESPONSE_BYTES = 65_536
BASE_SCOPES = frozenset({"openid", "email", "profile"})
_TOKEN_RE = re.compile(r"^[A-Za-z0-9._~+/=\-]{8,4096}$")


def parse_oauth_secret(secret: str) -> Tuple[str, str, str]:
    parts = secret.split(":")
    if len(parts) != 3 or not all(p and len(p) <= MAX_SECRET_CHARS and " " not in p for p in parts):
        raise ConnectorConfigError("OAuth credentials must be client_id:client_secret:refresh_token")
    return parts[0], parts[1], parts[2]


def check_oauth_config(config: Dict[str, Any]) -> None:
    """Create-time shape check for the optional oauth_url (no DNS)."""
    check_write_flag(config)
    url = config.get("oauth_url") if isinstance(config, dict) else None
    if url is None:
        return
    if not isinstance(url, str) or not url:
        raise ConnectorConfigError("config.oauth_url must be a URL")
    ConnectorConfig(base_url=url)                                              # absolute http(s), no credentials/query
    netguard.assert_public_host(url, resolve_dns=False)


def resolve_token_url(config: Dict[str, Any], settings: Settings) -> str:
    """Build-time: https in production and every address public (DNS-checked)."""
    url = config.get("oauth_url", DEFAULT_TOKEN_URL)
    if not isinstance(url, str) or not url:
        raise ConnectorConfigError("config.oauth_url must be a URL")
    ConnectorConfig(base_url=url, require_https=settings.is_production)
    netguard.assert_public_host(url, allow_private=settings.allow_private_connector_hosts)
    return url


class TokenManager:
    def __init__(self, *, token_url: str, client_id: str, client_secret: str, refresh_token: str,
                 allowed_scopes: FrozenSet[str], timeout: float = 10.0,
                 transport: Optional[httpx.BaseTransport] = None, clock: Callable[[], float] = time.monotonic):
        self._url, self._cid, self._csecret, self._refresh = token_url, client_id, client_secret, refresh_token
        self._allowed = allowed_scopes | BASE_SCOPES
        self._clock = clock
        self._lock = threading.Lock()
        self._token: Optional[str] = None
        self._issued = 0.0
        self._expires = 0.0
        self._failed_at: Optional[float] = None
        self._client = httpx.Client(timeout=httpx.Timeout(timeout), follow_redirects=False, transport=transport)

    def close(self) -> None:
        self._client.close()

    def __repr__(self) -> str:
        return "<TokenManager>"

    def token(self) -> str:
        with self._lock:
            now = self._clock()
            if self._token is not None and now < self._expires - REFRESH_SKEW:
                return self._token
            return self._refresh_locked(now)

    def drop_if_stale(self) -> bool:
        """True when a token older than MIN_TOKEN_AGE was dropped (so one refresh-and-retry is justified)."""
        with self._lock:
            if self._token is None or self._clock() - self._issued < MIN_TOKEN_AGE:
                return False
            self._token = None
            return True

    # -- refresh (lock held) -------------------------------------------------------
    def _refresh_locked(self, now: float) -> str:
        if self._failed_at is not None and now - self._failed_at < FAILURE_COOLDOWN:
            raise ConnectorAuthError("External system rejected the credentials")        # no call during the cooldown
        try:
            body = self._exchange()
            token, ttl = self._validated(body)
        except ConnectorAuthError:
            self._token, self._failed_at = None, now
            raise
        self._token, self._issued, self._expires, self._failed_at = token, now, now + ttl, None
        return token

    def _exchange(self) -> Any:
        form = {"grant_type": "refresh_token", "refresh_token": self._refresh,
                "client_id": self._cid, "client_secret": self._csecret}
        try:
            with self._client.stream("POST", self._url, data=form, headers={"Accept": "application/json"}) as resp:
                status = resp.status_code
                declared = resp.headers.get("content-length", "")
                if declared.isdigit() and int(declared) > MAX_TOKEN_RESPONSE_BYTES:
                    raise ConnectorBadResponseError("Response too large")
                buf = bytearray()
                for chunk in resp.iter_bytes():
                    buf.extend(chunk)
                    if len(buf) > MAX_TOKEN_RESPONSE_BYTES:
                        raise ConnectorBadResponseError("Response too large")
                retry_after = resp.headers.get("retry-after", "")
        except httpx.TimeoutException:
            raise ConnectorTimeoutError("External system timed out") from None
        except httpx.TransportError:
            raise ConnectorUnavailableError("External system unreachable") from None
        if status == 429:
            raise ConnectorRateLimitedError(retry_after=int(retry_after) if retry_after.isdigit() else None)
        if status >= 500:
            raise ConnectorUnavailableError("External system error")
        if 300 <= status < 400:
            raise ConnectorBadResponseError("Unexpected redirect from external system")
        if status != 200:                                          # invalid_grant, invalid_client, ... never echoed
            raise ConnectorAuthError("External system rejected the credentials")
        try:
            return json.loads(bytes(buf))
        except ValueError:
            raise ConnectorBadResponseError("External system returned invalid JSON") from None

    def _validated(self, body: Any) -> Tuple[str, float]:
        bad = ConnectorBadResponseError("External system returned an unexpected shape")
        if not isinstance(body, dict):
            raise bad
        token, ttl, kind = body.get("access_token"), body.get("expires_in"), body.get("token_type")
        if not isinstance(token, str) or not _TOKEN_RE.match(token):
            raise bad
        if not isinstance(kind, str) or kind.lower() != "bearer":
            raise bad
        if isinstance(ttl, bool) or not isinstance(ttl, int) or not (1 <= ttl <= 86_400):
            raise bad
        scope = body.get("scope")
        if scope is not None:
            if not isinstance(scope, str):
                raise bad
            if not set(scope.split()) <= self._allowed:
                raise ConnectorConfigError("The credential grants more access than this connector allows")
        rotated = body.get("refresh_token")
        if rotated is not None:
            if not isinstance(rotated, str) or not _TOKEN_RE.match(rotated):
                raise bad
            self._refresh = rotated                                # in memory only
        return token, float(ttl)


class OAuthConnector(KitConnector, WriteGate):
    """Subclasses set `allowed_scopes` (read-only scopes only in 10.4) and their probe."""
    auth_kind = "bearer"
    allowed_scopes: FrozenSet[str] = frozenset()          # read-only scopes, always allowed
    write_scopes: FrozenSet[str] = frozenset()            # additionally allowed only when the connection has allow_write

    def __init__(self, config: ConnectorConfig, *, allow_write: bool = False, token_url: str = DEFAULT_TOKEN_URL,
                 transport: Optional[httpx.BaseTransport] = None, clock: Callable[[], float] = time.monotonic, **kw):
        self.allow_write = allow_write
        super().__init__(config, transport=transport, **kw)        # validates the combined secret first
        cid, csecret, refresh = parse_oauth_secret(self._secret)
        self._tokens = TokenManager(token_url=token_url, client_id=cid, client_secret=csecret, refresh_token=refresh,
                                    allowed_scopes=self.allowed_scopes | (self.write_scopes if allow_write else frozenset()),
                                    timeout=config.timeout_seconds,
                                    transport=transport, clock=clock)
        self._secret = ""                                          # only the token manager keeps the secrets now

    def close(self) -> None:
        self._tokens.close()
        super().close()

    def _auth_headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self._tokens.token()}"}

    def _send(self, method: str, path: str, params, json_body) -> Any:
        try:
            return super()._send(method, path, params, json_body)
        except ConnectorAuthError:
            if not self._tokens.drop_if_stale():
                raise
            return super()._send(method, path, params, json_body)  # exactly one retry with a fresh token
