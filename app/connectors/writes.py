"""Shared rules for connector write tools (Step 10.5).

Writes need TWO deliberate opt-ins, so a read-only connection can never be turned into a writing one by accident:
  1. the credential's config says `"allow_write": true` (set by an admin when the connection is created), and
  2. for OAuth providers the Google grant must stay inside the connector's read + write scope allow-list.
Without (1) every write method refuses before any request is made. Write tools themselves are always approval-gated by the
kernel (business_tool); nothing here grants authority.

Text that will be written into someone else's system is checked here: control characters, header-injection characters and
oversized values are rejected, never silently altered.
"""
import re
from typing import Any, Dict, List

from app.connectors.errors import ConnectorConfigError

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9\-]{1,63}(\.[A-Za-z0-9\-]{1,63})+$")
MAX_EMAIL_CHARS = 254


def check_write_flag(config: Dict[str, Any]) -> None:
    """Create-time rule: `allow_write`, when present, must be a real boolean."""
    if isinstance(config, dict) and "allow_write" in config and not isinstance(config["allow_write"], bool):
        raise ConnectorConfigError("config.allow_write must be true or false")


def write_enabled(config: Dict[str, Any]) -> bool:
    return isinstance(config, dict) and config.get("allow_write") is True


class WriteGate:
    allow_write: bool = False

    def _require_write(self) -> None:
        if not self.allow_write:
            raise ConnectorConfigError("Write access is not enabled for this connection")


def check_email(value: str) -> str:
    if not isinstance(value, str) or len(value) > MAX_EMAIL_CHARS or not EMAIL_RE.match(value):
        raise ValueError("not a valid email address")
    return value


def check_email_list(values: List[str]) -> List[str]:
    cleaned = [check_email(v) for v in values]
    if len({v.lower() for v in cleaned}) != len(cleaned):
        raise ValueError("duplicate addresses")
    return cleaned


def check_line(value: str) -> str:
    """Single-line text: no control characters at all (blocks header and field injection)."""
    if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 or ord(c) == 127 or c in "\u2028\u2029" for c in value):
        raise ValueError("must be non-blank single-line text")
    return value.strip()


def check_block(value: str) -> str:
    """Multi-line text: newlines and tabs allowed, other control characters and bidi/zero-width tricks are not."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("must not be blank")
    for c in value:
        o = ord(c)
        if (o < 32 and c not in "\n\t\r") or o == 127 or 0x200B <= o <= 0x200F or 0x202A <= o <= 0x202E \
                or 0x2060 <= o <= 0x2069 or o == 0xFEFF:
            raise ValueError("contains disallowed characters")
    return value.replace("\r\n", "\n").replace("\r", "\n")
