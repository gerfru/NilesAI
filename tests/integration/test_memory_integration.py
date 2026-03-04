"""Integration tests for MemoryStore (PostgreSQL)."""

import pytest

from niles.memory.store import MemoryStore

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]


class TestMemorySet:
    async def test_set_and_get_string(self, pool_in_tx):
        store = MemoryStore(pool_in_tx)
        await store.set("test_key", "test_value")
        result = await store.get("test_key")
        assert result == "test_value"

    async def test_set_and_get_dict(self, pool_in_tx):
        store = MemoryStore(pool_in_tx)
        data = {"name": "Max", "age": 30}
        await store.set("person", data)
        result = await store.get("person")
        assert result == data

    async def test_upsert_overwrites(self, pool_in_tx):
        store = MemoryStore(pool_in_tx)
        await store.set("key1", "old")
        await store.set("key1", "new")
        result = await store.get("key1")
        assert result == "new"


class TestMemoryGet:
    async def test_missing_key_returns_none(self, pool_in_tx):
        store = MemoryStore(pool_in_tx)
        result = await store.get("nonexistent_key_xyz")
        assert result is None


class TestMemoryDelete:
    async def test_delete_existing(self, pool_in_tx):
        store = MemoryStore(pool_in_tx)
        await store.set("to_delete", "bye")
        assert await store.delete("to_delete") is True
        assert await store.get("to_delete") is None

    async def test_delete_nonexistent(self, pool_in_tx):
        store = MemoryStore(pool_in_tx)
        assert await store.delete("no_such_key") is False


class TestMemorySearch:
    async def test_search_by_prefix(self, pool_in_tx):
        store = MemoryStore(pool_in_tx)
        await store.set("integ_a", "value_a")
        await store.set("integ_b", "value_b")
        await store.set("other_c", "value_c")
        results = await store.search("integ")
        assert len(results) >= 2
        keys = {r["key"] for r in results}
        assert "integ_a" in keys
        assert "integ_b" in keys


class TestMemoryListAll:
    async def test_list_all(self, pool_in_tx):
        store = MemoryStore(pool_in_tx)
        await store.set("list_test_1", "v1")
        await store.set("list_test_2", "v2")
        results = await store.list_all()
        assert len(results) >= 2
