"""Asana connector (read-only): projects and tasks of ONE configured Asana workspace, via a personal access token.

Config: `base_url` (e.g. https://app.asana.com/api/1.0) and `workspace_gid` (digits, required). A token can often reach
several Asana workspaces, so every project and task read is checked to belong to the configured workspace; anything else
looks like "not found". Only GET requests are made. Shapes follow Asana's REST API as I know it; verify against a real
account before relying on it in production.
"""
import re
from typing import Any, Dict, List, Optional

from pydantic import ValidationError

from app.connectors.base import Capability
from app.connectors.errors import ConnectorBadResponseError, ConnectorConfigError, ConnectorNotFoundError
from app.connectors.kit import KitConnector
from app.connectors.project.base import (CURSOR_PATTERN, ID_PATTERN, GetTaskInput, GetTaskOutput, ListProjectsInput,
                                         ListProjectsOutput, ListTasksInput, ListTasksOutput, Project, ProjectConnector,
                                         Task, TaskDetail, project_tool_definitions)
from app.kernel.registry import ToolDefinition

_CURSOR = re.compile(CURSOR_PATTERN)
_ID = re.compile(ID_PATTERN)
_TASK_FIELDS = "name,completed,due_on,assignee.name,modified_at,workspace.gid"
_bad = lambda: ConnectorBadResponseError("External system returned an unexpected shape")  # noqa: E731


def check_asana_config(config: Dict[str, Any]) -> str:
    gid = config.get("workspace_gid") if isinstance(config, dict) else None
    if not isinstance(gid, str) or not _ID.match(gid):
        raise ConnectorConfigError("config.workspace_gid is required (digits only)")
    return gid


class AsanaConnector(KitConnector, ProjectConnector):
    name = "asana"
    auth_kind = "bearer"
    probe_path = "/users/me"

    def __init__(self, config, *, workspace_gid: str, **kw):
        if not _ID.match(workspace_gid or ""):
            raise ConnectorConfigError("config.workspace_gid is required (digits only)")
        self.workspace_gid = workspace_gid
        super().__init__(config, **kw)

    def capabilities(self) -> List[Capability]:
        return [Capability("project.list", "List projects"), Capability("task.list", "List tasks of a project"),
                Capability("task.get", "Get one task")]

    def tools(self) -> List[ToolDefinition]:
        return project_tool_definitions(lambda workspace_id: self)

    # -- helpers -----------------------------------------------------------------
    def _data(self, path: str, params: dict):
        raw = self._request("GET", path, params=params)
        if not isinstance(raw, dict) or "data" not in raw:
            raise _bad()
        return raw

    @staticmethod
    def _next(raw: dict) -> Optional[str]:
        page = raw.get("next_page")
        if page is None:
            return None
        offset = page.get("offset") if isinstance(page, dict) else False
        if offset is None:
            return None
        if not isinstance(offset, str) or not _CURSOR.match(offset):
            raise _bad()
        return offset

    @staticmethod
    def _gid(item: Any) -> dict:
        if not isinstance(item, dict) or not isinstance(item.get("gid"), str) or not _ID.match(item["gid"]):
            raise _bad()
        return item

    def _in_workspace(self, item: dict) -> bool:
        ws = item.get("workspace")
        return isinstance(ws, dict) and ws.get("gid") == self.workspace_gid

    def _require_project(self, project_id: str) -> None:
        raw = self._data(f"/projects/{project_id}", {"opt_fields": "workspace.gid,archived"})
        item = raw["data"]
        if not isinstance(item, dict) or not self._in_workspace(item) or item.get("archived") is True:
            raise ConnectorNotFoundError("Resource not found in external system")

    def _task(self, item: Any, detail: bool = False) -> Task:
        item = self._gid(item)
        assignee = item.get("assignee")
        if assignee is not None and not isinstance(assignee, dict):
            raise _bad()
        fields = dict(id=item["gid"], name=item.get("name"), completed=item.get("completed"), due_on=item.get("due_on"),
                      assignee_name=(assignee or {}).get("name"), modified_at=item.get("modified_at"))
        try:
            return TaskDetail(**fields, notes=item.get("notes")) if detail else Task(**fields)
        except ValidationError:
            raise _bad() from None

    # -- reads -------------------------------------------------------------------
    def list_projects(self, data: ListProjectsInput) -> ListProjectsOutput:
        params = {"workspace": self.workspace_gid, "archived": "false", "limit": data.limit, "opt_fields": "name"}
        if data.cursor:
            params["offset"] = data.cursor
        raw = self._data("/projects", params)
        if not isinstance(raw["data"], list):
            raise _bad()
        try:
            projects = [Project(id=self._gid(p)["gid"], name=p.get("name")) for p in raw["data"]]
        except ValidationError:
            raise _bad() from None
        return ListProjectsOutput(projects=projects[:data.limit], next_cursor=self._next(raw))

    def list_tasks(self, data: ListTasksInput) -> ListTasksOutput:
        self._require_project(data.project_id)
        params = {"project": data.project_id, "limit": data.limit, "opt_fields": "name,completed,due_on,assignee.name,modified_at"}
        if not data.include_completed:
            params["completed_since"] = "now"
        if data.cursor:
            params["offset"] = data.cursor
        raw = self._data("/tasks", params)
        if not isinstance(raw["data"], list):
            raise _bad()
        return ListTasksOutput(tasks=[self._task(t) for t in raw["data"]][:data.limit], next_cursor=self._next(raw))

    def get_task(self, data: GetTaskInput) -> GetTaskOutput:
        raw = self._data(f"/tasks/{data.task_id}", {"opt_fields": _TASK_FIELDS + ",notes"})
        item = raw["data"]
        task = self._task(item, detail=True)
        if task.id != data.task_id:
            raise _bad()
        if not self._in_workspace(item):
            raise ConnectorNotFoundError("Resource not found in external system")
        return GetTaskOutput(task=task)
