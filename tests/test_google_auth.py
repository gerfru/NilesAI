"""Tests for GoogleCalendarAuth (Bearer token with automatic refresh)."""

import time
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from niles.sync.google_auth import GoogleCalendarAuth


@pytest.fixture
def auth():
    return GoogleCalendarAuth(
        refresh_token="test-refresh-token",
        client_id="test-client-id",
        client_secret="test-client-secret",
    )


class TestGoogleCalendarAuth:
    def test_sync_auth_flow_raises(self, auth):
        with pytest.raises(NotImplementedError):
            gen = auth.sync_auth_flow(MagicMock())
            next(gen)

    async def test_async_auth_flow_refreshes_token(self, auth):
        """First call should trigger a token refresh."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "access_token": "fresh-access-token",
            "expires_in": 3600,
        }

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        auth._client = mock_client

        request = MagicMock()
        request.headers = {}

        async for _ in auth.async_auth_flow(request):
            pass

        # Verify Bearer token was set
        assert request.headers["Authorization"] == "Bearer fresh-access-token"

        # Verify refresh was called with correct params
        call_kwargs = mock_client.post.call_args[1]
        assert call_kwargs["data"]["refresh_token"] == "test-refresh-token"
        assert call_kwargs["data"]["client_id"] == "test-client-id"
        assert call_kwargs["data"]["grant_type"] == "refresh_token"

    async def test_cached_token_not_refreshed(self, auth):
        """Second call should use cached token without refreshing."""
        auth._access_token = "cached-token"
        auth._expires_at = time.monotonic() + 3600

        mock_client = AsyncMock()
        auth._client = mock_client

        request = MagicMock()
        request.headers = {}

        async for _ in auth.async_auth_flow(request):
            pass

        # Should NOT have called post (no refresh needed)
        mock_client.post.assert_not_called()
        assert request.headers["Authorization"] == "Bearer cached-token"

    async def test_expired_token_triggers_refresh(self, auth):
        """Expired token should trigger a refresh."""
        auth._access_token = "old-token"
        auth._expires_at = time.monotonic() - 10

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "access_token": "new-token",
            "expires_in": 3600,
        }

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        auth._client = mock_client

        request = MagicMock()
        request.headers = {}

        async for _ in auth.async_auth_flow(request):
            pass

        mock_client.post.assert_called_once()
        assert request.headers["Authorization"] == "Bearer new-token"

    async def test_refresh_failure_raises(self, auth):
        """HTTP error during refresh should propagate."""
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.HTTPStatusError(
            "401",
            request=MagicMock(),
            response=MagicMock(status_code=401),
        )
        auth._client = mock_client

        request = MagicMock()
        request.headers = {}

        with pytest.raises(httpx.HTTPStatusError):
            async for _ in auth.async_auth_flow(request):
                pass
