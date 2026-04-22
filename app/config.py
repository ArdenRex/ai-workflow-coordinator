import logging
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str = Field(
        ...,
        description="PostgreSQL connection string (required).",
    )

    # ── Groq ──────────────────────────────────────────────────────────────────
    groq_api_key: SecretStr = Field(
        ...,
        description="Groq API key (required). Get one free at https://console.groq.com",
    )

    # ── Slack ─────────────────────────────────────────────────────────────────
    slack_bot_token: SecretStr = Field(
        ...,
        description="Slack Bot User OAuth Token (required).",
    )
    slack_signing_secret: SecretStr = Field(
        ...,
        description="Slack signing secret used to verify request signatures (required).",
    )
    slack_channel_id: str = Field(
        default="",
        description="Optional: restrict bot to one channel ID.",
    )

    # ── App ───────────────────────────────────────────────────────────────────
    app_env: Literal["development", "staging", "production"] = Field(
        default="development",
        description="Deployment environment.",
    )
    app_secret_key: SecretStr = Field(
        ...,
        description="Secret key for signing/encryption (required).",
    )

    # ── NEW: JWT settings ─────────────────────────────────────────────────────
    # Used to sign access tokens (login sessions)
    jwt_algorithm: str = Field(
        default="HS256",
        description="JWT signing algorithm.",
    )
    # Short-lived access token — 30 minutes
    jwt_access_token_expire_minutes: int = Field(
        default=30,
        description="Access token expiry in minutes.",
    )
    # Long-lived token for Remember Me — 30 days
    jwt_refresh_token_expire_days: int = Field(
        default=30,
        description="Refresh token expiry in days (used for Remember Me).",
    )

    # ── Validators (all unchanged) ────────────────────────────────────────────
    @field_validator("database_url", mode="before")
    @classmethod
    def _validate_database_url(cls, v: str) -> str:
        if not isinstance(v, str) or not v.strip():
            raise ValueError("database_url must not be empty.")
        if not (v.startswith("postgresql://") or v.startswith("postgres://")):
            raise ValueError(
                "database_url must start with postgresql:// or postgres://. "
                f"Got: {v[:30]!r}"
            )
        return v.strip()

    @field_validator("groq_api_key", mode="before")
    @classmethod
    def _reject_placeholder_groq(cls, v: str) -> str:
        if isinstance(v, str) and v.strip() in ("", "gsk-changeme"):
            raise ValueError(
                "groq_api_key must be set to a real value. "
                "Get one free at https://console.groq.com"
            )
        return v

    @field_validator("slack_bot_token", mode="before")
    @classmethod
    def _reject_placeholder_slack_token(cls, v: str) -> str:
        if isinstance(v, str) and v.strip() in ("", "xoxb-changeme"):
            raise ValueError(
                "slack_bot_token must be set to a real value. "
                "Update your .env file."
            )
        return v

    @field_validator("slack_signing_secret", mode="before")
    @classmethod
    def _reject_placeholder_signing_secret(cls, v: str) -> str:
        if isinstance(v, str) and v.strip() in ("", "changeme"):
            raise ValueError(
                "slack_signing_secret must be set to a real value. "
                "Update your .env file."
            )
        return v

    @field_validator("app_secret_key", mode="before")
    @classmethod
    def _reject_placeholder_secret_key(cls, v: str) -> str:
        if isinstance(v, str) and v.strip() in ("", "changeme"):
            raise ValueError(
                "app_secret_key must be set to a real value. "
                "Update your .env file."
            )
        return v


def _safe_db_host(url: str) -> str:
    """Extract host from DB URL string for logging — never exposes credentials."""
    try:
        without_scheme = url.split("://", 1)[-1]
        if "@" in without_scheme:
            without_scheme = without_scheme.split("@", 1)[-1]
        return without_scheme.split("/")[0] or "(unknown)"
    except Exception:
        return "(unknown)"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    logger.info(
        "Config loaded | env=%s | db_host=%s | slack_channel=%s",
        settings.app_env,
        _safe_db_host(settings.database_url),
        settings.slack_channel_id or "(all channels)",
    )
    return settings
