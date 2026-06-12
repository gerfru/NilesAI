"""Tests for niles.config."""

import pytest
from pydantic import ValidationError

from niles.config import Settings


def test_settings_defaults(monkeypatch):
    """Settings loads with correct defaults."""
    # Clear env vars that would override defaults (e.g. from a previous
    # test-integration.sh run or a sourced .env file)
    for var in (
        "POSTGRES_HOST",
        "POSTGRES_HOST_PORT",
        "POSTGRES_DB",
        "POSTGRES_USER",
        "LLM_BASE_URL",
        "EVOLUTION_INSTANCE",
    ):
        monkeypatch.delenv(var, raising=False)
    settings = Settings(
        _env_file=None,
        postgres_password="test",
        evolution_api_key="test",
    )
    assert settings.llm_base_url == "http://host.docker.internal:11434/v1"
    assert settings.postgres_host == "evolution_postgres"
    assert settings.postgres_port == 5432
    assert settings.postgres_db == "evolution_db"
    assert settings.evolution_instance == "niles-whatsapp"


def test_settings_from_env(monkeypatch):
    """Settings reads from environment variables."""
    monkeypatch.setenv("EVOLUTION_POSTGRES_PASSWORD", "my-secret")
    monkeypatch.setenv("EVOLUTION_API_KEY", "my-key")
    monkeypatch.setenv("LLM_BASE_URL", "http://custom:9999/v1")

    settings = Settings()
    assert settings.postgres_password == "my-secret"
    assert settings.evolution_api_key == "my-key"
    assert settings.llm_base_url == "http://custom:9999/v1"


def test_settings_missing_postgres_password(monkeypatch):
    """Settings raises ValidationError when EVOLUTION_POSTGRES_PASSWORD is missing."""
    monkeypatch.delenv("EVOLUTION_POSTGRES_PASSWORD", raising=False)
    monkeypatch.setenv("EVOLUTION_API_KEY", "test-key")

    with pytest.raises(ValidationError, match="EVOLUTION_POSTGRES_PASSWORD"):
        Settings(_env_file=None)


def test_settings_missing_api_key(monkeypatch):
    """Settings raises ValidationError when EVOLUTION_API_KEY is missing."""
    monkeypatch.setenv("EVOLUTION_POSTGRES_PASSWORD", "test-pw")
    monkeypatch.delenv("EVOLUTION_API_KEY", raising=False)

    with pytest.raises(ValidationError, match="EVOLUTION_API_KEY"):
        Settings(_env_file=None)


def test_requires_encryption_key_by_default(monkeypatch):
    """Without opt-out, CREDENTIAL_ENCRYPTION_KEY is required."""
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_OPTIONAL", "false")
    with pytest.raises(ValidationError, match="CREDENTIAL_ENCRYPTION_KEY"):
        Settings(
            _env_file=None,
            postgres_password="test",
            evolution_api_key="test",
            credential_encryption_key="",
            credential_encryption_optional=False,
        )


def test_debug_still_requires_encryption_key(monkeypatch):
    """LOG_LEVEL=DEBUG no longer bypasses encryption requirement."""
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_OPTIONAL", "false")
    with pytest.raises(ValidationError, match="CREDENTIAL_ENCRYPTION_KEY"):
        Settings(
            _env_file=None,
            postgres_password="test",
            evolution_api_key="test",
            log_level="DEBUG",
            credential_encryption_key="",
            credential_encryption_optional=False,
        )


def test_encryption_optional_allows_empty_key(monkeypatch):
    """CREDENTIAL_ENCRYPTION_OPTIONAL=true allows empty encryption key."""
    settings = Settings(
        _env_file=None,
        postgres_password="test",
        evolution_api_key="test",
        credential_encryption_optional=True,
        credential_encryption_key="",
    )
    assert settings.credential_encryption_key == ""
