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

    with pytest.raises(ValidationError, match="evolution_api_key"):
        Settings(_env_file=None)
