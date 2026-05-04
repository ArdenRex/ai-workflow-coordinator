"""
schemas.py
──────────
Pydantic v2 request/response schemas.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models import Priority, TaskStatus, UserRole


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


# ─── Task Response Schemas ────────────────────────────────────────────────────

class TaskResponse(BaseModel):
    """Full task as returned from the database."""
    id: int
    title: Optional[str] = None
    task_description: Optional[str] = None
    assignee: Optional[str] = None
    assignee_id: Optional[str] = None
    deadline: Optional[str] = None
    priority: Priority
    source_message: Optional[str] = None
    status: TaskStatus
    slack_channel_id: Optional[str] = None
    slack_message_ts: Optional[str] = None
    owner_id: Optional[int] = None
    workspace_id: Optional[int] = None
    # Segment 3 — ping tracking
    pinged_at: Optional[datetime] = None
    owner_pinged_at: Optional[datetime] = None
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


# ─── Auth Request Schemas ─────────────────────────────────────────────────────

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


# ─── Auth Response Schemas ────────────────────────────────────────────────────

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
    role: str = "admin"   # "admin" or "freelancer" — used by dashboard to pick the right view
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


# ─── Workspace Settings Schemas (Segment 2 + 3) ───────────────────────────────

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
    # Segment 3 — escalation target
    owner_slack_id: Optional[str] = Field(
        default=None,
        description="Slack user ID of the workspace architect — receives escalation DMs at 2× drift threshold.",
        examples=["U012AB3CD"],
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
                "owner_slack_id": "U012AB3CD",
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
    owner_slack_id: Optional[str] = None   # Segment 3
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


# ─── Onboarding Checklist Schemas (Segment 7) ────────────────────────────────

class OnboardingStepUpdate(BaseModel):
    """
    Payload for POST /onboarding/step.
    Marks one checklist step as complete for the current user.

    step values:
        slack_connected      — Step 1: Slack OAuth done
        first_command_sent   — Step 2: First bot command sent
        dashboard_viewed     — Step 3: Dashboard opened
        teammate_invited     — Step 4: Invite sent to a teammate
    """
    step: str = Field(
        ...,
        description="Step identifier to mark complete.",
        examples=["slack_connected", "first_command_sent", "dashboard_viewed", "teammate_invited"],
    )

    @field_validator("step")
    @classmethod
    def step_must_be_valid(cls, v: str) -> str:
        valid = {"slack_connected", "first_command_sent", "dashboard_viewed", "teammate_invited"}
        if v not in valid:
            raise ValueError(f"step must be one of: {', '.join(sorted(valid))}")
        return v


class OnboardingProgressResponse(BaseModel):
    """
    Full onboarding checklist state returned to the frontend.
    Use this to render the progress bar and step checkboxes.
    """
    user_id: int

    # Step flags
    slack_connected: bool
    slack_connected_at: Optional[datetime]

    first_command_sent: bool
    first_command_sent_at: Optional[datetime]

    dashboard_viewed: bool
    dashboard_viewed_at: Optional[datetime]

    teammate_invited: bool
    teammate_invited_at: Optional[datetime]

    # Completion
    is_completed: bool
    completed_at: Optional[datetime]

    # Computed helpers (returned from model properties)
    steps_completed: int        # 0–4
    total_steps: int            # always 4
    progress_label: str         # e.g. "3/4 steps to full setup"

    model_config = {"from_attributes": True}


# ─── Segment 11 — Integration Schemas ────────────────────────────────────────

class IntegrationConfig(BaseModel):
    """
    Payload for PUT /integrations/config.
    All fields optional — only supplied keys are merged into stored config.

    Notion:
        notion_token         — Integration token (secret_…)
        notion_database_id   — ID of the Notion DB to push pages into

    Jira:
        jira_base_url        — e.g. https://yourorg.atlassian.net
        jira_email           — Atlassian account email
        jira_api_token       — API token from id.atlassian.com
        jira_project_key     — e.g. "PROJ"

    Trello:
        trello_api_key       — from trello.com/app-key
        trello_token         — OAuth token
        trello_list_id       — ID of the Trello list to add cards to
    """
    # Notion
    notion_token: Optional[str] = Field(default=None, min_length=1, max_length=500)
    notion_database_id: Optional[str] = Field(default=None, min_length=1, max_length=100)

    # Jira
    jira_base_url: Optional[str] = Field(default=None, min_length=1, max_length=255)
    jira_email: Optional[str] = Field(default=None, min_length=1, max_length=255)
    jira_api_token: Optional[str] = Field(default=None, min_length=1, max_length=500)
    jira_project_key: Optional[str] = Field(default=None, min_length=1, max_length=20)

    # Trello
    trello_api_key: Optional[str] = Field(default=None, min_length=1, max_length=100)
    trello_token: Optional[str] = Field(default=None, min_length=1, max_length=500)
    trello_list_id: Optional[str] = Field(default=None, min_length=1, max_length=100)

    @field_validator("jira_base_url", mode="before")
    @classmethod
    def jira_url_strip(cls, v: Optional[str]) -> Optional[str]:
        return v.strip().rstrip("/") if isinstance(v, str) else v

    @field_validator("jira_project_key", mode="before")
    @classmethod
    def project_key_upper(cls, v: Optional[str]) -> Optional[str]:
        return v.strip().upper() if isinstance(v, str) else v


class IntegrationSyncRequest(BaseModel):
    """
    Payload for POST /integrations/{service}/sync.
    task_ids: list of specific task IDs to push.
    Omit or pass [] to sync all workspace tasks.
    """
    task_ids: Optional[list[int]] = Field(
        default=None,
        description="Task IDs to sync. Leave empty to sync all workspace tasks.",
    )


class TaskSyncResult(BaseModel):
    """Per-task result from a sync operation."""
    task_id: int
    success: bool
    external_id: Optional[str] = None    # Notion page ID / Jira issue key / Trello card ID
    external_url: Optional[str] = None   # Direct link to the created item
    error: Optional[str] = None          # Error message if success=False


class IntegrationSyncResponse(BaseModel):
    """Summary returned after a sync operation."""
    integration: str                     # "notion" | "jira" | "trello"
    total: int
    succeeded: int
    failed: int
    results: list[TaskSyncResult]


class IntegrationStatusResponse(BaseModel):
    """Which integrations are fully configured for the workspace."""
    notion_configured: bool
    jira_configured: bool
    trello_configured: bool


# ─── Segment 12 — Locale / i18n Schemas ──────────────────────────────────────

SUPPORTED_LANGUAGES: dict[str, str] = {
    "en":    "English",
    "ar":    "Arabic",
    "zh":    "Chinese (Simplified)",
    "zh-TW": "Chinese (Traditional)",
    "fr":    "French",
    "de":    "German",
    "hi":    "Hindi",
    "id":    "Indonesian",
    "it":    "Italian",
    "ja":    "Japanese",
    "ko":    "Korean",
    "ms":    "Malay",
    "pt":    "Portuguese",
    "ru":    "Russian",
    "es":    "Spanish",
    "sv":    "Swedish",
    "tr":    "Turkish",
    "ur":    "Urdu",
    "vi":    "Vietnamese",
}

SUPPORTED_CURRENCIES: dict[str, str] = {
    "USD": "US Dollar ($)",
    "EUR": "Euro (€)",
    "GBP": "British Pound (£)",
    "JPY": "Japanese Yen (¥)",
    "CNY": "Chinese Yuan (¥)",
    "INR": "Indian Rupee (₹)",
    "PKR": "Pakistani Rupee (₨)",
    "AED": "UAE Dirham (د.إ)",
    "SAR": "Saudi Riyal (﷼)",
    "CAD": "Canadian Dollar (CA$)",
    "AUD": "Australian Dollar (A$)",
    "CHF": "Swiss Franc (CHF)",
    "SGD": "Singapore Dollar (S$)",
    "MYR": "Malaysian Ringgit (RM)",
    "BRL": "Brazilian Real (R$)",
    "KRW": "South Korean Won (₩)",
    "TRY": "Turkish Lira (₺)",
    "SEK": "Swedish Krona (kr)",
    "NOK": "Norwegian Krone (kr)",
    "IDR": "Indonesian Rupiah (Rp)",
}

# Common IANA timezones grouped by region (frontend uses this for the picker)
SUPPORTED_TIMEZONES: list[str] = [
    "UTC",
    "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles",
    "America/Toronto", "America/Vancouver", "America/Sao_Paulo", "America/Mexico_City",
    "America/Buenos_Aires", "America/Bogota",
    "Europe/London", "Europe/Paris", "Europe/Berlin", "Europe/Madrid",
    "Europe/Rome", "Europe/Amsterdam", "Europe/Stockholm", "Europe/Moscow",
    "Europe/Istanbul",
    "Asia/Dubai", "Asia/Riyadh", "Asia/Karachi", "Asia/Kolkata",
    "Asia/Dhaka", "Asia/Bangkok", "Asia/Singapore", "Asia/Shanghai",
    "Asia/Tokyo", "Asia/Seoul", "Asia/Jakarta", "Asia/Manila",
    "Asia/Kuala_Lumpur", "Asia/Ho_Chi_Minh",
    "Africa/Cairo", "Africa/Lagos", "Africa/Nairobi",
    "Australia/Sydney", "Australia/Melbourne", "Pacific/Auckland",
]


class UserLocaleUpdate(BaseModel):
    """Payload for PUT /locale/settings — update the current user's locale prefs."""
    language: Optional[str] = Field(default=None, description="BCP-47 language tag, e.g. 'en', 'ar', 'zh'")
    timezone: Optional[str] = Field(default=None, description="IANA timezone, e.g. 'Asia/Karachi'")
    currency: Optional[str] = Field(default=None, description="ISO 4217 currency code, e.g. 'PKR'")

    @field_validator("language", mode="before")
    @classmethod
    def validate_language(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if v not in SUPPORTED_LANGUAGES:
            raise ValueError(f"Unsupported language '{v}'. Supported: {list(SUPPORTED_LANGUAGES.keys())}")
        return v

    @field_validator("currency", mode="before")
    @classmethod
    def validate_currency(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip().upper()
        if v not in SUPPORTED_CURRENCIES:
            raise ValueError(f"Unsupported currency '{v}'. Supported: {list(SUPPORTED_CURRENCIES.keys())}")
        return v

    @field_validator("timezone", mode="before")
    @classmethod
    def validate_timezone(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if v not in SUPPORTED_TIMEZONES:
            raise ValueError(f"Unsupported timezone '{v}'.")
        return v


class WorkspaceLocaleUpdate(BaseModel):
    """Payload for PUT /locale/workspace — update workspace-level locale defaults (Architect only)."""
    default_language: Optional[str] = Field(default=None)
    default_timezone: Optional[str] = Field(default=None)
    default_currency: Optional[str] = Field(default=None)

    @field_validator("default_language", mode="before")
    @classmethod
    def validate_language(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if v not in SUPPORTED_LANGUAGES:
            raise ValueError(f"Unsupported language '{v}'.")
        return v

    @field_validator("default_currency", mode="before")
    @classmethod
    def validate_currency(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip().upper()
        if v not in SUPPORTED_CURRENCIES:
            raise ValueError(f"Unsupported currency '{v}'.")
        return v

    @field_validator("default_timezone", mode="before")
    @classmethod
    def validate_timezone(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if v not in SUPPORTED_TIMEZONES:
            raise ValueError(f"Unsupported timezone '{v}'.")
        return v


class UserLocaleResponse(BaseModel):
    """Current locale settings for the authenticated user."""
    user_id: int
    language: str
    language_label: str
    timezone: str
    currency: str
    currency_label: str

    model_config = {"from_attributes": True}


class WorkspaceLocaleResponse(BaseModel):
    """Workspace-level locale defaults."""
    workspace_id: int
    default_language: str
    default_language_label: str
    default_timezone: str
    default_currency: str
    default_currency_label: str

    model_config = {"from_attributes": True}


class LocaleOptionsResponse(BaseModel):
    """All supported languages, timezones, currencies — used to populate dropdowns."""
    languages: dict[str, str]    # {"en": "English", ...}
    timezones: list[str]
    currencies: dict[str, str]   # {"USD": "US Dollar ($)", ...}


# ─── Segment 6 — Viral Onboarding / Social Proof Schemas ─────────────────────

class WorkspaceStatsResponse(BaseModel):
    """Social proof metrics shown on the dashboard."""
    tasks_this_month:   int
    total_tasks:        int
    active_members:     int
    top_assignee:       Optional[str] = None
    top_assignee_count: int = 0
    completion_rate:    float = 0.0
    done_tasks:         int = 0


# ─── Segment 9 — Microsoft Teams Schemas ─────────────────────────────────────

class TeamsConfigUpdate(BaseModel):
    """Payload for PUT /teams/config — save the Azure AD tenant ID."""
    tenant_id: Optional[str] = Field(
        default=None,
        description="Azure AD / Teams tenant ID (from Azure portal).",
        examples=["xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"],
    )

    @field_validator("tenant_id", mode="before")
    @classmethod
    def tenant_strip(cls, v: Optional[str]) -> Optional[str]:
        return v.strip() if isinstance(v, str) else v


class TeamsConfigResponse(BaseModel):
    """Returned after saving Teams config."""
    tenant_id: Optional[str] = None
    updated: bool = True


class TeamsStatusResponse(BaseModel):
    """Connection status returned by GET /teams/status."""
    connected: bool
    tenant_id: Optional[str] = None
    bot_configured: bool
    webhook_url: str
    channel_count: int = 0


class TeamsChannelCreate(BaseModel):
    """Payload for POST /teams/channels — register a channel."""
    channel_id: str = Field(..., description="Teams channel ID")
    channel_name: str = Field(..., description="Human-readable channel name", max_length=255)
    service_url: str = Field(..., description="Bot Framework service URL for this channel")
    conversation_id: str = Field(..., description="Teams conversation ID for proactive messages")

    @field_validator("channel_id", "service_url", "conversation_id", mode="before")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        return v.strip() if isinstance(v, str) else v


class TeamsChannelResponse(BaseModel):
    """A registered Teams channel."""
    id: int
    workspace_id: int
    channel_id: str
    channel_name: str
    service_url: str
    conversation_id: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ─── Segment 13 — Public API Schemas ─────────────────────────────────────────

class PublicTaskCreate(BaseModel):
    """Payload for POST /api/v1/tasks — create a task from an external tool."""
    title: str = Field(..., min_length=1, max_length=500, description="Task title")
    description: Optional[str] = Field(default=None, max_length=5000)
    assignee: Optional[str] = Field(default=None, max_length=255)
    deadline: Optional[str] = Field(default=None, max_length=100, description="ISO date or natural string")
    priority: Optional[Priority] = Field(default=Priority.medium)
    status: Optional[TaskStatus] = Field(default=TaskStatus.to_do)
    source: Optional[str] = Field(default=None, max_length=100, description="e.g. 'notion', 'jira', 'trello'")

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("title must not be blank.")
        return v.strip()


class PublicTaskUpdate(BaseModel):
    """Payload for PUT /api/v1/tasks/{id} — partial update."""
    task_description: Optional[str] = Field(default=None, max_length=5000)
    assignee: Optional[str] = Field(default=None, max_length=255)
    deadline: Optional[str] = Field(default=None, max_length=100)
    priority: Optional[Priority] = None
    status: Optional[TaskStatus] = None


class PublicTaskResponse(BaseModel):
    """Task as returned by the public API."""
    id: int
    title: str
    description: Optional[str] = None
    assignee: Optional[str] = None
    deadline: Optional[str] = None
    priority: str
    status: str
    workspace_id: Optional[int] = None
    source_message: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class PublicTaskListResponse(BaseModel):
    """Paginated list of tasks from the public API."""
    total: int
    skip: int = 0
    limit: int = 50
    tasks: list[PublicTaskResponse]


class ApiKeyCreate(BaseModel):
    """Payload for POST /api/v1/keys — create a new API key."""
    name: str = Field(
        ..., min_length=1, max_length=255,
        description="Human-readable label, e.g. 'Notion Integration'",
        examples=["Notion Integration", "Jira Webhook", "Zapier"],
    )

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("name must not be blank.")
        return v.strip()


class ApiKeyResponse(BaseModel):
    """API key as shown in the dashboard (no raw key — only prefix)."""
    id: int
    name: str
    key_prefix: str
    workspace_id: int
    is_active: bool
    last_used_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ApiKeyCreatedResponse(BaseModel):
    """Returned once after key creation — includes the full raw key."""
    id: int
    name: str
    key: str          # ← full raw key, shown only once
    key_prefix: str
    workspace_id: int
    is_active: bool
    created_at: datetime
