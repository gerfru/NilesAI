"""Unit tests for the data-access stores (ContactStore, EventStore)."""

from unittest.mock import AsyncMock

from niles.contact_store import ContactStore
from niles.event_store import EventStore


class TestContactStore:
    async def test_find_fails_closed_without_user_id(self):
        pool = AsyncMock()
        store = ContactStore(pool)
        result = await store.find_contact_row("Anna", user_id=None)
        assert result is None
        pool.fetchrow.assert_not_called()  # data layer never queries unscoped

    async def test_find_scopes_query_to_user(self):
        pool = AsyncMock()
        pool.fetchrow.return_value = None
        store = ContactStore(pool)
        await store.find_contact_row("Anna", user_id=42)
        assert 42 in pool.fetchrow.call_args.args

    async def test_count_and_last_sync_scoped(self):
        pool = AsyncMock()
        pool.fetchrow.return_value = {"cnt": 3, "last_sync": None}
        store = ContactStore(pool)
        out = await store.count_and_last_sync(user_id=7)
        assert out == {"cnt": 3, "last_sync": None}
        assert 7 in pool.fetchrow.call_args.args


class TestEventStore:
    async def test_resolve_source_id_returns_id(self):
        pool = AsyncMock()
        pool.fetchrow.return_value = {"id": 5}
        store = EventStore(pool)
        assert await store.resolve_source_id("Geburtstage", user_id=1) == 5

    async def test_resolve_source_id_none_when_missing(self):
        pool = AsyncMock()
        pool.fetchrow.return_value = None
        store = EventStore(pool)
        assert await store.resolve_source_id("Nope", user_id=1) is None

    async def test_search_passes_filters(self):
        pool = AsyncMock()
        pool.fetch.return_value = []
        store = EventStore(pool)
        await store.search("meeting", None, None, None, 9)
        args = pool.fetch.call_args.args
        assert "meeting" in args
        assert 9 in args
