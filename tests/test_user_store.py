"""Tests for UserStore — user CRUD, auto-promote, and GDPR hard delete."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from niles.user_store import UserStore


@pytest.fixture
def pool():
    pool = AsyncMock()
    # pool.acquire() → async context manager returning a mock connection
    conn = AsyncMock()
    acq_ctx = MagicMock()
    acq_ctx.__aenter__ = AsyncMock(return_value=conn)
    acq_ctx.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=acq_ctx)
    # conn.transaction() → sync call returning async context manager
    tx_ctx = MagicMock()
    tx_ctx.__aenter__ = AsyncMock()
    tx_ctx.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=tx_ctx)
    pool._conn = conn  # expose for assertions
    return pool


@pytest.fixture
def store(pool):
    return UserStore(pool)


# ---- get_by_email ----


class TestGetByEmail:
    async def test_returns_dict_when_found(self, store, pool):
        pool.fetchrow.return_value = {
            "id": 1,
            "email": "a@b.com",
            "display_name": "Alice",
            "avatar_url": None,
            "is_admin": False,
        }
        result = await store.get_by_email("a@b.com")
        assert result == {
            "id": 1,
            "email": "a@b.com",
            "display_name": "Alice",
            "avatar_url": None,
            "is_admin": False,
        }
        sql = pool.fetchrow.call_args[0][0]
        assert "is_active = TRUE" in sql

    async def test_returns_none_when_not_found(self, store, pool):
        pool.fetchrow.return_value = None
        result = await store.get_by_email("nobody@b.com")
        assert result is None


# ---- get_with_hash ----


class TestGetWithHash:
    async def test_includes_password_hash_and_auth_method(self, store, pool):
        pool.fetchrow.return_value = {
            "id": 1,
            "email": "a@b.com",
            "display_name": "Alice",
            "avatar_url": None,
            "password_hash": "$2b$12$hash",
            "auth_method": "password",
            "is_admin": True,
        }
        result = await store.get_with_hash("a@b.com")
        assert result["password_hash"] == "$2b$12$hash"
        assert result["auth_method"] == "password"


# ---- create_or_update ----


class TestCreateOrUpdate:
    async def test_first_user_becomes_admin(self, store, pool):
        pool.fetchval.return_value = 0  # no active users
        pool.fetchrow.return_value = {
            "id": 1,
            "email": "a@b.com",
            "display_name": "Alice",
            "avatar_url": None,
            "is_admin": True,
        }
        result = await store.create_or_update("a@b.com", "Alice")
        # is_first should be True → $4 = True
        args = pool.fetchrow.call_args[0]
        assert args[4] is True  # $4 = is_first
        assert result["is_admin"] is True

    async def test_second_user_not_admin(self, store, pool):
        pool.fetchval.return_value = 1  # one active user exists
        pool.fetchrow.return_value = {
            "id": 2,
            "email": "b@b.com",
            "display_name": "Bob",
            "avatar_url": None,
            "is_admin": False,
        }
        await store.create_or_update("b@b.com", "Bob")
        args = pool.fetchrow.call_args[0]
        assert args[4] is False  # $4 = is_first

    async def test_returns_none_for_deactivated_user(self, store, pool):
        pool.fetchval.return_value = 1
        pool.fetchrow.return_value = None  # ON CONFLICT + WHERE is_active = TRUE → no row
        result = await store.create_or_update("deactivated@b.com", "Gone")
        assert result is None


# ---- create_password_user ----


class TestCreatePasswordUser:
    async def test_first_user_is_admin(self, store, pool):
        pool.fetchval.return_value = 0
        pool.fetchrow.return_value = {
            "id": 1,
            "email": "a@b.com",
            "display_name": "Alice",
            "avatar_url": None,
            "is_admin": True,
        }
        result = await store.create_password_user("a@b.com", "Alice", "$2b$hash")
        args = pool.fetchrow.call_args[0]
        assert args[4] is True
        assert result["is_admin"] is True

    async def test_subsequent_user_not_admin(self, store, pool):
        pool.fetchval.return_value = 2
        pool.fetchrow.return_value = {
            "id": 3,
            "email": "c@b.com",
            "display_name": "Charlie",
            "avatar_url": None,
            "is_admin": False,
        }
        await store.create_password_user("c@b.com", "Charlie", "$2b$hash")
        args = pool.fetchrow.call_args[0]
        assert args[4] is False


# ---- get_by_id ----


class TestGetById:
    async def test_returns_dict_when_found(self, store, pool):
        pool.fetchrow.return_value = {
            "id": 1,
            "email": "a@b.com",
            "display_name": "Alice",
            "avatar_url": None,
            "is_admin": False,
        }
        result = await store.get_by_id(1)
        assert result["id"] == 1

    async def test_returns_none_when_not_found(self, store, pool):
        pool.fetchrow.return_value = None
        assert await store.get_by_id(999) is None


# ---- update_password ----


class TestUpdatePassword:
    async def test_returns_true_on_success(self, store, pool):
        pool.execute.return_value = "UPDATE 1"
        assert await store.update_password(1, "$2b$new") is True

    async def test_returns_false_on_no_match(self, store, pool):
        pool.execute.return_value = "UPDATE 0"
        assert await store.update_password(999, "$2b$new") is False


# ---- update_last_login ----


class TestUpdateLastLogin:
    async def test_executes_update(self, store, pool):
        await store.update_last_login(1)
        sql = pool.execute.call_args[0][0]
        assert "last_login" in sql


# ---- list_all ----


class TestListAll:
    async def test_returns_list_of_dicts(self, store, pool):
        pool.fetch.return_value = [
            {
                "id": 1,
                "email": "a@b.com",
                "display_name": "Alice",
                "auth_method": "google",
                "is_admin": True,
                "is_active": True,
                "created_at": None,
                "last_login": None,
            },
            {
                "id": 2,
                "email": "b@b.com",
                "display_name": "Bob",
                "auth_method": "password",
                "is_admin": False,
                "is_active": True,
                "created_at": None,
                "last_login": None,
            },
        ]
        result = await store.list_all()
        assert len(result) == 2
        assert result[0]["email"] == "a@b.com"

    async def test_passes_limit_and_offset(self, store, pool):
        pool.fetch.return_value = []
        await store.list_all(limit=10, offset=5)
        args = pool.fetch.call_args[0]
        assert args[1] == 10  # $1 = limit
        assert args[2] == 5  # $2 = offset


# ---- deactivate_user ----


class TestDeactivateUser:
    async def test_returns_true_on_success(self, store, pool):
        pool.execute.return_value = "UPDATE 1"
        assert await store.deactivate_user(1) is True
        sql = pool.execute.call_args[0][0]
        assert "is_active = FALSE" in sql

    async def test_returns_false_when_already_inactive(self, store, pool):
        pool.execute.return_value = "UPDATE 0"
        assert await store.deactivate_user(999) is False


# ---- hard_delete_user ----


class TestHardDeleteUser:
    async def test_erases_all_channels_in_transaction(self, store, pool):
        conn = pool._conn
        conn.execute.return_value = "DELETE 1"
        conn.fetchval.return_value = 1  # user exists
        conn.fetchrow.return_value = {"phone_number": "+43 660 12345"}
        result = await store.hard_delete_user(42)
        assert result is True

        # Flatten all executed SQL + bind params for assertions
        sqls = [c[0][0] for c in conn.execute.call_args_list]
        joined = "\n".join(sqls)
        params = [c[0][1:] for c in conn.execute.call_args_list]

        # Web + WhatsApp self-chat conversations (scoped to this user's phone)
        assert ("web-user-42",) in params
        assert ("wa-self-4366012345",) in params
        # Signal single-account history fully erased
        assert "signal-self-%" in joined
        assert "DELETE FROM signal_messages" in joined
        # FK tables + user row
        assert "whatsapp_sessions" in joined
        assert "vikunja_credentials" in joined
        assert "DELETE FROM users" in joined

    async def test_skips_wa_self_when_no_phone(self, store, pool):
        conn = pool._conn
        conn.execute.return_value = "DELETE 1"
        conn.fetchval.return_value = 1  # user exists
        conn.fetchrow.return_value = None  # no WhatsApp session
        await store.hard_delete_user(7)

        params = [c[0][1:] for c in conn.execute.call_args_list]
        assert not any(p and str(p[0]).startswith("wa-self-") for p in params)
        # Signal history is still erased regardless of WhatsApp
        joined = "\n".join(c[0][0] for c in conn.execute.call_args_list)
        assert "DELETE FROM signal_messages" in joined

    async def test_returns_false_when_user_not_found(self, store, pool):
        conn = pool._conn
        conn.fetchval.return_value = None  # user does not exist
        result = await store.hard_delete_user(999)
        assert result is False
        # Nothing must be deleted for an unknown user (esp. global Signal history)
        conn.execute.assert_not_called()


# ---- initialize (auto-promote) ----


class TestInitialize:
    async def test_auto_promotes_single_user(self, store, pool):
        # First call: admin_count = 0, second call: total = 1
        pool.fetchval.side_effect = [0, 1]
        pool.execute.return_value = "UPDATE 1"
        await store.initialize()
        sql = pool.execute.call_args[0][0]
        assert "is_admin = TRUE" in sql

    async def test_no_promote_when_admin_exists(self, store, pool):
        pool.fetchval.return_value = 1  # admin_count = 1
        await store.initialize()
        pool.execute.assert_not_called()

    async def test_no_promote_when_multiple_users(self, store, pool):
        pool.fetchval.side_effect = [0, 3]  # no admin, 3 users
        await store.initialize()
        pool.execute.assert_not_called()

    async def test_no_promote_when_no_users(self, store, pool):
        pool.fetchval.side_effect = [0, 0]  # no admin, 0 users
        await store.initialize()
        pool.execute.assert_not_called()


# ---- has_password_users ----


class TestHasPasswordUsers:
    async def test_returns_true_when_exists(self, store, pool):
        pool.fetchval.return_value = 1
        assert await store.has_password_users() is True

    async def test_returns_false_when_none(self, store, pool):
        pool.fetchval.return_value = 0
        assert await store.has_password_users() is False
