"""
schemas.py
──────────
Pydantic v2 request/response schemas.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models import Priority, TaskStatus, UserRole


# ─── Existing Request Schemas (unchanged) ─────────────────────────────────────

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


# ─── Existing AI Extraction Schema (unchanged) ────────────────────────────────

class ExtractedTask(BaseModel):
    """Represents what the AI extracted from a message."""
    task: str = Field(..., min_length=1)
    assignee: Optional[str] = None
    deadline: Optional[str] = None
    priority: Priority = Priority.medium
    urgency: str = Field(
        default="medium",
        description="one of: none | low | medium | high | critical",
    )
    confidence: float = Field(
        default=0.8, ge=0.0, le=1.0,
        description="AI confidence score for this extraction.",
    )

    @field_validator("task")
    @classmethod
    def task_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("AI-extracted task description must not be blank.")
        return v.strip()

    @field_validator("assignee", mode="before")
    @classmethod
    def assignee_empty_to_none(cls, v: Optional[str]) -> Optional[str]:
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @field_validator("deadline", mode="before")
    @classmethod
    def deadline_empty_to_none(cls, v: Optional[str]) -> Optional[str]:
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @field_validator("priority", mode="before")
    @classmethod
    def priority_normalise(cls, v) -> Priority:
        if isinstance(v, str):
            try:
                return Priority(v.strip().lower())
            except ValueError:
                return Priority.medium
        return v

    @field_validator("urgency", mode="before")
    @classmethod
    def urgency_normalise(cls, v) -> str:
        valid = {"none", "low", "medium", "high", "critical"}
        if isinstance(v, str) and v.strip().lower() in valid:
            return v.strip().lower()
        return "medium"

    @field_validator("confidence", mode="before")
    @classmethod
    def confidence_clamp(cls, v) -> float:
        try:
            return max(0.0, min(1.0, float(v)))
        except (TypeError, ValueError):
            return 0.8


# ─── Existing Response Schemas (unchanged) ────────────────────────────────────

class TaskResponse(BaseModel):
    """Full task as returned from the database."""
    id: int
    task_description: Optional[str] = None
    assignee: Optional[str] = None
    deadline: Optional[str] = None
    priority: Priority
    source_message: Optional[str] = None
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


# ─── Auth Request Schemas (unchanged) ────────────────────────────────────────

class RegisterRequest(BaseModel):
    """Step 1 of signup — basic account creation."""
    name: str = Field(..., min_length=2, max_length=255)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Name must not be blank.")
        return v.strip()

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters.")
        return v


class OnboardingRequest(BaseModel):
    """Step 2 + 3 — role selection + workspace setup."""
    role: UserRole
    team_name: Optional[str] = Field(default=None, max_length=255)
    create_workspace: bool = Field(default=True)
    workspace_name: Optional[str] = Field(default=None, max_length=255)
    invite_code: Optional[str] = Field(default=None, max_length=16)

    @field_validator("team_name", mode="before")
    @classmethod
    def team_name_empty_to_none(cls, v: Optional[str]) -> Optional[str]:
        if isinstance(v, str) and not v.strip():
            return None
        return v


class LoginRequest(BaseModel):
    """Email + password login."""
    email: EmailStr
    password: str
    remember_me: bool = Field(default=False)


# ─── Auth Response Schemas (unchanged) ───────────────────────────────────────

class WorkspaceResponse(BaseModel):
    """Workspace info returned to frontend."""
    id: int
    name: str
    invite_code: str

    model_config = {"from_attributes": True}


class UserResponse(BaseModel):
    """User profile returned after login/register."""
    id: int
    name: str
    email: str
    role: UserRole
    team_name: Optional[str] = None
    workspace: Optional[WorkspaceResponse] = None
    is_verified: bool

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    """Returned after successful login."""
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    remember_me: bool
    user: UserResponse


class RegisterResponse(BaseModel):
    """Returned after successful registration (before onboarding)."""
    message: str
    user: UserResponse


class OnboardingResponse(BaseModel):
    """Returned after completing onboarding."""
    message: str
    user: UserResponse
    workspace: WorkspaceResponse


# ─── NEW: Workspace Settings Schemas (Segment 2) ──────────────────────────────

class KeywordRule(BaseModel):
    """A single keyword → priority mapping rule."""
    keyword: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Word or phrase to match (case-insensitive) in the message.",
        examples=["URGENT", "FYI", "ASAP", "blocker"],
    )
    priority: Priority = Field(
        ...,
        description="Priority to apply when this keyword is found.",
        examples=["critical", "high", "low"],
    )

    @field_validator("keyword")
    @classmethod
    def keyword_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Keyword must not be blank.")
        return v.strip().lower()


class WorkspaceSettingsUpdate(BaseModel):
    """
    Payload for PUT /workspace/settings.
    All fields are optional — only provided fields are updated.
    """
    keyword_rules: Optional[list[KeywordRule]] = Field(
        default=None,
        description="List of keyword → priority rules. Replaces all existing rules.",
        examples=[[{"keyword": "URGENT", "priority": "critical"}, {"keyword": "FYI", "priority": "low"}]],
    )
    high_priority_channels: Optional[list[str]] = Field(
        default=None,
        description="Slack channel IDs where all tasks auto-get High priority.",
        examples=[["C08XXXXXX", "C09YYYYYYY"]],
    )
    drift_alert_hours: Optional[int] = Field(
        default=None,
        ge=1,
        le=168,
        description="Hours before unstarted High/Critical tasks trigger a drift alert (1–168).",
        examples=[24],
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "keyword_rules": [
                    {"keyword": "URGENT", "priority": "critical"},
                    {"keyword": "FYI",    "priority": "low"},
                    {"keyword": "ASAP",   "priority": "high"},
                    {"keyword": "blocker","priority": "critical"},
                ],
                "high_priority_channels": ["C08XXXXXX"],
                "drift_alert_hours": 24,
            }
        }
    }


class WorkspaceSettingsResponse(BaseModel):
    """Workspace settings as returned by GET/PUT /workspace/settings."""
    id: int
    workspace_id: int
    keyword_rules: list[dict] = []
    high_priority_channels: list[str] = []
    drift_alert_hours: int = 24
    updated_at: datetime

    model_config = {"from_attributes": True}


class PriorityPreviewRequest(BaseModel):
    """Payload for POST /workspace/settings/preview."""
    message: str = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="The message text to test against your rules.",
        examples=["URGENT: Ali please fix the payment bug before EOD"],
    )
    base_priority: Optional[Priority] = Field(
        default=Priority.medium,
        description="Starting priority (simulates what the AI would extract).",
    )
    urgency: Optional[str] = Field(
        default="medium",
        description="Urgency detected by AI: none | low | medium | high | critical",
    )
    slack_channel_id: Optional[str] = Field(
        default=None,
        description="Optional Slack channel ID to test channel rules.",
        examples=["C08XXXXXX"],
    )


class PriorityPreviewResponse(BaseModel):
    """Result of priority preview."""
    base_priority: Priority
    final_priority: Priority
    boosted: bool
    explanation: str
