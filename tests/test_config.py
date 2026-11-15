import pytest
from pydantic import ValidationError

from app.config import Settings


def test_defaults_are_development():
    s = Settings(_env_file=None)
    assert s.app_env in {"development", "test"}


def test_invalid_env_rejected():
    with pytest.raises(ValidationError):
        Settings(app_env="staging", _env_file=None)


def test_production_requires_strong_secret():
    with pytest.raises(ValidationError):
        Settings(app_env="production", database_url="postgresql://u:p@h/db", _env_file=None)


def test_production_rejects_sqlite():
    with pytest.raises(ValidationError):
        Settings(app_env="production", app_secret_key="x" * 40, _env_file=None)


def test_production_valid():
    s = Settings(app_env="production", app_secret_key="x" * 40,
                 database_url="postgres://u:p@h/db", llm_provider="openai", _env_file=None)
    assert s.database_url.startswith("postgresql://")
    assert s.is_production


def test_cors_parsing():
    s = Settings(allowed_origins=" https://a.com, https://b.com ,", _env_file=None)
    assert s.cors_origins == ["https://a.com", "https://b.com"]


def test_token_ttl_bounds():
    import pytest
    from app.config import Settings
    for bad in (0, 1441):
        with pytest.raises(ValueError):
            Settings(app_env="test", database_url="sqlite:///:memory:", access_token_ttl_minutes=bad, _env_file=None)
