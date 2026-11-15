"""Per-workspace connector construction from stored, encrypted credentials.

WorkspaceConnectors.provider(provider) returns the `provider(workspace_id)` callable the kernel
tools already expect. It uses its OWN short-lived DB session (tool handlers run on pool threads;
a request's Session must not be shared), only ever reads credentials of the requested workspace,
re-checks on every call that the credential is still active, and caches built connectors per
credential (rebuilt automatically after rotation, dropped after revocation).
"""
import threading
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Callable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.connectors.aceden.connector import aceden_tool_definitions
from app.connectors.base import BaseConnector
from app.connectors.calendar.base import calendar_tool_definitions, calendar_write_tool_definitions
from app.connectors.chat.base import chat_tool_definitions, chat_write_tool_definitions
from app.connectors.crm.base import crm_tool_definitions, crm_write_tool_definitions
from app.connectors.email.base import email_tool_definitions, email_write_tool_definitions
from app.connectors.project.base import project_tool_definitions
from app.connectors.errors import ConnectorConfigError, ConnectorError
from app.connectors.registry import get_spec, providers_for
from app.credentials_service import CredentialRevokedError, CredentialService
from app.kernel.registry import ToolRegistry
from app.models.credentials import Credential
from app.models.identity import User


class TestTooSoonError(Exception):
    pass


class UnsupportedProviderError(Exception):
    pass


class WorkspaceConnectors:
    def __init__(self, session_factory: sessionmaker, settings: Settings, *, max_cached: int = 64, **connector_kw):
        self._sf, self._settings, self._kw = session_factory, settings, connector_kw
        self._max = max_cached
        self._cache: "OrderedDict[str, tuple[int, BaseConnector]]" = OrderedDict()
        self._lock = threading.Lock()

    def get(self, workspace_id: str, provider: str) -> BaseConnector:
        spec = get_spec(provider)
        if spec is None:
            raise ConnectorConfigError("Unsupported provider")
        with self._sf() as db:
            creds = db.scalars(select(Credential).where(
                Credential.workspace_id == workspace_id, Credential.provider == provider,
                Credential.is_active.is_(True))).all()
            if not creds:
                raise ConnectorConfigError(f"No {provider} connection configured for this workspace")
            if len(creds) > 1:
                raise ConnectorConfigError(f"Multiple active {provider} connections; revoke the extras")
            cred = creds[0]
            with self._lock:
                hit = self._cache.get(cred.id)
                if hit and hit[0] == cred.version:
                    self._cache.move_to_end(cred.id)
                    return hit[1]
            secret = CredentialService(db, self._settings).reveal_secret(workspace_id, cred.id)
            connector = spec.build(cred.config, secret, self._settings, **self._kw)
        with self._lock:
            old = self._cache.pop(cred.id, None)
            self._cache[cred.id] = (cred.version, connector)
            evicted = [old[1]] if old else []
            while len(self._cache) > self._max:
                evicted.append(self._cache.popitem(last=False)[1][1])
        for c in evicted:
            _close(c)
        return connector

    def provider(self, provider: str) -> Callable[[str], BaseConnector]:
        return lambda workspace_id: self.get(workspace_id, provider)

    def domain_provider(self, workspace_id: str, domain: str) -> str:
        """The ONE provider this workspace has actively connected for a business domain. None or several is refused
        (never guessed), so a domain tool can never reach a system the admins did not clearly choose."""
        providers = providers_for(domain)
        if not providers:
            raise ConnectorConfigError(f"No connector exists for {domain} yet")
        with self._sf() as db:
            found = sorted(set(db.scalars(select(Credential.provider).where(
                Credential.workspace_id == workspace_id, Credential.provider.in_(providers),
                Credential.is_active.is_(True)))))
        if not found:
            raise ConnectorConfigError(f"No {domain} connection configured for this workspace")
        if len(found) > 1:
            raise ConnectorConfigError(f"Multiple active {domain} connections; revoke the extras")
        return found[0]

    def for_domain(self, domain: str) -> Callable[[str], BaseConnector]:
        """`provider(workspace_id)` callable for domain-level tools (crm.*, email.*, ...)."""
        return lambda workspace_id: self.get(workspace_id, self.domain_provider(workspace_id, domain))

    def close(self) -> None:
        with self._lock:
            conns, self._cache = [v[1] for v in self._cache.values()], OrderedDict()
        for c in conns:
            _close(c)


def _close(connector: BaseConnector) -> None:
    try:
        connector.close()          # type: ignore[attr-defined]
    except Exception:
        pass


def register_workspace_tools(registry: ToolRegistry, connectors: WorkspaceConnectors) -> ToolRegistry:
    """Registers each supported connector's kernel tools, resolved per workspace."""
    for tool in aceden_tool_definitions(connectors.provider("aceden")):
        registry.register(tool)
    for tool in crm_tool_definitions(connectors.for_domain("crm")):         # vendor-neutral: whichever CRM is connected
        registry.register(tool)
    for tool in chat_tool_definitions(connectors.for_domain("chat")):
        registry.register(tool)
    for tool in project_tool_definitions(connectors.for_domain("project")):
        registry.register(tool)
    for tool in email_tool_definitions(connectors.for_domain("email")):
        registry.register(tool)
    for tool in calendar_tool_definitions(connectors.for_domain("calendar")):
        registry.register(tool)
    # write tools (10.5): always approval-gated by the kernel, and refused by the connector unless allow_write is set
    for definitions, domain in ((crm_write_tool_definitions, "crm"), (email_write_tool_definitions, "email"),
                                (calendar_write_tool_definitions, "calendar"), (chat_write_tool_definitions, "chat")):
        for tool in definitions(connectors.for_domain(domain)):
            registry.register(tool)
    return registry


def test_credential(db: Session, settings: Settings, workspace_id: str, credential_id: str, actor: User, **connector_kw) -> dict:
    """Outbound connection test for one stored credential. Records the result + an audit event."""
    svc = CredentialService(db, settings)
    cred = svc.get(workspace_id, credential_id)                      # CredentialNotFoundError -> 404
    if not cred.is_active:
        raise CredentialRevokedError("Credential is revoked")
    if cred.provider == "llm":                                       # LLM keys (Step 5.2) are not connectors
        from app.llm.credentials import test_llm_credential
        return test_llm_credential(db, settings, workspace_id, credential_id, actor, **connector_kw)
    spec = get_spec(cred.provider)
    if spec is None:
        raise UnsupportedProviderError("No connector exists for this provider yet")
    last = cred.last_tested_at
    if last is not None:
        last = last if last.tzinfo else last.replace(tzinfo=timezone.utc)
        if (datetime.now(timezone.utc) - last).total_seconds() < settings.connection_test_cooldown_seconds:
            raise TestTooSoonError("Connection was tested moments ago; try again shortly")

    capabilities: list[str] = []
    try:
        connector = spec.build(cred.config, svc.reveal_secret(workspace_id, cred.id), settings, **connector_kw)
        try:
            status = connector.validate_connection()
            ok, message = status.ok, status.message
            capabilities = [c.name for c in connector.capabilities()] if ok else []
        finally:
            _close(connector)
    except ConnectorError as exc:
        ok, message = False, exc.code
    svc.record_test(workspace_id, cred.id, actor, ok=ok, message=message[:64])
    return {"ok": ok, "message": message, "provider": cred.provider, "capabilities": capabilities,
            "tested_at": cred.last_tested_at}
