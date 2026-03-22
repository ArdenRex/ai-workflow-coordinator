"""
schemas.py
──────────
Pydantic v2 request/response schemas.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models import Priority, TaskStatus


# ─── Request Schemas ──────────────────────────────────────────────────────────

class MessageRequest(BaseModel):
    """Payload for the /process-message endpoint."""
    message: str = Field(
        ...,
        min_length=5,
        max_length=5000,
        examples=["Hey team, John please finish the Q3 report by Friday."],
    )
    source: str = Field(
        default="manual",
        examples=["slack", "email", "manual"],
    )

    @field_validator("message")
    @classmethod
    def message_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("message must not be blank or whitespace only.")
        return v.strip()

    @field_validator("source")
    @classmethod
    def source_normalise(cls, v: str) -> str:
        return v.strip().lower()


class TaskStatusUpdate(BaseModel):
    """Payload for updating a task's status."""
    status: TaskStatus


# ─── AI Extraction Schema ─────────────────────────────────────────────────────

class ExtractedTask(BaseModel):
    """Represents what the AI extracted from a message."""
    task: str = Field(..., min_length=1)
    assignee: Optional[str] = None
    deadline: Optional[str] = None
    priority: Priority = Priority.medium

    @field_validator("task")
    @classmethod
    def task_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("AI-extracted task description must not be blank.")
        return v.strip()

    @field_validator("assignee", mode="before")
    @classmethod
    def assignee_empty_to_none(cls, v: Optional[str]) -> Optional[str]:
        """Treat empty/whitespace assignee strings returned by AI as None."""
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @field_validator("deadline", mode="before")
    @classmethod
    def deadline_empty_to_none(cls, v: Optional[str]) -> Optional[str]:
        """Treat empty/whitespace deadline strings returned by AI as None."""
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @field_validator("priority", mode="before")
    @classmethod
    def priority_normalise(cls, v) -> Priority:
        """Coerce AI string output to a valid Priority; default to medium."""
        if isinstance(v, str):
            try:
                return Priority(v.strip().lower())
            except ValueError:
                return Priority.medium
        return v


# ─── Response Schemas ─────────────────────────────────────────────────────────

class TaskResponse(BaseModel):
    """Full task as returned from the database."""
    id: int
    task_description: str
    assignee: Optional[str] = None
    deadline: Optional[str] = None
    priority: Priority
    source_message: str
    status: TaskStatus
    slack_channel_id: Optional[str] = None
    slack_message_ts: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProcessMessageResponse(BaseModel):
    """Response after processing a message through AI."""
    message: str
    extracted: ExtractedTask
    task: TaskResponse


class TaskListResponse(BaseModel):
    """Paginated list of tasks."""
    total: int
    skip: int = 0
    limit: int = 50
    tasks: list[TaskResponse]


class HealthResponse(BaseModel):
    """Standard health-check response."""
    status: str
    service: str
    version: str
