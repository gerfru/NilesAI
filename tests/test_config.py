"""Tests for niles.config."""

from niles.config import Settings


def test_settings_defaults():
    """Settings loads with correct defaults."""
    settings = Settings(
        postgres_password="test",
        evolution_api_key="test",
    )
    assert settings.llm_base_url == "http://host.docker.internal:1234/v1"
    assert settings.postgres_host == "evolution_postgres"
    assert settings.postgres_port == 5432
    assert settings.postgres_db == "evolution_db"
    assert settings.evolution_instance == "niles-whatsapp"


def test_settings_from_env(monkeypatch):
    """Settings reads from environment variables."""
    monkeypatch.setenv("POSTGRES_PASSWORD", "my-secret")
    monkeypatch.setenv("EVOLUTION_API_KEY", "my-key")
    monkeypatch.setenv("LLM_BASE_URL", "http://custom:9999/v1")

    settings = Settings()
    assert settings.postgres_password == "my-secret"
    assert settings.evolution_api_key == "my-key"
    assert settings.llm_base_url == "http://custom:9999/v1"
