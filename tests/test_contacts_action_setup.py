"""Tests for ContactsAction connect/disconnect."""

from unittest.mock import AsyncMock

import pytest

from niles.actions.contacts import ContactsAction


class TestContactsConnect:
    @pytest.mark.asyncio
    async def test_success_creates_source_and_syncs(self):
        manager = AsyncMock()
        manager.test_connection.return_value = (True, "OK")
        manager.add_source.return_value = {
            "id": 1,
            "name": "test",
            "url": "https://dav.example.com",
        }
        action = ContactsAction(AsyncMock(), carddav_manager=manager)

        result = await action.connect(
            "  https://dav.example.com  ", "  user  ", "pass", user_id=42
        )

        manager.test_connection.assert_called_once_with(
            "https://dav.example.com", "user", "pass"
        )
        manager.add_source.assert_called_once_with(
            "https://dav.example.com", "user", "pass", user_id=42
        )
        manager.sync_source.assert_called_once_with(1, user_id=42)
        assert result["id"] == 1

    @pytest.mark.asyncio
    async def test_connection_failure_raises(self):
        manager = AsyncMock()
        manager.test_connection.return_value = (False, "Auth failed")
        action = ContactsAction(AsyncMock(), carddav_manager=manager)

        with pytest.raises(ConnectionError, match="Auth failed"):
            await action.connect("https://dav.example.com", "user", "pass", user_id=42)

        manager.add_source.assert_not_called()


class TestContactsDisconnect:
    @pytest.mark.asyncio
    async def test_removes_source(self):
        manager = AsyncMock()
        manager.remove_source.return_value = True
        action = ContactsAction(AsyncMock(), carddav_manager=manager)

        result = await action.disconnect(source_id=1, user_id=42)

        assert result is True
        manager.remove_source.assert_called_once_with(1, user_id=42)
