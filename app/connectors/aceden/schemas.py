"""Tool input/output schemas for the Aceden connector.

Outputs are an explicit allow-list: unknown remote fields are dropped, and fields we
do not need (source message text, internal workspace ids) are never exposed to agents.
"""
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

TaskStatusFilter = Literal["to_do", "pending", "active", "in_progress", "completed", "cancelled"]
PriorityFilter = Literal["low", "medium", "high", "critical"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ListTasksInput(_Strict):
    status: Optional[TaskStatusFilter] = None
    priority: Optional[PriorityFilter] = None
    assignee: Optional[str] = Field(default=None, min_length=1, max_length=255)
    skip: int = Field(default=0, ge=0, le=10_000)
    limit: int = Field(default=50, ge=1, le=200)


class GetTaskInput(_Strict):
    task_id: int = Field(ge=1, le=2**31 - 1)


class AcedenTask(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    assignee: Optional[str] = None
    deadline: Optional[str] = None
    priority: str
    status: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ListTasksOutput(BaseModel):
    total: int
    skip: int
    limit: int
    tasks: List[AcedenTask]


class GetTaskOutput(BaseModel):
    task: AcedenTask
