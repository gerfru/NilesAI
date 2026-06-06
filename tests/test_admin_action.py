"""Tests for AdminAction."""

from unittest.mock import AsyncMock

import pytest

from niles.actions.admin import AdminAction, DuplicateEmailError


class TestCreateUser:
    @pytest.mark.asyncio
    async def test_success(self):
        user_store = AsyncMock()
        user_store.get_by_email.return_value = None
        user_store.create_password_user.return_value = {
            "id": 42,
            "email": "new@example.com",
            "display_name": "New User",
            "is_admin": False,
        }
        action = AdminAction(user_store)

        result = await action.create_user(
            "  New@Example.com  ", "  New User  ", "securepass123"
        )

        assert result["id"] == 42
        # Email normalized to lowercase + stripped
        user_store.get_by_email.assert_called_once_with("new@example.com")
        # Password is hashed (not the plain string)
        call_args = user_store.create_password_user.call_args
        assert call_args[0][0] == "new@example.com"
        assert call_args[0][1] == "New User"
        assert call_args[0][2] != "securepass123"  # hashed

    @pytest.mark.asyncio
    async def test_empty_fields_raises(self):
        action = AdminAction(AsyncMock())

        with pytest.raises(ValueError, match="Alle Felder"):
            await action.create_user("", "Name", "password12345")

        with pytest.raises(ValueError, match="Alle Felder"):
            await action.create_user("email@test.com", "", "password12345")

        with pytest.raises(ValueError, match="Alle Felder"):
            await action.create_user("email@test.com", "Name", "")

    @pytest.mark.asyncio
    async def test_short_password_raises(self):
        action = AdminAction(AsyncMock())

        with pytest.raises(ValueError, match="mindestens 12 Zeichen"):
            await action.create_user("a@b.com", "Name", "short")

    @pytest.mark.asyncio
    async def test_duplicate_email_raises(self):
        user_store = AsyncMock()
        user_store.get_by_email.return_value = {"id": 1, "email": "dup@test.com"}
        action = AdminAction(user_store)

        with pytest.raises(DuplicateEmailError, match="bereits vergeben"):
            await action.create_user("dup@test.com", "Name", "password12345")


class TestResetPassword:
    @pytest.mark.asyncio
    async def test_success(self):
        user_store = AsyncMock()
        user_store.get_by_id.return_value = {"id": 1, "email": "test@test.com"}
        action = AdminAction(user_store)

        await action.reset_password(1, "newpassword123")

        user_store.update_password.assert_called_once()
        call_args = user_store.update_password.call_args
        assert call_args[0][0] == 1
        assert call_args[0][1] != "newpassword123"  # hashed

    @pytest.mark.asyncio
    async def test_short_password_raises(self):
        action = AdminAction(AsyncMock())

        with pytest.raises(ValueError, match="mindestens 12 Zeichen"):
            await action.reset_password(1, "short")

    @pytest.mark.asyncio
    async def test_user_not_found_raises(self):
        user_store = AsyncMock()
        user_store.get_by_id.return_value = None
        action = AdminAction(user_store)

        with pytest.raises(KeyError, match="nicht gefunden"):
            await action.reset_password(999, "password12345")


class TestDeactivateUser:
    @pytest.mark.asyncio
    async def test_success(self):
        user_store = AsyncMock()
        user_store.get_by_id.return_value = {"id": 2, "email": "user@test.com"}
        action = AdminAction(user_store)

        await action.deactivate_user(2, admin_uid=1)

        user_store.deactivate_user.assert_called_once_with(2)

    @pytest.mark.asyncio
    async def test_self_deactivation_raises(self):
        action = AdminAction(AsyncMock())

        with pytest.raises(ValueError, match="Eigenen Account"):
            await action.deactivate_user(1, admin_uid=1)

    @pytest.mark.asyncio
    async def test_user_not_found_raises(self):
        user_store = AsyncMock()
        user_store.get_by_id.return_value = None
        action = AdminAction(user_store)

        with pytest.raises(KeyError, match="nicht gefunden"):
            await action.deactivate_user(999, admin_uid=1)


class TestHardDeleteUser:
    @pytest.mark.asyncio
    async def test_success(self):
        user_store = AsyncMock()
        user_store.get_by_id.return_value = {"id": 2, "email": "user@test.com"}
        action = AdminAction(user_store)

        await action.hard_delete_user(2, admin_uid=1)

        user_store.hard_delete_user.assert_called_once_with(2)

    @pytest.mark.asyncio
    async def test_self_deletion_raises(self):
        action = AdminAction(AsyncMock())

        with pytest.raises(ValueError, match="Eigenen Account"):
            await action.hard_delete_user(1, admin_uid=1)

    @pytest.mark.asyncio
    async def test_user_not_found_raises(self):
        user_store = AsyncMock()
        user_store.get_by_id.return_value = None
        action = AdminAction(user_store)

        with pytest.raises(KeyError, match="nicht gefunden"):
            await action.hard_delete_user(999, admin_uid=1)


class TestListUsers:
    @pytest.mark.asyncio
    async def test_delegates_to_store(self):
        user_store = AsyncMock()
        user_store.list_all.return_value = [{"id": 1}, {"id": 2}]
        action = AdminAction(user_store)

        result = await action.list_users()

        assert len(result) == 2
        user_store.list_all.assert_called_once()
