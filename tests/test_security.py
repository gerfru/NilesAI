"""Tests for API authentication."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from niles.config import Settings


class TestChatAuth:
    @pytest.fixture
    def mock_app(self):
        """Create a mock app with state."""
        app = MagicMock()
        app.state.agent = AsyncMock()
        app.state.settings = Settings(
            postgres_password="test",
            evolution_api_key="test",
            niles_api_key="test-niles-key",
        )
        return app

    async def test_require_api_key_rejects_missing(self, mock_app):
        from fastapi import HTTPException

        from niles.main import require_api_key

        request = MagicMock()
        request.app = mock_app

        with pytest.raises(HTTPException) as exc_info:
            await require_api_key(request, api_key=None)

        assert exc_info.value.status_code == 401

    async def test_require_api_key_rejects_wrong(self, mock_app):
        from fastapi import HTTPException

        from niles.main import require_api_key

        request = MagicMock()
        request.app = mock_app

        with pytest.raises(HTTPException) as exc_info:
            await require_api_key(request, api_key="wrong-key")

        assert exc_info.value.status_code == 401

    async def test_require_api_key_accepts_valid(self, mock_app):
        from niles.main import require_api_key

        request = MagicMock()
        request.app = mock_app

        result = await require_api_key(request, api_key="test-niles-key")

        assert result == "test-niles-key"


class TestNilesApiKeyDefault:
    def test_auto_generates_key_when_not_set(self, monkeypatch):
        monkeypatch.delenv("NILES_API_KEY", raising=False)
        settings = Settings(
            _env_file=None,
            postgres_password="test",
            evolution_api_key="test",
        )
        assert len(settings.niles_api_key) > 20

    def test_uses_env_key_when_set(self, monkeypatch):
        monkeypatch.setenv("NILES_API_KEY", "my-custom-key")
        settings = Settings(
            postgres_password="test",
            evolution_api_key="test",
        )
        assert settings.niles_api_key == "my-custom-key"
