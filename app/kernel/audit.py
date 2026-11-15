"""Append-only audit trail helper. Payloads are redacted before storage."""
import hashlib
import json
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.kernel import SystemEvent

_SENSITIVE = ("secret", "token", "password", "passwd", "api_key", "apikey", "authorization", "credential")


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: ("[REDACTED]" if any(s in str(k).lower() for s in _SENSITIVE) else redact(v))
                for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def record_event(db: Session, *, workspace_id: str, event_type: str, actor: Optional[str] = None,
                 execution_id: Optional[str] = None, payload: Optional[dict] = None) -> SystemEvent:
    """Adds an event to the session (caller commits, so it is atomic with the change)."""
    ev = SystemEvent(workspace_id=workspace_id, event_type=event_type, actor=actor,
                     execution_id=execution_id, payload=redact(payload or {}))
    db.add(ev)
    return ev


def input_digest(data: Any) -> str:
    """Canonical SHA-256 of a tool input; binds an approval to the exact request."""
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
