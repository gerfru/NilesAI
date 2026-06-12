"""Integration tests for DB-backed stores."""

import pytest

from niles.memory.history import ConversationHistory
from niles.settings_store import SettingsStore
from niles.signal_store import SignalMessageStore
from niles.vikunja_store import VikunjaCredentialStore
from niles.whatsapp_store import WhatsAppSessionStore

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]


class TestConversationHistory:
    async def test_add_and_get_messages(self, pool_in_tx):
        history = ConversationHistory(pool_in_tx)
        await history.add_message("integ-chat", "user", "Hello")
        await history.add_message("integ-chat", "assistant", "Hi there!")
        messages = await history.get_recent("integ-chat")
        assert len(messages) == 2
        roles = {m["role"] for m in messages}
        assert roles == {"user", "assistant"}

    async def test_clear(self, pool_in_tx):
        history = ConversationHistory(pool_in_tx)
        await history.add_message("clear-chat", "user", "msg1")
        await history.add_message("clear-chat", "user", "msg2")
        count = await history.clear("clear-chat")
        assert count == 2
        remaining = await history.get_recent("clear-chat")
        assert remaining == []

    async def test_pagination(self, pool_in_tx):
        history = ConversationHistory(pool_in_tx)
        for i in range(5):
            await history.add_message("page-chat", "user", f"msg{i}")
        messages = await history.get_recent("page-chat", limit=3)
        assert len(messages) == 3


class TestSettingsStore:
    async def test_set_and_get_all(self, pool_in_tx):
        store = SettingsStore(pool_in_tx)
        await store.set("timezone", "Europe/Berlin")
        all_settings = await store.get_all()
        assert all_settings.get("timezone") == "Europe/Berlin"

    async def test_delete(self, pool_in_tx):
        store = SettingsStore(pool_in_tx)
        await store.set("log_level", "DEBUG")
        await store.delete("log_level")
        all_settings = await store.get_all()
        assert "log_level" not in all_settings

    async def test_invalid_key_raises(self, pool_in_tx):
        store = SettingsStore(pool_in_tx)
        with pytest.raises(ValueError, match="not editable"):
            await store.set("nonexistent_setting_xyz", "value")

    async def test_invalid_timezone_raises(self, pool_in_tx):
        store = SettingsStore(pool_in_tx)
        with pytest.raises(ValueError, match="not a valid IANA timezone"):
            await store.set("timezone", "Invalid/Timezone")


class TestWhatsAppSessionStore:
    async def test_upsert_and_get(self, pool_in_tx, seed_user):
        store = WhatsAppSessionStore(pool_in_tx)
        await store.upsert_session(
            user_id=seed_user,
            instance_name="test-instance",
            status="connected",
            phone_number="435000000000",
        )
        session = await store.get_session(seed_user)
        assert session is not None
        assert session["instance_name"] == "test-instance"
        assert session["status"] == "connected"

    async def test_get_by_instance(self, pool_in_tx, seed_user):
        store = WhatsAppSessionStore(pool_in_tx)
        await store.upsert_session(
            user_id=seed_user,
            instance_name="lookup-inst",
            status="connected",
        )
        session = await store.get_by_instance("lookup-inst")
        assert session is not None
        assert session["user_id"] == seed_user

    async def test_delete_session(self, pool_in_tx, seed_user):
        store = WhatsAppSessionStore(pool_in_tx)
        await store.upsert_session(
            user_id=seed_user,
            instance_name="del-inst",
            status="connected",
        )
        await store.delete_session(seed_user)
        assert await store.get_session(seed_user) is None


class TestVikunjaCredentialStore:
    async def test_upsert_and_get(self, pool_in_tx, seed_user):
        store = VikunjaCredentialStore(pool_in_tx)
        await store.upsert_credentials(
            user_id=seed_user,
            api_token="test-token-123",
            api_url="http://vikunja:3456/api/v1",
        )
        creds = await store.get_credentials(seed_user)
        assert creds is not None
        assert creds["api_token"] == "test-token-123"

    async def test_delete_credentials(self, pool_in_tx, seed_user):
        store = VikunjaCredentialStore(pool_in_tx)
        await store.upsert_credentials(
            user_id=seed_user,
            api_token="temp-token",
        )
        await store.delete_credentials(seed_user)
        assert await store.get_credentials(seed_user) is None


class TestSignalMessageStore:
    async def test_store_and_retrieve(self, pool_in_tx):
        store = SignalMessageStore(pool_in_tx)
        await store.store(
            phone="+43660999888",
            text="Test Signal message",
            from_me=False,
            chat_id="test-chat",
        )
        messages = await store.get_messages(phone="+43660999888")
        assert len(messages) >= 1
        assert messages[0]["text"] == "Test Signal message"
        assert messages[0]["from_me"] is False
