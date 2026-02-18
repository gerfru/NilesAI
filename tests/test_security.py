"""Tests for API authentication and rate limiting."""

import time
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


class TestRateLimiting:
    def test_rate_limit_middleware_allows_normal_traffic(self):
        from niles.main import RateLimitMiddleware

        middleware = RateLimitMiddleware(app=MagicMock(), requests_per_minute=5)
        # Simulate 5 hits within window -- all should be under limit
        client_ip = "127.0.0.1"
        now = time.monotonic()
        middleware._hits[client_ip] = [now - i for i in range(4)]
        middleware._hits[client_ip].append(now)
        assert len(middleware._hits[client_ip]) <= 5

    def test_rate_limit_middleware_detects_excess(self):
        from niles.main import RateLimitMiddleware

        middleware = RateLimitMiddleware(app=MagicMock(), requests_per_minute=5)
        client_ip = "127.0.0.1"
        now = time.monotonic()
        # Fill with 6 hits (exceeds limit of 5)
        middleware._hits[client_ip] = [now - i for i in range(6)]
        assert len(middleware._hits[client_ip]) > 5

    def test_rate_limit_middleware_prunes_old_entries(self):
        from niles.main import RateLimitMiddleware

        middleware = RateLimitMiddleware(app=MagicMock(), requests_per_minute=5)
        client_ip = "127.0.0.1"
        now = time.monotonic()
        # Old entries (> 60s ago) should be pruned
        middleware._hits[client_ip] = [now - 120, now - 90, now]
        window = now - 60.0
        pruned = [t for t in middleware._hits[client_ip] if t > window]
        assert len(pruned) == 1
