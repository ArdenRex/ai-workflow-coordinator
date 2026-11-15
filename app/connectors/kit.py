"""Connector kit: the shared, provider-neutral building blocks every business connector (Step 10) uses.

KitConnector   HttpConnector with a declared auth scheme (bearer, a named header, or basic) and validated secrets.
build_config   the one place a stored credential + config becomes a ConnectorConfig (SSRF guard included).
clean_text     external text is untrusted: control, zero-width and bidi-override characters are stripped and the
               length is capped, so a remote system cannot smuggle hidden text into outputs that agents may read.
ExternalText   pydantic type applying clean_text to an output field.
paginate       bounded cursor pagination: page and item ceilings, loop detection, an honest `truncated` flag.

Nothing here executes a tool or holds authority; connectors are still only reached through kernel tools.
"""
import re
from dataclasses import dataclass
from typing import Annotated, Any, Callable, Dict, List, Optional, Tuple

from pydantic import BeforeValidator, SecretStr

from app.config import Settings
from app.connectors import netguard
from app.connectors.base import ConnectorConfig, HttpConnector
from app.connectors.errors import ConnectorBadResponseError, ConnectorConfigError

AUTH_KINDS = ("bearer", "header", "basic")
_HEADER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9-]{0,63}$")
_RESERVED_HEADERS = frozenset({"host", "content-length", "content-type", "transfer-encoding", "connection", "cookie",
                               "set-cookie", "accept", "accept-encoding", "user-agent", "te", "upgrade", "expect"})
MAX_SECRET_CHARS = 4096


class KitConnector(HttpConnector):
    """Subclasses declare `auth_kind` (and `auth_header` for kind "header"); the secret never leaves the config."""
    auth_kind: str = "bearer"
    auth_header: str = "Authorization"

    def __init_subclass__(cls, **kw) -> None:
        super().__init_subclass__(**kw)
        if cls.auth_kind not in AUTH_KINDS:
            raise ConnectorConfigError("Unknown auth kind")
        if cls.auth_kind == "header" and (not _HEADER_RE.match(cls.auth_header)
                                          or cls.auth_header.lower() in _RESERVED_HEADERS
                                          or cls.auth_header.lower() == "authorization"):
            raise ConnectorConfigError("Invalid auth header name")

    def __init__(self, config: ConnectorConfig, **kw):
        self._secret = self._checked_secret(config)
        super().__init__(config, **kw)

    @classmethod
    def _checked_secret(cls, config: ConnectorConfig) -> str:
        if config.auth_token is None:
            raise ConnectorConfigError("This connector requires a credential")
        secret = config.auth_token.get_secret_value().strip()
        if not secret or len(secret) > MAX_SECRET_CHARS or any(ord(c) < 33 and c != " " or ord(c) == 127 for c in secret):
            raise ConnectorConfigError("The credential is not valid for this connector")
        if cls.auth_kind != "basic" and " " in secret:
            raise ConnectorConfigError("The credential is not valid for this connector")
        if cls.auth_kind == "basic" and ":" not in secret:
            raise ConnectorConfigError("Basic credentials must be user:password")
        return secret

    def _auth_headers(self) -> Dict[str, str]:
        if self.auth_kind == "bearer":
            return {"Authorization": f"Bearer {self._secret}"}
        if self.auth_kind == "header":
            return {self.auth_header: self._secret}
        import base64
        return {"Authorization": "Basic " + base64.b64encode(self._secret.encode("utf-8")).decode("ascii")}


def build_config(config: Dict[str, Any], secret: str, settings: Settings) -> ConnectorConfig:
    """Stored credential config -> ConnectorConfig, with the https rule and the SSRF guard (DNS-checked)."""
    base_url = config.get("base_url") if isinstance(config, dict) else None
    if not isinstance(base_url, str) or not base_url:
        raise ConnectorConfigError("config.base_url is required")
    try:
        timeout = float(config.get("timeout_seconds", settings.aceden_timeout_seconds))
    except (TypeError, ValueError):
        raise ConnectorConfigError("timeout_seconds must be a number") from None
    cfg = ConnectorConfig(base_url=base_url, auth_token=SecretStr(secret), timeout_seconds=timeout,
                          require_https=settings.is_production,
                          max_calls_per_minute=settings.connector_max_calls_per_minute)
    netguard.assert_public_host(cfg.base_url, allow_private=settings.allow_private_connector_hosts)
    return cfg


# ------------------------------------------------------------------ untrusted external text
_HIDDEN = {c: None for c in (list(range(0x200B, 0x2010)) + list(range(0x202A, 0x202F)) + list(range(0x2060, 0x2065))
                             + list(range(0x2066, 0x206A)) + [0xFEFF, 0x2028, 0x2029, 0x00AD])}
DEFAULT_TEXT_CHARS = 2000


def clean_text(value: Any, max_chars: int = DEFAULT_TEXT_CHARS) -> Optional[str]:
    """None stays None; anything but a string is rejected (never coerced). Output is bounded and printable."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("expected text")
    kept = "".join(ch for ch in value.translate(_HIDDEN) if ch in "\n\t" or (ord(ch) >= 32 and ord(ch) != 127))
    return kept[:max_chars]


def ExternalText(max_chars: int = DEFAULT_TEXT_CHARS):
    """`subject: ExternalText(200)` in an output model: cleaned and capped before it can reach anything else."""
    return Annotated[str, BeforeValidator(lambda v: clean_text(v, max_chars) if v is not None else v)]


# ------------------------------------------------------------------ bounded pagination
@dataclass(frozen=True)
class Page:
    items: List[Any]
    truncated: bool            # True when the remote had more than we were willing to read


def paginate(fetch: Callable[[Optional[str]], Tuple[List[Any], Optional[str]]], *, max_pages: int = 5,
             max_items: int = 200) -> Page:
    """`fetch(cursor)` returns (items, next_cursor or None). Never reads more than max_pages pages or keeps more than
    max_items items, and a cursor the remote repeats is a bad response rather than an endless loop."""
    if not (1 <= max_pages <= 20 and 1 <= max_items <= 1000):
        raise ConnectorConfigError("pagination bounds out of range")
    items: List[Any] = []
    cursor: Optional[str] = None
    seen = set()
    for _ in range(max_pages):
        batch, cursor = fetch(cursor)
        items.extend(batch)
        if len(items) >= max_items:
            return Page(items[:max_items], truncated=len(items) > max_items or cursor is not None)
        if cursor is None:
            return Page(items, truncated=False)
        if cursor in seen:
            raise ConnectorBadResponseError("External system returned a repeating cursor")
        seen.add(cursor)
    return Page(items, truncated=True)
