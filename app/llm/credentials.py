"""Workspace-owned LLM credentials (provider name "llm") and per-workspace provider resolution.

A workspace may store its own OpenAI-compatible key (config: base_url, model, optional
timeout_seconds; secret: the API key, encrypted like every other credential). If it has none,
the platform provider from settings is used. Resolution only ever reads the requested workspace.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, Optional

from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.credentials_service import CredentialRevokedError, CredentialService
from app.llm.base import LLMProvider
from app.llm.errors import LLMConfigError, LLMError
from app.llm.openai_compatible import OpenAICompatibleProvider
from app.llm.registry import build_provider
from app.llm.service import LLMService
from app.llm.types import LLMRequest, Message, MessageRole
from app.models.credentials import Credential
from app.models.identity import User

LLM_CREDENTIAL_PROVIDER = "llm"
_ALLOWED_CONFIG = {"base_url", "model", "timeout_seconds"}


def _build(config: Dict[str, Any], secret: str, settings: Settings, **kw) -> OpenAICompatibleProvider:
    base_url, model = config.get("base_url"), config.get("model")
    if not isinstance(base_url, str) or not base_url or not isinstance(model, str) or not model:
        raise LLMConfigError("config.base_url and config.model are required")
    return OpenAICompatibleProvider(base_url, SecretStr(secret), model, require_https=settings.is_production,
                                    allow_private_host=settings.allow_private_connector_hosts, **kw)


def validate_llm_config(config: Dict[str, Any], settings: Settings) -> None:
    """Create-time check (shape + literal-IP rules, no DNS, no network)."""
    from app.connectors import netguard
    from app.connectors.base import ConnectorConfig
    from app.connectors.errors import ConnectorConfigError
    if set(config) - _ALLOWED_CONFIG:
        raise LLMConfigError("Unknown config keys")
    base_url, model = config.get("base_url"), config.get("model")
    if not isinstance(base_url, str) or not base_url or not isinstance(model, str) or not model:
        raise LLMConfigError("config.base_url and config.model are required")
    if len(model) > 100 or any(ord(c) < 33 for c in model):
        raise LLMConfigError("Invalid model name")
    try:
        ConnectorConfig(base_url=base_url, require_https=settings.is_production)
        netguard.assert_public_host(base_url, allow_private=settings.allow_private_connector_hosts, resolve_dns=False)
    except ConnectorConfigError as exc:
        raise LLMConfigError(f"Invalid LLM endpoint: {exc}") from None
    if "timeout_seconds" in config:
        t = config["timeout_seconds"]
        if isinstance(t, bool) or not isinstance(t, (int, float)) or not 1 <= t <= 300:
            raise LLMConfigError("timeout_seconds must be between 1 and 300")


def resolve_provider(db: Session, settings: Settings, workspace_id: str, **kw) -> LLMProvider:
    """Workspace credential if one is active, otherwise the platform provider."""
    creds = db.scalars(select(Credential).where(
        Credential.workspace_id == workspace_id, Credential.provider == LLM_CREDENTIAL_PROVIDER,
        Credential.is_active.is_(True))).all()
    if len(creds) > 1:
        raise LLMConfigError("Multiple active LLM connections; revoke the extras")
    if not creds:
        return build_provider(settings, **kw) if kw else build_provider(settings)
    secret = CredentialService(db, settings).reveal_secret(workspace_id, creds[0].id)
    return _build(creds[0].config, secret, settings, **kw)


@contextmanager
def workspace_llm(db: Session, settings: Settings, workspace_id: str, **kw) -> Iterator[LLMService]:
    """Yields an LLMService bound to the workspace's provider; always closes the HTTP client."""
    provider = resolve_provider(db, settings, workspace_id, **kw)
    try:
        yield LLMService(db, provider, settings)
    finally:
        provider.close()


def test_llm_credential(db: Session, settings: Settings, workspace_id: str, credential_id: str,
                        actor: User, **kw) -> dict:
    """One 1-token call with the stored key (admin/owner only, cooldown-limited by the caller's route)."""
    from app.connectors.workspace import TestTooSoonError
    svc = CredentialService(db, settings)
    cred = svc.get(workspace_id, credential_id)
    if not cred.is_active:
        raise CredentialRevokedError("Credential is revoked")
    last = cred.last_tested_at
    if last is not None:
        last = last if last.tzinfo else last.replace(tzinfo=timezone.utc)
        if (datetime.now(timezone.utc) - last).total_seconds() < settings.connection_test_cooldown_seconds:
            raise TestTooSoonError("Connection was tested moments ago; try again shortly")
    try:
        provider = _build(cred.config, svc.reveal_secret(workspace_id, cred.id), settings, **kw)
        try:
            provider.complete(LLMRequest(messages=[Message(role=MessageRole.USER, content="Reply with OK.")],
                                         max_output_tokens=5), timeout=min(settings.llm_timeout_seconds, 15))
            ok, message = True, "Connected"
        finally:
            provider.close()
    except LLMError as exc:
        ok, message = False, exc.code
    svc.record_test(workspace_id, cred.id, actor, ok=ok, message=message[:64])
    return {"ok": ok, "message": message, "provider": cred.provider, "capabilities": [],
            "tested_at": cred.last_tested_at}
