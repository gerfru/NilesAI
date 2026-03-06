"""Tests for per-user Google OAuth token store."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from niles.google_token_store import GoogleTokenStore


class TestGoogleTokenStore:
    """Test GoogleTokenStore CRUD operations."""

    @pytest.fixture
    def store(self):
        pool = AsyncMock()
        return GoogleTokenStore(pool)

    async def test_get_tokens_found(self, store):
        store.pool.fetchrow.return_value = {
            "user_id": 5,
            "refresh_token": "rt-abc",
            "access_token": "at-xyz",
            "token_expiry": datetime(2026, 3, 5, tzinfo=timezone.utc),
            "scopes": "https://www.googleapis.com/auth/calendar",
        }
        result = await store.get_tokens(5)
        assert result is not None
        assert result["refresh_token"] == "rt-abc"
        assert result["access_token"] == "at-xyz"

    async def test_get_tokens_not_found(self, store):
        store.pool.fetchrow.return_value = None
        result = await store.get_tokens(999)
        assert result is None

    async def test_has_tokens_true(self, store):
        store.pool.fetchval.return_value = 1
        assert await store.has_tokens(5) is True

    async def test_has_tokens_false(self, store):
        store.pool.fetchval.return_value = None
        assert await store.has_tokens(999) is False

    async def test_upsert_tokens(self, store):
        await store.upsert_tokens(
            user_id=5,
            refresh_token="rt-new",
            access_token="at-new",
            token_expiry=datetime(2026, 3, 5, 12, 0, tzinfo=timezone.utc),
            scopes="calendar",
        )
        store.pool.execute.assert_called_once()
        sql = store.pool.execute.call_args[0][0]
        assert "INSERT INTO user_google_tokens" in sql
        assert "ON CONFLICT" in sql

    async def test_upsert_tokens_defaults(self, store):
        await store.upsert_tokens(user_id=5, refresh_token="rt")
        args = store.pool.execute.call_args[0]
        assert args[3] == ""  # access_token defaults to empty
        assert args[4] is None  # token_expiry defaults to None
        assert args[5] == ""  # scopes defaults to empty

    async def test_delete_tokens(self, store):
        await store.delete_tokens(5)
        store.pool.execute.assert_called_once()
        sql = store.pool.execute.call_args[0][0]
        assert "DELETE FROM user_google_tokens" in sql
