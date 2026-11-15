"""Central configuration. Single source of truth for environment settings.

The AI OS is independent of any connected system (including Aceden):
nothing here references a specific external product.
"""
from functools import lru_cache
from typing import List, Optional

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_DEFAULT = "dev-insecure-secret-change-me-0000000000"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    app_name: str = "Aceden AI OS"
    log_level: str = "INFO"
    database_url: str = "sqlite:///./aceden_ai_os.db"
    app_secret_key: str = _INSECURE_DEFAULT
    allowed_origins: str = ""
    # Aceden connector (optional). Single-tenant/dev convenience until Step 4 stores
    # encrypted per-workspace credentials.
    aceden_base_url: Optional[str] = None
    aceden_api_key: Optional[SecretStr] = None
    aceden_timeout_seconds: float = 10.0
    # Auth (Step 4.2)
    access_token_ttl_minutes: int = 60
    remember_me_ttl_days: int = 30                  # F1: lifetime of a token when the user ticks "remember me"
    jwt_issuer: str = "aceden-ai-os"
    # Authentication throttling (14.1). 0 disables the matching limit.
    auth_max_failed_logins: int = 5                 # failures per (email, address) per window; the email-wide limit is 4x this
    auth_lockout_window_seconds: int = 900
    auth_max_requests_per_minute: int = 30          # login + register requests per client address
    trusted_proxy_count: int = 0                    # how many reverse proxies sit in front of the app (0 = none: the direct peer address is used)
    max_request_bytes: int = 4 * 1024 * 1024        # requests declaring a larger Content-Length get 413
    # Old root secrets (comma-separated) still accepted for DECRYPTING credentials after a key change.
    app_secret_key_previous: str = ""
    # Connections (Step 4.5)
    allow_private_connector_hosts: bool = False     # True only for local dev against localhost/LAN
    connection_test_cooldown_seconds: int = 5
    connector_max_calls_per_minute: int = 120       # outbound calls per connection per minute (Step 10.6); 0 = unlimited
    # LLM (Step 5.1). "fake" is offline/deterministic and refused in production.
    llm_provider: str = "fake"
    llm_model: str = "fake-model"
    llm_timeout_seconds: float = 30.0
    llm_max_retries: int = 2
    llm_max_input_chars: int = 40000
    llm_max_output_tokens: int = 1024
    intent_min_confidence: float = 0.5                 # below this, tool/goal intents need clarification
    llm_max_repairs: int = 1                           # structured-output repair attempts
    llm_base_url: Optional[str] = None                 # openai_compatible: e.g. https://api.openai.com/v1
    llm_api_key: Optional[SecretStr] = None
    # Agent runs (Step 6.3). These are CEILINGS: a caller may ask for less, never more.
    agent_run_max_steps: int = 8
    agent_run_max_tool_calls: int = 5
    agent_run_max_llm_calls: int = 8
    agent_run_timeout_seconds: int = 120               # queue wait, and each active stretch of a run
    agent_run_approval_wait_seconds: int = 86400       # how long a run may wait on a human approval
    # Orchestration (Step 7). A CEILING on plan size; a plan may never exceed it.
    plan_max_steps: int = 8
    # Workflows (Step 9). CEILING on steps in one workflow definition.
    workflow_max_steps: int = 10
    workflow_max_definitions: int = 100                # distinct workflow keys per workspace
    workflow_max_active_runs: int = 20                 # pending or running workflow runs per workspace
    workflow_max_event_fanout: int = 10                # workflow runs one event may start
    workflow_max_schedules: int = 20                   # armed schedules per workspace
    workflow_tick_max_schedules: int = 20              # due schedules one scheduler tick fires
    workflow_tick_max_runs: int = 10                   # scheduled/event runs one scheduler tick drives
    # Memory (Step 8). CEILINGS on stored memory.
    memory_max_items: int = 5000                       # active items per workspace
    memory_max_preferences_per_user: int = 50
    # Document ingestion (8.3): ceilings on one uploaded document and on how it is cut up.
    memory_max_document_chars: int = 100000
    memory_max_chunks_per_document: int = 100
    memory_retrieval_max_chars: int = 8000             # total content returned by one retrieval (500-100000)
    memory_prompt_max_chars: int = 3000                # memory text added to ONE model prompt (200-20000)
    memory_prompt_max_hits: int = 5                    # memory hits added to ONE model prompt (1-10)
    memory_chunk_chars: int = 1000                     # target chunk size (max 4000, the memory content limit)

    @field_validator("app_env")
    @classmethod
    def _valid_env(cls, v: str) -> str:
        v = v.lower()
        if v not in {"development", "test", "production"}:
            raise ValueError("APP_ENV must be development, test or production")
        return v

    @field_validator("remember_me_ttl_days")
    @classmethod
    def _valid_remember(cls, v: int) -> int:
        if not 1 <= v <= 90:
            raise ValueError("REMEMBER_ME_TTL_DAYS must be between 1 and 90")
        return v

    @field_validator("access_token_ttl_minutes")
    @classmethod
    def _valid_ttl(cls, v: int) -> int:
        if not 1 <= v <= 1440:
            raise ValueError("ACCESS_TOKEN_TTL_MINUTES must be between 1 and 1440")
        return v

    @field_validator("auth_max_failed_logins")
    @classmethod
    def _valid_auth_failures(cls, v: int) -> int:
        if not 0 <= v <= 100:
            raise ValueError("AUTH_MAX_FAILED_LOGINS must be between 0 and 100")
        return v

    @field_validator("auth_lockout_window_seconds")
    @classmethod
    def _valid_auth_window(cls, v: int) -> int:
        if not 60 <= v <= 86400:
            raise ValueError("AUTH_LOCKOUT_WINDOW_SECONDS must be between 60 and 86400")
        return v

    @field_validator("auth_max_requests_per_minute")
    @classmethod
    def _valid_auth_rpm(cls, v: int) -> int:
        if not 0 <= v <= 10000:
            raise ValueError("AUTH_MAX_REQUESTS_PER_MINUTE must be between 0 and 10000")
        return v

    @field_validator("trusted_proxy_count")
    @classmethod
    def _valid_proxy_count(cls, v: int) -> int:
        if not 0 <= v <= 5:
            raise ValueError("TRUSTED_PROXY_COUNT must be between 0 and 5")
        return v

    @field_validator("max_request_bytes")
    @classmethod
    def _valid_max_bytes(cls, v: int) -> int:
        if not 1024 <= v <= 64 * 1024 * 1024:
            raise ValueError("MAX_REQUEST_BYTES must be between 1024 and 67108864")
        return v

    @field_validator("llm_timeout_seconds")
    @classmethod
    def _valid_llm_timeout(cls, v: float) -> float:
        if not 1 <= v <= 300:
            raise ValueError("LLM_TIMEOUT_SECONDS must be between 1 and 300")
        return v

    @field_validator("intent_min_confidence")
    @classmethod
    def _valid_intent_conf(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("INTENT_MIN_CONFIDENCE must be between 0 and 1")
        return v

    @field_validator("llm_max_repairs")
    @classmethod
    def _valid_llm_repairs(cls, v: int) -> int:
        if not 0 <= v <= 3:
            raise ValueError("LLM_MAX_REPAIRS must be between 0 and 3")
        return v

    @field_validator("llm_max_retries")
    @classmethod
    def _valid_llm_retries(cls, v: int) -> int:
        if not 0 <= v <= 5:
            raise ValueError("LLM_MAX_RETRIES must be between 0 and 5")
        return v

    @field_validator("llm_max_input_chars", "llm_max_output_tokens")
    @classmethod
    def _positive_llm_limit(cls, v: int) -> int:
        if v < 1:
            raise ValueError("LLM limits must be positive")
        return v

    @field_validator("agent_run_max_steps", "agent_run_max_llm_calls")
    @classmethod
    def _valid_run_budget(cls, v: int) -> int:
        if not 1 <= v <= 50:
            raise ValueError("AGENT_RUN_MAX_STEPS / AGENT_RUN_MAX_LLM_CALLS must be between 1 and 50")
        return v

    @field_validator("plan_max_steps")
    @classmethod
    def _valid_plan_size(cls, v: int) -> int:
        if not 1 <= v <= 20:
            raise ValueError("PLAN_MAX_STEPS must be between 1 and 20")
        return v

    @field_validator("workflow_max_steps")
    @classmethod
    def _valid_workflow_size(cls, v: int) -> int:
        if not 1 <= v <= 20:
            raise ValueError("WORKFLOW_MAX_STEPS must be between 1 and 20")
        return v

    @field_validator("workflow_max_definitions")
    @classmethod
    def _valid_workflow_definitions(cls, v: int) -> int:
        if not 1 <= v <= 1000:
            raise ValueError("WORKFLOW_MAX_DEFINITIONS must be between 1 and 1000")
        return v

    @field_validator("workflow_max_active_runs")
    @classmethod
    def _valid_workflow_active_runs(cls, v: int) -> int:
        if not 1 <= v <= 200:
            raise ValueError("WORKFLOW_MAX_ACTIVE_RUNS must be between 1 and 200")
        return v

    @field_validator("workflow_max_event_fanout")
    @classmethod
    def _valid_workflow_fanout(cls, v: int) -> int:
        if not 1 <= v <= 50:
            raise ValueError("WORKFLOW_MAX_EVENT_FANOUT must be between 1 and 50")
        return v

    @field_validator("workflow_max_schedules", "workflow_tick_max_schedules")
    @classmethod
    def _valid_workflow_schedules(cls, v: int) -> int:
        if not 1 <= v <= 200:
            raise ValueError("WORKFLOW schedule limits must be between 1 and 200")
        return v

    @field_validator("workflow_tick_max_runs")
    @classmethod
    def _valid_workflow_tick_runs(cls, v: int) -> int:
        if not 1 <= v <= 100:
            raise ValueError("WORKFLOW_TICK_MAX_RUNS must be between 1 and 100")
        return v

    @field_validator("memory_max_items")
    @classmethod
    def _valid_memory_items(cls, v: int) -> int:
        if not 1 <= v <= 100000:
            raise ValueError("MEMORY_MAX_ITEMS must be between 1 and 100000")
        return v

    @field_validator("memory_max_document_chars")
    @classmethod
    def _valid_doc_chars(cls, v: int) -> int:
        if not 1000 <= v <= 2000000:
            raise ValueError("MEMORY_MAX_DOCUMENT_CHARS must be between 1000 and 2000000")
        return v

    @field_validator("memory_max_chunks_per_document")
    @classmethod
    def _valid_doc_chunks(cls, v: int) -> int:
        if not 1 <= v <= 500:
            raise ValueError("MEMORY_MAX_CHUNKS_PER_DOCUMENT must be between 1 and 500")
        return v

    @field_validator("memory_retrieval_max_chars")
    @classmethod
    def _valid_retrieval_chars(cls, v: int) -> int:
        if not 500 <= v <= 100000:
            raise ValueError("MEMORY_RETRIEVAL_MAX_CHARS must be between 500 and 100000")
        return v

    @field_validator("memory_prompt_max_chars")
    @classmethod
    def _valid_prompt_chars(cls, v: int) -> int:
        if not 200 <= v <= 20000:
            raise ValueError("MEMORY_PROMPT_MAX_CHARS must be between 200 and 20000")
        return v

    @field_validator("memory_prompt_max_hits")
    @classmethod
    def _valid_prompt_hits(cls, v: int) -> int:
        if not 1 <= v <= 10:
            raise ValueError("MEMORY_PROMPT_MAX_HITS must be between 1 and 10")
        return v

    @field_validator("memory_chunk_chars")
    @classmethod
    def _valid_chunk_chars(cls, v: int) -> int:
        if not 200 <= v <= 4000:
            raise ValueError("MEMORY_CHUNK_CHARS must be between 200 and 4000")
        return v

    @field_validator("memory_max_preferences_per_user")
    @classmethod
    def _valid_memory_prefs(cls, v: int) -> int:
        if not 1 <= v <= 500:
            raise ValueError("MEMORY_MAX_PREFERENCES_PER_USER must be between 1 and 500")
        return v

    @field_validator("agent_run_max_tool_calls")
    @classmethod
    def _valid_run_tool_budget(cls, v: int) -> int:
        if not 0 <= v <= 25:
            raise ValueError("AGENT_RUN_MAX_TOOL_CALLS must be between 0 and 25")
        return v

    @field_validator("agent_run_timeout_seconds")
    @classmethod
    def _valid_run_timeout(cls, v: int) -> int:
        if not 5 <= v <= 3600:
            raise ValueError("AGENT_RUN_TIMEOUT_SECONDS must be between 5 and 3600")
        return v

    @field_validator("agent_run_approval_wait_seconds")
    @classmethod
    def _valid_run_approval_wait(cls, v: int) -> int:
        if not 60 <= v <= 604800:
            raise ValueError("AGENT_RUN_APPROVAL_WAIT_SECONDS must be between 60 and 604800")
        return v

    @field_validator("log_level")
    @classmethod
    def _valid_level(cls, v: str) -> str:
        v = v.upper()
        if v not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("Invalid LOG_LEVEL")
        return v

    @field_validator("database_url")
    @classmethod
    def _normalize_db_url(cls, v: str) -> str:
        # Some hosts hand out the legacy "postgres://" scheme.
        if v.startswith("postgres://"):
            return "postgresql://" + v[len("postgres://"):]
        return v

    @model_validator(mode="after")
    def _aceden_guards(self) -> "Settings":
        has_url = bool(self.aceden_base_url)
        has_key = bool(self.aceden_api_key and self.aceden_api_key.get_secret_value().strip())
        if has_url != has_key:
            raise ValueError("ACEDEN_BASE_URL and ACEDEN_API_KEY must be set together")
        if has_url and self.app_env == "production" and not self.aceden_base_url.startswith("https://"):
            raise ValueError("ACEDEN_BASE_URL must use https in production")
        return self

    @model_validator(mode="after")
    def _llm_guards(self) -> "Settings":
        if self.llm_provider == "openai_compatible":
            key = self.llm_api_key.get_secret_value().strip() if self.llm_api_key else ""
            if not self.llm_base_url or not key:
                raise ValueError("LLM_BASE_URL and LLM_API_KEY are required for LLM_PROVIDER=openai_compatible")
            if self.app_env == "production" and not self.llm_base_url.startswith("https://"):
                raise ValueError("LLM_BASE_URL must use https in production")
        return self

    @model_validator(mode="after")
    def _production_guards(self) -> "Settings":
        if self.app_env == "production":
            if self.app_secret_key == _INSECURE_DEFAULT or len(self.app_secret_key) < 32:
                raise ValueError("APP_SECRET_KEY must be set (32+ chars) in production")
            if any(len(k) < 32 for k in self.previous_secret_keys):
                raise ValueError("APP_SECRET_KEY_PREVIOUS entries must be 32+ chars")
            if self.database_url.startswith("sqlite"):
                raise ValueError("SQLite is not allowed in production")
            if self.llm_provider == "fake":
                raise ValueError("LLM_PROVIDER=fake is not allowed in production")
            if "*" in self.cors_origins:
                raise ValueError("ALLOWED_ORIGINS must list explicit origins in production (no *)")
            if self.allow_private_connector_hosts:
                raise ValueError("ALLOW_PRIVATE_CONNECTOR_HOSTS cannot be enabled in production")
            if self.connector_max_calls_per_minute == 0:
                raise ValueError("CONNECTOR_MAX_CALLS_PER_MINUTE=0 (unlimited) is not allowed in production")
            if self.auth_max_failed_logins == 0 or self.auth_max_requests_per_minute == 0:
                raise ValueError("Authentication throttling cannot be disabled in production")
        return self

    @property
    def aceden_configured(self) -> bool:
        return bool(self.aceden_base_url)

    def __repr_args__(self):                       # 14.4: repr/str of Settings (logs, tracebacks, debuggers) never shows the root secrets
        for name, value in super().__repr_args__():
            yield name, ("***" if name in ("app_secret_key", "app_secret_key_previous") and value else value)

    @property
    def previous_secret_keys(self) -> List[str]:
        return [k.strip() for k in self.app_secret_key_previous.split(",") if k.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def cors_origins(self) -> List[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
