"""Shared pytest fixtures and helpers."""

import pytest
import structlog


@pytest.fixture(autouse=True)
def _set_test_env(monkeypatch):
    """Set required environment variables for tests."""
    monkeypatch.setenv("EVOLUTION_POSTGRES_PASSWORD", "test-password")
    monkeypatch.setenv("EVOLUTION_API_KEY", "test-api-key")
    monkeypatch.setenv("NILES_API_KEY", "test-niles-key")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    # Tests run without encryption (opt-in via CREDENTIAL_ENCRYPTION_OPTIONAL)
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", "")
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_OPTIONAL", "true")


@pytest.fixture(autouse=True)
def _reset_structlog():
    """Reset structlog to prevent test pollution."""
    structlog.reset_defaults()
    yield
    structlog.reset_defaults()
