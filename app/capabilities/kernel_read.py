"""Shared pieces for business capabilities (Step 11): one kernel read with fixed failure states, plus small text/time helpers.

A capability never touches a connector. It submits ordinary read tools to the execution kernel as the calling principal, so each
read is permission-checked, policy-checked, rate-limited per connection and audited like any other tool call. A read that cannot
be served becomes one of a few FIXED states; remote error text is never kept.
"""
from datetime import datetime, timezone
from typing import Any, Dict, Literal, Optional, Tuple

from app.kernel.errors import KernelError, PolicyDeniedError
from app.kernel.permissions import Principal
from app.kernel.service import ToolExecutionService
from app.models.enums import ExecutionStatus

SourceState = Literal["ok", "not_permitted", "unavailable", "auth_failed", "rate_limited", "failed"]


class SourceFailed(Exception):
    def __init__(self, state: SourceState):
        super().__init__(state)
        self.state = state


def read_tool(kernel: ToolExecutionService, principal: Principal, tool_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    try:
        tool = kernel.registry.get(tool_id)
        if not principal.can(tool.required_permission):
            raise SourceFailed("not_permitted")       # convenience pre-check (no execution, no denial noise); the kernel enforces it again
        ex = kernel.submit(principal, tool_id, data)
    except SourceFailed:
        raise
    except PolicyDeniedError:
        raise SourceFailed("not_permitted") from None
    except KernelError:
        raise SourceFailed("unavailable") from None
    if ex.status != ExecutionStatus.SUCCEEDED or not isinstance(ex.output, dict):
        error = ex.error or ""
        if "ConnectorConfigError" in error:
            raise SourceFailed("unavailable")         # not connected, or connected for writes only / misconfigured
        if "ConnectorAuthError" in error:
            raise SourceFailed("auth_failed")
        if "ConnectorRateLimitedError" in error:
            raise SourceFailed("rate_limited")
        raise SourceFailed("failed")
    return ex.output


def parse_dt(text: Any) -> Optional[datetime]:
    if not isinstance(text, str):
        return None
    try:
        value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if value.tzinfo else None


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def title(text: Any, fallback: str) -> Tuple[str, bool]:
    """(text capped at 200, is_external_text). Fixed fallbacks are not external."""
    if isinstance(text, str) and text.strip():
        return text.strip()[:200], True
    return fallback, False
