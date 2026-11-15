"""Aceden connector (read-only, via Aceden's public API, X-API-Key auth).

Aceden is just one connected system: nothing here imports Aceden's code. The kernel
tools resolve the connector per workspace through a provider, so credentials for
workspace A can never serve a request from workspace B.
"""
from typing import Callable, List

from pydantic import ValidationError
from pydantic import SecretStr

from app.connectors.aceden.schemas import (GetTaskInput, GetTaskOutput, ListTasksInput, ListTasksOutput)
from app.connectors.base import Capability, ConnectorConfig, HttpConnector
from app.connectors.errors import ConnectorBadResponseError, ConnectorConfigError
from app.kernel.registry import ToolDefinition
from app.models.enums import RiskLevel

API_PREFIX = "/api/v1"


class AcedenConnector(HttpConnector):
    name = "aceden"
    probe_path = f"{API_PREFIX}/tasks"
    probe_params = {"limit": 1}

    def __init__(self, config: ConnectorConfig, **kw):
        if config.auth_token is None or not config.auth_token.get_secret_value().strip():
            raise ConnectorConfigError("Aceden connector requires an API key")
        super().__init__(config, **kw)

    def _auth_headers(self):
        return {"X-API-Key": self.config.auth_token.get_secret_value().strip()}

    def capabilities(self) -> List[Capability]:
        return [Capability("task.list", "List tasks in the connected Aceden workspace"),
                Capability("task.get", "Get one task by id")]

    # -- reads (typed, validated) -----------------------------------------------
    def list_tasks(self, data: ListTasksInput) -> ListTasksOutput:
        params = {k: v for k, v in data.model_dump().items() if v is not None}
        raw = self._request("GET", f"{API_PREFIX}/tasks", params=params)
        return self._parse(ListTasksOutput, raw)

    def get_task(self, data: GetTaskInput) -> GetTaskOutput:
        raw = self._request("GET", f"{API_PREFIX}/tasks/{int(data.task_id)}")
        return self._parse(GetTaskOutput, {"task": raw})

    @staticmethod
    def _parse(model, raw):
        try:
            return model.model_validate(raw)
        except ValidationError:
            raise ConnectorBadResponseError("External system returned an unexpected shape") from None

    def tools(self) -> List[ToolDefinition]:
        return aceden_tool_definitions(lambda workspace_id: self)


def aceden_tool_definitions(provider: Callable[[str], AcedenConnector]) -> List[ToolDefinition]:
    """Kernel tools. `provider(workspace_id)` returns that workspace's connector."""

    def _list(ctx, data: ListTasksInput):
        return provider(ctx.workspace_id).list_tasks(data).model_dump()

    def _get(ctx, data: GetTaskInput):
        return provider(ctx.workspace_id).get_task(data).model_dump()

    return [
        ToolDefinition(id="aceden.task.list", description="List tasks from the connected Aceden workspace, "
                       "optionally filtered by status, priority or assignee.",
                       input_schema=ListTasksInput, output_schema=ListTasksOutput,
                       required_permission="task:read", risk_level=RiskLevel.LOW,
                       timeout_seconds=30, handler=_list),
        ToolDefinition(id="aceden.task.get", description="Get a single task from the connected Aceden workspace.",
                       input_schema=GetTaskInput, output_schema=GetTaskOutput,
                       required_permission="task:read", risk_level=RiskLevel.LOW,
                       timeout_seconds=30, handler=_get),
    ]
