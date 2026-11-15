"""Build the Aceden connector from settings."""
from typing import Callable, Optional

from app.config import Settings
from app.connectors.aceden.connector import AcedenConnector
from app.connectors.base import ConnectorConfig
from app.connectors.errors import ConnectorConfigError


def build_aceden_connector(settings: Settings, **kw) -> Optional[AcedenConnector]:
    """Returns None when Aceden is not configured."""
    if not settings.aceden_configured:
        return None
    return AcedenConnector(
        ConnectorConfig(base_url=settings.aceden_base_url, auth_token=settings.aceden_api_key,
                        timeout_seconds=settings.aceden_timeout_seconds,
                        require_https=settings.is_production),
        **kw)


def bound_provider(workspace_id: str, connector: AcedenConnector) -> Callable[[str], AcedenConnector]:
    """Single-tenant provider: ONLY `workspace_id` may use this connector's credentials."""
    def provider(requested_workspace_id: str) -> AcedenConnector:
        if requested_workspace_id != workspace_id:
            raise ConnectorConfigError("No Aceden connection configured for this workspace")
        return connector
    return provider
