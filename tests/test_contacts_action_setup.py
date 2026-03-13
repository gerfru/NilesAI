"""Tests for ContactsAction connect/disconnect."""

from unittest.mock import AsyncMock

import pytest

from niles.actions.contacts import ContactsAction

from tests.helpers import make_test_settings


class TestContactsConnect:
    @pytest.mark.asyncio
    async def test_success_persists_and_returns_settings(self):
        store = AsyncMock()
        carddav = AsyncMock()
        carddav.test_connection.return_value = (True, "OK")
        action = ContactsAction(AsyncMock(), settings_store=store, carddav_sync=carddav)
        settings = make_test_settings()

        result = await action.connect(
            "  https://dav.example.com  ", "  user  ", "pass", settings
        )

        assert result.carddav_url == "https://dav.example.com"
        assert result.carddav_user == "user"
        assert store.set.call_count == 3
        store.set.assert_any_call("carddav_url", "https://dav.example.com")
        store.set.assert_any_call("carddav_user", "user")
        store.set.assert_any_call("carddav_password", "pass")

    @pytest.mark.asyncio
    async def test_connection_failure_raises_and_reverts(self):
        store = AsyncMock()
        carddav = AsyncMock()
        carddav.test_connection.return_value = (False, "Auth failed")
        action = ContactsAction(AsyncMock(), settings_store=store, carddav_sync=carddav)
        settings = make_test_settings()

        with pytest.raises(ConnectionError, match="Auth failed"):
            await action.connect("https://dav.example.com", "user", "pass", settings)

        store.set.assert_not_called()
        # Config reverted to original
        carddav.update_config.assert_called_with(settings)


class TestContactsDisconnect:
    @pytest.mark.asyncio
    async def test_deletes_credentials_and_clears_contacts(self):
        store = AsyncMock()
        carddav = AsyncMock()
        pool = AsyncMock()
        action = ContactsAction(pool, settings_store=store, carddav_sync=carddav)
        settings = make_test_settings(
            carddav_url="https://dav.example.com",
            carddav_user="user",
        )

        result = await action.disconnect(settings)

        assert store.delete.call_count == 3
        store.delete.assert_any_call("carddav_url")
        store.delete.assert_any_call("carddav_user")
        store.delete.assert_any_call("carddav_password")
        assert result.carddav_url == ""
        carddav.update_config.assert_called_once()
        pool.execute.assert_called_once()  # clear_all
