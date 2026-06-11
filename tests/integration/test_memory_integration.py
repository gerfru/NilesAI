"""Integration tests for MemoryStore (PostgreSQL)."""

import pytest

from niles.memory.store import MemoryStore

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]


class TestMemorySet:
    async def test_set_and_get_string(self, pool_in_tx, seed_user):
        store = MemoryStore(pool_in_tx)
        await store.set(seed_user, "test_key", "test_value")
        result = await store.get(seed_user, "test_key")
        assert result == "test_value"

    async def test_set_and_get_dict(self, pool_in_tx, seed_user):
        store = MemoryStore(pool_in_tx)
        data = {"name": "Max", "age": 30}
        await store.set(seed_user, "person", data)
        result = await store.get(seed_user, "person")
        assert result == data

    async def test_upsert_overwrites(self, pool_in_tx, seed_user):
        store = MemoryStore(pool_in_tx)
        await store.set(seed_user, "key1", "old")
        await store.set(seed_user, "key1", "new")
        result = await store.get(seed_user, "key1")
        assert result == "new"


class TestMemoryGet:
    async def test_missing_key_returns_none(self, pool_in_tx, seed_user):
        store = MemoryStore(pool_in_tx)
        result = await store.get(seed_user, "nonexistent_key_xyz")
        assert result is None


class TestMemoryDelete:
    async def test_delete_existing(self, pool_in_tx, seed_user):
        store = MemoryStore(pool_in_tx)
        await store.set(seed_user, "to_delete", "bye")
        assert await store.delete(seed_user, "to_delete") is True
        assert await store.get(seed_user, "to_delete") is None

    async def test_delete_nonexistent(self, pool_in_tx, seed_user):
        store = MemoryStore(pool_in_tx)
        assert await store.delete(seed_user, "no_such_key") is False


class TestMemorySearch:
    async def test_search_by_prefix(self, pool_in_tx, seed_user):
        store = MemoryStore(pool_in_tx)
        await store.set(seed_user, "integ_a", "value_a")
        await store.set(seed_user, "integ_b", "value_b")
        await store.set(seed_user, "other_c", "value_c")
        results = await store.search(seed_user, "integ")
        assert len(results) >= 2
        keys = {r["key"] for r in results}
        assert "integ_a" in keys
        assert "integ_b" in keys


class TestMemoryListAll:
    async def test_list_all(self, pool_in_tx, seed_user):
        store = MemoryStore(pool_in_tx)
        await store.set(seed_user, "list_test_1", "v1")
        await store.set(seed_user, "list_test_2", "v2")
        results = await store.list_all(seed_user)
        keys = {r["key"] for r in results}
        assert "list_test_1" in keys
        assert "list_test_2" in keys


class TestCrossUserIsolation:
    """Verify that memories are isolated between users."""

    async def test_same_key_different_users(self, pool_in_tx, db_conn):
        """Two users can store different values under the same key."""
        user1 = await db_conn.fetchval(
            "INSERT INTO users (email, display_name, auth_method, is_admin) "
            "VALUES ('mem_user1@test.com', 'MemUser1', 'password', false) RETURNING id"
        )
        user2 = await db_conn.fetchval(
            "INSERT INTO users (email, display_name, auth_method, is_admin) "
            "VALUES ('mem_user2@test.com', 'MemUser2', 'password', false) RETURNING id"
        )
        store = MemoryStore(pool_in_tx)

        await store.set(user1, "color", "red")
        await store.set(user2, "color", "blue")

        assert await store.get(user1, "color") == "red"
        assert await store.get(user2, "color") == "blue"

    async def test_delete_only_affects_own_user(self, pool_in_tx, db_conn):
        """Deleting a key for one user doesn't affect the other."""
        user1 = await db_conn.fetchval(
            "INSERT INTO users (email, display_name, auth_method, is_admin) "
            "VALUES ('mem_del1@test.com', 'MemDel1', 'password', false) RETURNING id"
        )
        user2 = await db_conn.fetchval(
            "INSERT INTO users (email, display_name, auth_method, is_admin) "
            "VALUES ('mem_del2@test.com', 'MemDel2', 'password', false) RETURNING id"
        )
        store = MemoryStore(pool_in_tx)

        await store.set(user1, "temp", "val1")
        await store.set(user2, "temp", "val2")

        assert await store.delete(user1, "temp") is True
        assert await store.get(user1, "temp") is None
        assert await store.get(user2, "temp") == "val2"

    async def test_list_all_scoped_to_user(self, pool_in_tx, db_conn):
        """list_all only returns the current user's entries."""
        user1 = await db_conn.fetchval(
            "INSERT INTO users (email, display_name, auth_method, is_admin) "
            "VALUES ('mem_list1@test.com', 'MemList1', 'password', false) RETURNING id"
        )
        user2 = await db_conn.fetchval(
            "INSERT INTO users (email, display_name, auth_method, is_admin) "
            "VALUES ('mem_list2@test.com', 'MemList2', 'password', false) RETURNING id"
        )
        store = MemoryStore(pool_in_tx)

        await store.set(user1, "u1_key", "u1_val")
        await store.set(user2, "u2_key", "u2_val")

        u1_results = await store.list_all(user1)
        u1_keys = {r["key"] for r in u1_results}
        assert "u1_key" in u1_keys
        assert "u2_key" not in u1_keys
