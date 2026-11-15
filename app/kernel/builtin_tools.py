"""Built-in system tools. External-system tools come from connectors (Step 3+)."""
from pydantic import BaseModel, ConfigDict

from app.kernel.registry import ToolDefinition, ToolRegistry
from app.models.enums import RiskLevel


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PingInput(_Strict):
    message: str = "ping"


class PingOutput(_Strict):
    reply: str


def _ping(ctx, data: PingInput) -> dict:
    return {"reply": data.message}


SYSTEM_PING = ToolDefinition(
    id="system.ping",
    description="Health check tool that echoes a message. No external effects.",
    input_schema=PingInput,
    output_schema=PingOutput,
    required_permission="system:read",
    risk_level=RiskLevel.LOW,
    timeout_seconds=5,
    handler=_ping,
)


def build_default_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(SYSTEM_PING)
    return registry
