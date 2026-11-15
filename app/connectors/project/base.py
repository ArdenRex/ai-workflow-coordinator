"""Project domain interface, schemas and kernel tools (read-only in 10.3).

Tools: `project.project.list`, `project.task.list`, `project.task.get` (permission `project:read`, low risk, no approval).
Names, notes and assignee names are external text: cleaned and capped. Ids are numeric and validated before any request.
"""
from abc import ABC, abstractmethod
from typing import Callable, List, Optional

from pydantic import BaseModel, ConfigDict, Field, StrictBool

from app.connectors.base import BaseConnector
from app.connectors.domains import business_tool
from app.connectors.errors import ConnectorConfigError
from app.connectors.kit import ExternalText
from app.kernel.registry import ToolDefinition

CURSOR_PATTERN = r"^[A-Za-z0-9._=\-]{1,512}$"
ID_PATTERN = r"^[0-9]{1,20}$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ListProjectsInput(_Strict):
    limit: int = Field(default=50, ge=1, le=100)
    cursor: Optional[str] = Field(default=None, pattern=CURSOR_PATTERN)


class ListTasksInput(_Strict):
    project_id: str = Field(pattern=ID_PATTERN)
    limit: int = Field(default=50, ge=1, le=100)
    cursor: Optional[str] = Field(default=None, pattern=CURSOR_PATTERN)
    include_completed: bool = False


class GetTaskInput(_Strict):
    task_id: str = Field(pattern=ID_PATTERN)


class Project(BaseModel):
    id: str = Field(pattern=ID_PATTERN)
    name: ExternalText(200)


class Task(BaseModel):
    id: str = Field(pattern=ID_PATTERN)
    name: ExternalText(300)
    completed: Optional[StrictBool] = None
    due_on: Optional[ExternalText(10)] = None
    assignee_name: Optional[ExternalText(100)] = None
    modified_at: Optional[ExternalText(40)] = None


class TaskDetail(Task):
    notes: Optional[ExternalText(2000)] = None


class ListProjectsOutput(BaseModel):
    projects: List[Project]
    next_cursor: Optional[str] = None


class ListTasksOutput(BaseModel):
    tasks: List[Task]
    next_cursor: Optional[str] = None


class GetTaskOutput(BaseModel):
    task: TaskDetail


class ProjectConnector(ABC):
    """What a connector must provide to serve the `project` domain (read side)."""

    @abstractmethod
    def list_projects(self, data: ListProjectsInput) -> ListProjectsOutput: ...

    @abstractmethod
    def list_tasks(self, data: ListTasksInput) -> ListTasksOutput: ...

    @abstractmethod
    def get_task(self, data: GetTaskInput) -> GetTaskOutput: ...


def _project(provider: Callable[[str], BaseConnector], workspace_id: str) -> ProjectConnector:
    connector = provider(workspace_id)
    if not isinstance(connector, ProjectConnector):
        raise ConnectorConfigError("The connected system does not support project tools")
    return connector


def project_tool_definitions(provider: Callable[[str], BaseConnector]) -> List[ToolDefinition]:
    def _projects(ctx, data: ListProjectsInput):
        return _project(provider, ctx.workspace_id).list_projects(data).model_dump()

    def _tasks(ctx, data: ListTasksInput):
        return _project(provider, ctx.workspace_id).list_tasks(data).model_dump()

    def _task(ctx, data: GetTaskInput):
        return _project(provider, ctx.workspace_id).get_task(data).model_dump()

    return [
        business_tool("project", "read", resource="project", action="list", handler=_projects, timeout_seconds=30,
                      description="List active projects of the connected project-management system.",
                      input_schema=ListProjectsInput, output_schema=ListProjectsOutput),
        business_tool("project", "read", resource="task", action="list", handler=_tasks, timeout_seconds=30,
                      description="List tasks of one project (open tasks unless include_completed is true).",
                      input_schema=ListTasksInput, output_schema=ListTasksOutput),
        business_tool("project", "read", resource="task", action="get", handler=_task, timeout_seconds=30,
                      description="Get one task, including its notes, by id.",
                      input_schema=GetTaskInput, output_schema=GetTaskOutput),
    ]
