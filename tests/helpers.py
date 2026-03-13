"""Shared test helpers."""

from niles.config import Settings


def make_test_settings(**overrides) -> Settings:
    """Create a Settings instance for testing with sensible defaults."""
    defaults = dict(
        _env_file=None,
        postgres_password="test",
        evolution_api_key="test",
        niles_api_key="test-key",
        session_secret="test-secret",
    )
    defaults.update(overrides)
    return Settings(**defaults)
