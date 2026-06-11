"""Tests for WhatsAppSessionStore — per-user session CRUD."""

from unittest.mock import AsyncMock

import pytest

from niles.whatsapp_store import WhatsAppSessionStore

_SESSION = {
    "user_id": 1,
    "instance_name": "wa-user-1",
    "phone_number": "+491234567",
    "status": "open",
}


@pytest.fixture
def pool():
    return AsyncMock()


@pytest.fixture
def store(pool):
    return WhatsAppSessionStore(pool)


# ---- get_session ----


class TestGetSession:
    async def test_returns_dict_when_found(self, store, pool):
        pool.fetchrow.return_value = _SESSION
        result = await store.get_session(1)
        assert result == _SESSION

    async def test_returns_none_when_not_found(self, store, pool):
        pool.fetchrow.return_value = None
        result = await store.get_session(999)
        assert result is None


# ---- get_by_instance ----


class TestGetByInstance:
    async def test_returns_dict_when_found(self, store, pool):
        pool.fetchrow.return_value = _SESSION
        result = await store.get_by_instance("wa-user-1")
        assert result == _SESSION

    async def test_returns_none_when_not_found(self, store, pool):
        pool.fetchrow.return_value = None
        result = await store.get_by_instance("nonexistent")
        assert result is None


# ---- get_by_phone ----


class TestGetByPhone:
    async def test_returns_dict_when_found(self, store, pool):
        pool.fetchrow.return_value = _SESSION
        result = await store.get_by_phone("+491234567")
        assert result == _SESSION

    async def test_returns_none_when_not_found(self, store, pool):
        pool.fetchrow.return_value = None
        result = await store.get_by_phone("+490000000")
        assert result is None


# ---- upsert_session ----


class TestUpsertSession:
    async def test_calls_execute_with_correct_args(self, store, pool):
        await store.upsert_session(1, "wa-user-1", "open", phone_number="+491234567")
        pool.execute.assert_called_once()
        args = pool.execute.call_args[0]
        assert args[1] == 1  # user_id
        assert args[2] == "wa-user-1"  # instance_name
        assert args[3] == "+491234567"  # phone_number
        assert args[4] == "open"  # status

    async def test_phone_number_defaults_to_none(self, store, pool):
        await store.upsert_session(1, "wa-user-1", "open")
        args = pool.execute.call_args[0]
        assert args[3] is None  # phone_number


# ---- update_status ----


class TestUpdateStatus:
    async def test_with_phone_number(self, store, pool):
        await store.update_status(1, "connected", phone_number="+491234567")
        args = pool.execute.call_args[0]
        assert "phone_number" in args[0]
        assert args[1] == 1
        assert args[2] == "connected"
        assert args[3] == "+491234567"

    async def test_without_phone_number(self, store, pool):
        await store.update_status(1, "close")
        args = pool.execute.call_args[0]
        assert "phone_number" not in args[0]
        assert args[1] == 1
        assert args[2] == "close"


# ---- delete_session ----


class TestDeleteSession:
    async def test_calls_execute(self, store, pool):
        await store.delete_session(1)
        pool.execute.assert_called_once()
        args = pool.execute.call_args[0]
        assert args[1] == 1
