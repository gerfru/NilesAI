"""Tests for memory store and conversation history."""

import json
from unittest.mock import AsyncMock

import pytest

from niles.memory.history import ConversationHistory
from niles.memory.store import MemoryStore


class TestMemoryStore:
    @pytest.fixture
    def pool(self):
        return AsyncMock()

    @pytest.fixture
    def store(self, pool):
        return MemoryStore(pool)

    async def test_initialize_creates_table_and_index(self, store, pool):
        await store.initialize()
        assert pool.execute.call_count == 2
        calls = [c[0][0] for c in pool.execute.call_args_list]
        assert "CREATE TABLE IF NOT EXISTS memory" in calls[0]
        assert "CREATE INDEX IF NOT EXISTS idx_memory_updated" in calls[1]

    async def test_get_returns_value(self, store, pool):
        pool.fetchrow.return_value = {"value": json.dumps("hello")}
        result = await store.get("test_key")
        assert result == "hello"
        pool.fetchrow.assert_called_once()

    async def test_get_returns_none_for_missing(self, store, pool):
        pool.fetchrow.return_value = None
        result = await store.get("missing")
        assert result is None

    async def test_set_calls_upsert(self, store, pool):
        await store.set("key1", "value1")
        pool.execute.assert_called_once()
        sql = pool.execute.call_args[0][0]
        assert "ON CONFLICT" in sql

    async def test_delete_returns_true(self, store, pool):
        pool.execute.return_value = "DELETE 1"
        result = await store.delete("key1")
        assert result is True

    async def test_delete_returns_false_for_missing(self, store, pool):
        pool.execute.return_value = "DELETE 0"
        result = await store.delete("missing")
        assert result is False

    async def test_search_by_prefix(self, store, pool):
        pool.fetch.return_value = [
            {"key": "todo_1", "value": json.dumps("Buy milk")},
            {"key": "todo_2", "value": json.dumps("Call dentist")},
        ]
        result = await store.search("todo")
        assert len(result) == 2
        assert result[0]["key"] == "todo_1"
        assert result[0]["value"] == "Buy milk"
        # Verify prefix + "%" is passed to the query
        call_args = pool.fetch.call_args[0]
        assert call_args[1] == "todo%"

    async def test_get_handles_corrupted_data(self, store, pool):
        pool.fetchrow.return_value = {"value": "not-valid-json{"}
        result = await store.get("broken")
        assert result is None

    async def test_list_all(self, store, pool):
        pool.fetch.return_value = [
            {"key": "k1", "value": json.dumps("v1")},
            {"key": "k2", "value": json.dumps({"nested": True})},
        ]
        result = await store.list_all()
        assert len(result) == 2
        assert result[1]["value"] == {"nested": True}


class TestConversationHistory:
    @pytest.fixture
    def pool(self):
        return AsyncMock()

    @pytest.fixture
    def history(self, pool):
        return ConversationHistory(pool)

    async def test_initialize_creates_table_and_index(self, history, pool):
        await history.initialize()
        assert pool.execute.call_count == 2
        calls = [c[0][0] for c in pool.execute.call_args_list]
        assert "CREATE TABLE IF NOT EXISTS conversations" in calls[0]
        assert "CREATE INDEX IF NOT EXISTS" in calls[1]

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
        assert result[0]["timestamp"] == "01.01. 10:00"
        assert result[1]["timestamp"] == "01.01. 10:01"

    async def test_get_recent_empty(self, history, pool):
        pool.fetch.return_value = []
        result = await history.get_recent("new_chat")
        assert result == []

    async def test_clear(self, history, pool):
        pool.execute.return_value = "DELETE 5"
        count = await history.clear("user123")
        assert count == 5
