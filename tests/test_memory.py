"""Tests for memory store and conversation history."""

import json
from unittest.mock import AsyncMock

import pytest

from niles.memory.history import ConversationHistory
from niles.memory.store import MemoryStore

_UID = 1  # default test user_id


class TestMemoryStore:
    @pytest.fixture
    def pool(self):
        return AsyncMock()

    @pytest.fixture
    def store(self, pool):
        return MemoryStore(pool)

    async def test_get_returns_value(self, store, pool):
        pool.fetchrow.return_value = {"value": json.dumps("hello")}
        result = await store.get(_UID, "test_key")
        assert result == "hello"
        pool.fetchrow.assert_called_once()

    async def test_get_returns_none_for_missing(self, store, pool):
        pool.fetchrow.return_value = None
        result = await store.get(_UID, "missing")
        assert result is None

    async def test_set_calls_upsert(self, store, pool):
        await store.set(_UID, "key1", "value1")
        pool.execute.assert_called_once()
        sql = pool.execute.call_args[0][0]
        assert "ON CONFLICT" in sql

    async def test_delete_returns_true(self, store, pool):
        pool.execute.return_value = "DELETE 1"
        result = await store.delete(_UID, "key1")
        assert result is True

    async def test_delete_returns_false_for_missing(self, store, pool):
        pool.execute.return_value = "DELETE 0"
        result = await store.delete(_UID, "missing")
        assert result is False

    async def test_search_by_prefix(self, store, pool):
        pool.fetch.return_value = [
            {"key": "todo_1", "value": json.dumps("Buy milk")},
            {"key": "todo_2", "value": json.dumps("Call dentist")},
        ]
        result = await store.search(_UID, "todo")
        assert len(result) == 2
        assert result[0]["key"] == "todo_1"
        assert result[0]["value"] == "Buy milk"
        # Verify user_id and prefix+"%" are passed to the query
        call_args = pool.fetch.call_args[0]
        assert call_args[1] == _UID
        assert call_args[2] == "todo%"

    async def test_get_handles_corrupted_data(self, store, pool):
        pool.fetchrow.return_value = {"value": "not-valid-json{"}
        result = await store.get(_UID, "broken")
        assert result is None

    async def test_list_all(self, store, pool):
        pool.fetch.return_value = [
            {"key": "k1", "value": json.dumps("v1")},
            {"key": "k2", "value": json.dumps({"nested": True})},
        ]
        result = await store.list_all(_UID)
        assert len(result) == 2
        assert result[1]["value"] == {"nested": True}


class TestMemoryStoreCrossUser:
    """Verify that user_id is always passed to SQL queries (isolation)."""

    @pytest.fixture
    def pool(self):
        return AsyncMock()

    @pytest.fixture
    def store(self, pool):
        return MemoryStore(pool)

    async def test_get_passes_user_id_to_query(self, store, pool):
        pool.fetchrow.return_value = None
        await store.get(42, "key")
        args = pool.fetchrow.call_args[0]
        assert args[1] == 42  # user_id
        assert args[2] == "key"

    async def test_set_passes_user_id_to_query(self, store, pool):
        await store.set(42, "key", "val")
        args = pool.execute.call_args[0]
        assert args[1] == 42  # user_id
        assert args[2] == "key"

    async def test_delete_passes_user_id_to_query(self, store, pool):
        pool.execute.return_value = "DELETE 0"
        await store.delete(42, "key")
        args = pool.execute.call_args[0]
        assert args[1] == 42
        assert args[2] == "key"

    async def test_list_all_passes_user_id_to_query(self, store, pool):
        pool.fetch.return_value = []
        await store.list_all(42)
        args = pool.fetch.call_args[0]
        assert args[1] == 42  # user_id


class TestConversationHistory:
    @pytest.fixture
    def pool(self):
        return AsyncMock()

    @pytest.fixture
    def history(self, pool):
        return ConversationHistory(pool)

    async def test_add_message(self, history, pool):
        await history.add_message("user123", "user", "Hello")
        pool.execute.assert_called_once()
        args = pool.execute.call_args[0]
        assert "user123" in args
        assert "user" in args
        assert "Hello" in args

    async def test_get_recent_returns_chronological(self, history, pool):
        # DB returns newest first (DESC), get_recent should reverse
        from datetime import datetime, timezone

        ts1 = datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        ts2 = datetime(2025, 1, 1, 10, 1, 0, tzinfo=timezone.utc)
        pool.fetch.return_value = [
            {"role": "assistant", "content": "Hi!", "created_at": ts2},
            {"role": "user", "content": "Hello", "created_at": ts1},
        ]
        result = await history.get_recent("user123", limit=10)
        assert len(result) == 2
        assert result[0]["role"] == "user"
        assert result[1]["role"] == "assistant"
        assert result[0]["timestamp"] == "2025-01-01T10:00:00+00:00"
        assert result[1]["timestamp"] == "2025-01-01T10:01:00+00:00"

    async def test_get_recent_empty(self, history, pool):
        pool.fetch.return_value = []
        result = await history.get_recent("new_chat")
        assert result == []

    async def test_clear(self, history, pool):
        pool.execute.return_value = "DELETE 5"
        count = await history.clear("user123")
        assert count == 5
