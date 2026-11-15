"""Provider -> connector spec. Adding a connector = adding one ConnectorSpec here."""
from dataclasses import dataclass
from typing import Any, Callable, Dict, FrozenSet, List, Optional

from pydantic import SecretStr

from app.config import Settings
from app.connectors import netguard
from app.connectors.aceden.connector import AcedenConnector
from app.connectors.base import BaseConnector, ConnectorConfig
from app.connectors.crm.hubspot import HubSpotConnector
from app.connectors.calendar.google_calendar import GoogleCalendarConnector
from app.connectors.chat.slack import SlackConnector
from app.connectors.email.gmail import GmailConnector
from app.connectors.oauth import check_oauth_config, resolve_token_url
from app.connectors.kit import build_config
from app.connectors.project.asana import AsanaConnector, check_asana_config
from app.connectors.errors import ConnectorConfigError
from app.connectors.writes import check_write_flag, write_enabled


@dataclass(frozen=True)
class ConnectorSpec:
    provider: str
    build: Callable[..., BaseConnector]            # (config, secret, settings, **kw) -> connector
    domains: FrozenSet[str] = frozenset()          # business domains this provider serves (see connectors/domains.py)
    check_config: Optional[Callable[[Dict[str, Any]], None]] = None   # extra create-time config rules (raise ConnectorConfigError)


def _aceden(config: Dict[str, Any], secret: str, settings: Settings, **kw) -> AcedenConnector:
    base_url = config.get("base_url")
    if not isinstance(base_url, str) or not base_url:
        raise ConnectorConfigError("config.base_url is required")
    try:
        timeout = float(config.get("timeout_seconds", settings.aceden_timeout_seconds))
    except (TypeError, ValueError):
        raise ConnectorConfigError("timeout_seconds must be a number") from None
    cfg = ConnectorConfig(base_url=base_url, auth_token=SecretStr(secret), timeout_seconds=timeout,
                          require_https=settings.is_production)
    netguard.assert_public_host(cfg.base_url, allow_private=settings.allow_private_connector_hosts)
    return AcedenConnector(cfg, **kw)


def _hubspot(config: Dict[str, Any], secret: str, settings: Settings, **kw) -> HubSpotConnector:
    return HubSpotConnector(build_config(config, secret, settings), allow_write=write_enabled(config), **kw)


def _slack(config: Dict[str, Any], secret: str, settings: Settings, **kw) -> SlackConnector:
    return SlackConnector(build_config(config, secret, settings), allow_write=write_enabled(config), **kw)


def _asana(config: Dict[str, Any], secret: str, settings: Settings, **kw) -> AsanaConnector:
    gid = check_asana_config(config)
    return AsanaConnector(build_config(config, secret, settings), workspace_gid=gid, **kw)


def _gmail(config: Dict[str, Any], secret: str, settings: Settings, **kw) -> GmailConnector:
    return GmailConnector(build_config(config, secret, settings), allow_write=write_enabled(config), token_url=resolve_token_url(config, settings), **kw)


def _google_calendar(config: Dict[str, Any], secret: str, settings: Settings, **kw) -> GoogleCalendarConnector:
    return GoogleCalendarConnector(build_config(config, secret, settings), allow_write=write_enabled(config),
                                   token_url=resolve_token_url(config, settings), **kw)


SPECS: Dict[str, ConnectorSpec] = {"aceden": ConnectorSpec("aceden", _aceden),
                                   "hubspot": ConnectorSpec("hubspot", _hubspot, frozenset({"crm"}), check_write_flag),
                                   "slack": ConnectorSpec("slack", _slack, frozenset({"chat"}), check_write_flag),
                                   "asana": ConnectorSpec("asana", _asana, frozenset({"project"}),
                                                          lambda config: check_asana_config(config)),
                                   "gmail": ConnectorSpec("gmail", _gmail, frozenset({"email"}), check_oauth_config),
                                   "google_calendar": ConnectorSpec("google_calendar", _google_calendar,
                                                                    frozenset({"calendar"}), check_oauth_config)}


def get_spec(provider: str) -> Optional[ConnectorSpec]:
    return SPECS.get(provider)


def providers_for(domain: str) -> List[str]:
    """Providers that declare they serve a business domain, in a stable order."""
    return sorted(p for p, s in SPECS.items() if domain in s.domains)


def validate_config(provider: str, config: Dict[str, Any], settings: Settings) -> None:
    """Create-time check: shape + literal-IP rules only (no DNS). Providers without a connector
    spec are stored as-is (their connector arrives in a later step)."""
    if provider not in SPECS:
        return
    if SPECS[provider].check_config is not None:
        SPECS[provider].check_config(config)
    base_url = config.get("base_url")
    if not isinstance(base_url, str) or not base_url:
        raise ConnectorConfigError("config.base_url is required")
    ConnectorConfig(base_url=base_url, require_https=settings.is_production)     # URL shape / https rule
    netguard.assert_public_host(base_url, allow_private=settings.allow_private_connector_hosts, resolve_dns=False)
    if "timeout_seconds" in config:
        try:
            ConnectorConfig(base_url=base_url, timeout_seconds=float(config["timeout_seconds"]))
        except (TypeError, ValueError):
            raise ConnectorConfigError("timeout_seconds must be a number") from None
