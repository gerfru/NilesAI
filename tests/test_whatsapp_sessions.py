"""Tests for WhatsApp session management (per-user Evolution API instances)."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from niles.config import Settings


VALID_TOKEN = "test-api-key"


def _make_settings(**overrides):
    defaults = dict(
        _env_file=None,
        postgres_password="test",
        evolution_api_key=VALID_TOKEN,
    )
    defaults.update(overrides)
    return Settings(**defaults)


class TestWhatsAppAction:
    """Test Evolution API client methods."""

    @pytest.fixture
    def action(self):
        from niles.actions.whatsapp import WhatsAppAction

        return WhatsAppAction(_make_settings())

    async def test_send_message_default_instance(self, action):
        """send_message without explicit instance uses the global one."""
        assert action.instance == "niles-whatsapp"

    async def test_send_message_custom_instance(self, action):
        """send_message with explicit instance parameter."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"status": "sent"}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with pytest.MonkeyPatch.context() as m:
            m.setattr("httpx.AsyncClient", lambda: mock_client)
            result = await action.send_message(
                to="436601234567", text="Hi", instance="niles-wa-5",
            )
            assert "error" not in result
            # Verify the URL includes the custom instance name
            call_url = mock_client.post.call_args[0][0]
            assert "niles-wa-5" in call_url

    def test_headers(self, action):
        """_headers returns correct API key."""
        assert action._headers() == {"apikey": VALID_TOKEN}


class TestWebhookPerUserRouting:
    """Test that webhook routes messages to whatsapp_inbox with correct user_id."""

    @pytest.fixture
    def mock_app(self):
        app = MagicMock()
        app.state.agent = AsyncMock()
        app.state.whatsapp_action = AsyncMock()
        app.state.settings = _make_settings()
        app.state.wa_store = AsyncMock()
        app.state.whatsapp_inbox = AsyncMock()
        app.state.contacts = AsyncMock()
        app.state.contacts.find_by_phone.return_value = "Max Mustermann"
        return app

    @pytest.fixture
    def webhook_payload(self):
        return {
            "event": "messages.upsert",
            "instance": "niles-wa-42",
            "data": {
                "key": {
                    "remoteJid": "436601234567@s.whatsapp.net",
                    "fromMe": False,
                    "id": "MSG001",
                },
                "message": {
                    "conversation": "Hello Niles",
                },
            },
        }

    async def test_per_user_routing(self, mock_app, webhook_payload):
        """Message from a per-user instance is stored with that user's user_id."""
        from niles.sources.whatsapp import whatsapp_webhook

        mock_app.state.wa_store.get_by_instance.return_value = {
            "user_id": 42,
            "instance_name": "niles-wa-42",
            "phone_number": "436601234567",
            "status": "connected",
        }

        request = AsyncMock()
        request.app = mock_app
        request.json.return_value = webhook_payload

        result = await whatsapp_webhook(request, token=VALID_TOKEN)

        assert result == {"status": "stored", "sender": "436601234567"}
        mock_app.state.whatsapp_inbox.store_message.assert_called_once_with(
            wa_message_id="MSG001",
            sender_phone="436601234567",
            contact_name="Max Mustermann",
            instance_name="niles-wa-42",
            user_id=42,
            content="Hello Niles",
        )

    async def test_fallback_routing(self, mock_app, webhook_payload):
        """Unknown instance stores with user_id=None."""
        from niles.sources.whatsapp import whatsapp_webhook

        mock_app.state.wa_store.get_by_instance.return_value = None

        request = AsyncMock()
        request.app = mock_app
        request.json.return_value = webhook_payload

        result = await whatsapp_webhook(request, token=VALID_TOKEN)

        assert result == {"status": "stored", "sender": "436601234567"}
        mock_app.state.whatsapp_inbox.store_message.assert_called_once_with(
            wa_message_id="MSG001",
            sender_phone="436601234567",
            contact_name="Max Mustermann",
            instance_name="niles-wa-42",
            user_id=None,
            content="Hello Niles",
        )

    async def test_incoming_message_never_auto_replies(self, mock_app, webhook_payload):
        """Incoming messages are stored in inbox, no LLM call, no reply."""
        from niles.sources.whatsapp import whatsapp_webhook

        mock_app.state.wa_store.get_by_instance.return_value = {
            "user_id": 42,
            "instance_name": "niles-wa-42",
            "phone_number": "436601234567",
            "status": "connected",
        }

        request = AsyncMock()
        request.app = mock_app
        request.json.return_value = webhook_payload

        await whatsapp_webhook(request, token=VALID_TOKEN)

        mock_app.state.whatsapp_inbox.store_message.assert_called_once()
        mock_app.state.agent.process_event.assert_not_called()
        mock_app.state.whatsapp_action.send_message.assert_not_called()

    async def test_contact_name_resolved(self, mock_app, webhook_payload):
        """Contact name is resolved from CardDAV contacts and passed to store_message."""
        from niles.sources.whatsapp import whatsapp_webhook

        mock_app.state.wa_store.get_by_instance.return_value = None
        mock_app.state.contacts.find_by_phone.return_value = "Thomas Brunner"

        request = AsyncMock()
        request.app = mock_app
        request.json.return_value = webhook_payload

        await whatsapp_webhook(request, token=VALID_TOKEN)

        mock_app.state.contacts.find_by_phone.assert_called_once_with("436601234567")
        call_kwargs = mock_app.state.whatsapp_inbox.store_message.call_args
        assert call_kwargs.kwargs["contact_name"] == "Thomas Brunner"

    async def test_unknown_contact_stores_none(self, mock_app, webhook_payload):
        """Unknown phone number stores contact_name=None."""
        from niles.sources.whatsapp import whatsapp_webhook

        mock_app.state.wa_store.get_by_instance.return_value = None
        mock_app.state.contacts.find_by_phone.return_value = None

        request = AsyncMock()
        request.app = mock_app
        request.json.return_value = webhook_payload

        await whatsapp_webhook(request, token=VALID_TOKEN)

        call_kwargs = mock_app.state.whatsapp_inbox.store_message.call_args
        assert call_kwargs.kwargs["contact_name"] is None


class TestAgentPerUserInstance:
    """Test that agent send_whatsapp tool uses per-user instance."""

    @pytest.fixture
    def wa_store_mock(self):
        store = AsyncMock()
        store.get_session.return_value = {
            "user_id": 5,
            "instance_name": "niles-wa-5",
            "phone_number": "436601234567",
            "status": "connected",
        }
        return store

    async def test_send_uses_per_user_instance(self, wa_store_mock):
        from niles.agent.core import NilesAgent

        whatsapp_mock = AsyncMock()
        whatsapp_mock.send_message.return_value = {"status": "sent"}

        agent = NilesAgent(
            config=_make_settings(),
            contacts=AsyncMock(),
            whatsapp=whatsapp_mock,
            memory=AsyncMock(),
            history=AsyncMock(),
            wa_store=wa_store_mock,
        )

        tool_call = MagicMock()
        tool_call.id = "call_123"
        tool_call.function.name = "send_whatsapp"
        tool_call.function.arguments = json.dumps({"to": "436601234567", "text": "Hi"})

        result = await agent._execute_tool_call(tool_call, chat_id="web-user-5")

        assert result == {"status": "sent", "to": "436601234567"}
        whatsapp_mock.send_message.assert_called_once_with(
            to="436601234567", text="Hi", instance="niles-wa-5",
        )

    async def test_send_without_session_uses_global(self):
        from niles.agent.core import NilesAgent

        wa_store_mock = AsyncMock()
        wa_store_mock.get_session.return_value = None

        whatsapp_mock = AsyncMock()
        whatsapp_mock.send_message.return_value = {"status": "sent"}

        agent = NilesAgent(
            config=_make_settings(),
            contacts=AsyncMock(),
            whatsapp=whatsapp_mock,
            memory=AsyncMock(),
            history=AsyncMock(),
            wa_store=wa_store_mock,
        )

        tool_call = MagicMock()
        tool_call.id = "call_456"
        tool_call.function.name = "send_whatsapp"
        tool_call.function.arguments = json.dumps({"to": "436601234567", "text": "Hi"})

        result = await agent._execute_tool_call(tool_call, chat_id="web-user-99")

        assert result == {"status": "sent", "to": "436601234567"}
        whatsapp_mock.send_message.assert_called_once_with(
            to="436601234567", text="Hi", instance=None,
        )

    async def test_send_without_wa_store_uses_global(self):
        """Agent without wa_store (backwards compat) uses global instance."""
        from niles.agent.core import NilesAgent

        whatsapp_mock = AsyncMock()
        whatsapp_mock.send_message.return_value = {"status": "sent"}

        agent = NilesAgent(
            config=_make_settings(),
            contacts=AsyncMock(),
            whatsapp=whatsapp_mock,
            memory=AsyncMock(),
            history=AsyncMock(),
        )

        tool_call = MagicMock()
        tool_call.id = "call_789"
        tool_call.function.name = "send_whatsapp"
        tool_call.function.arguments = json.dumps({"to": "436601234567", "text": "Hi"})

        result = await agent._execute_tool_call(tool_call, chat_id="web-user-1")

        assert result == {"status": "sent", "to": "436601234567"}
        whatsapp_mock.send_message.assert_called_once_with(
            to="436601234567", text="Hi", instance=None,
        )


class TestAgentGetWhatsAppMessages:
    """Test that agent get_whatsapp_messages tool queries the inbox."""

    async def test_get_messages_by_contact_name(self):
        from niles.agent.core import NilesAgent

        inbox_mock = AsyncMock()
        inbox_mock.get_messages.return_value = [
            {
                "sender_phone": "436601234567",
                "contact_name": "Max Mustermann",
                "content": "Treffen wir uns morgen?",
                "received_at": "2026-02-24T10:00:00+01:00",
            },
        ]

        agent = NilesAgent(
            config=_make_settings(),
            contacts=AsyncMock(),
            whatsapp=AsyncMock(),
            memory=AsyncMock(),
            history=AsyncMock(),
            whatsapp_inbox=inbox_mock,
        )

        tool_call = MagicMock()
        tool_call.id = "call_inbox_1"
        tool_call.function.name = "get_whatsapp_messages"
        tool_call.function.arguments = json.dumps({"contact": "Max"})

        result = await agent._execute_tool_call(tool_call, chat_id="web-user-1")

        assert result["count"] == 1
        assert result["messages"][0]["contact_name"] == "Max Mustermann"
        inbox_mock.get_messages.assert_called_once_with(
            contact="Max", phone=None, limit=10,
        )

    async def test_get_messages_by_phone(self):
        from niles.agent.core import NilesAgent

        inbox_mock = AsyncMock()
        inbox_mock.get_messages.return_value = [
            {
                "sender_phone": "436601234567",
                "contact_name": None,
                "content": "Test",
                "received_at": "2026-02-24T10:00:00+01:00",
            },
        ]

        agent = NilesAgent(
            config=_make_settings(),
            contacts=AsyncMock(),
            whatsapp=AsyncMock(),
            memory=AsyncMock(),
            history=AsyncMock(),
            whatsapp_inbox=inbox_mock,
        )

        tool_call = MagicMock()
        tool_call.id = "call_inbox_2"
        tool_call.function.name = "get_whatsapp_messages"
        tool_call.function.arguments = json.dumps({"contact": "436601234567"})

        result = await agent._execute_tool_call(tool_call, chat_id="web-user-1")

        assert result["count"] == 1
        inbox_mock.get_messages.assert_called_once_with(
            contact=None, phone="436601234567", limit=10,
        )

    async def test_get_messages_strips_at_prefix(self):
        """LLM sometimes sends '@Name' — the @ prefix must be stripped."""
        from niles.agent.core import NilesAgent

        inbox_mock = AsyncMock()
        inbox_mock.get_messages.return_value = [
            {
                "sender_phone": "436601234567",
                "contact_name": "Chrissi",
                "content": "Hi!",
                "received_at": "2026-02-24T10:00:00+01:00",
            },
        ]

        agent = NilesAgent(
            config=_make_settings(),
            contacts=AsyncMock(),
            whatsapp=AsyncMock(),
            memory=AsyncMock(),
            history=AsyncMock(),
            whatsapp_inbox=inbox_mock,
        )

        tool_call = MagicMock()
        tool_call.id = "call_inbox_at"
        tool_call.function.name = "get_whatsapp_messages"
        tool_call.function.arguments = json.dumps({"contact": "@Chrissi"})

        result = await agent._execute_tool_call(tool_call, chat_id="web-user-1")

        assert result["count"] == 1
        inbox_mock.get_messages.assert_called_once_with(
            contact="Chrissi", phone=None, limit=10,
        )

    async def test_get_messages_fallback_via_contacts(self):
        """When inbox search by name fails, resolve name→phone via contacts and retry."""
        from niles.agent.core import NilesAgent

        inbox_mock = AsyncMock()
        # First call (by contact_name) returns nothing, second call (by phone) finds it
        inbox_mock.get_messages.side_effect = [
            [],  # search by contact_name="Gerald"
            [    # search by phone="4366488846514"
                {
                    "sender_phone": "4366488846514",
                    "contact_name": None,
                    "content": "Hallo!",
                    "received_at": "2026-02-24T10:00:00+01:00",
                },
            ],
        ]

        contacts_mock = AsyncMock()
        contacts_mock.find_by_name.return_value = {
            "full_name": "Fruhmann, Gerald",
            "phone": "4366488846514",
            "phones": [{"type": "mobile", "number": "4366488846514"}],
            "email": None,
        }

        agent = NilesAgent(
            config=_make_settings(),
            contacts=contacts_mock,
            whatsapp=AsyncMock(),
            memory=AsyncMock(),
            history=AsyncMock(),
            whatsapp_inbox=inbox_mock,
        )

        tool_call = MagicMock()
        tool_call.id = "call_inbox_fallback"
        tool_call.function.name = "get_whatsapp_messages"
        tool_call.function.arguments = json.dumps({"contact": "Gerald"})

        result = await agent._execute_tool_call(tool_call, chat_id="web-user-1")

        assert result["count"] == 1
        assert result["messages"][0]["sender_phone"] == "4366488846514"
        # Verify: first searched by name, then resolved via contacts, then by phone
        contacts_mock.find_by_name.assert_called_once_with("Gerald")
        assert inbox_mock.get_messages.call_count == 2
        inbox_mock.get_messages.assert_any_call(contact="Gerald", phone=None, limit=10)
        inbox_mock.get_messages.assert_any_call(phone="4366488846514", limit=10)

    async def test_get_messages_empty(self):
        from niles.agent.core import NilesAgent

        inbox_mock = AsyncMock()
        inbox_mock.get_messages.return_value = []

        contacts_mock = AsyncMock()
        contacts_mock.find_by_name.return_value = None

        agent = NilesAgent(
            config=_make_settings(),
            contacts=contacts_mock,
            whatsapp=AsyncMock(),
            memory=AsyncMock(),
            history=AsyncMock(),
            whatsapp_inbox=inbox_mock,
        )

        tool_call = MagicMock()
        tool_call.id = "call_inbox_3"
        tool_call.function.name = "get_whatsapp_messages"
        tool_call.function.arguments = json.dumps({"contact": "Nobody"})

        result = await agent._execute_tool_call(tool_call, chat_id="web-user-1")

        assert "error" in result

    async def test_get_messages_without_inbox(self):
        """Agent without whatsapp_inbox returns error."""
        from niles.agent.core import NilesAgent

        agent = NilesAgent(
            config=_make_settings(),
            contacts=AsyncMock(),
            whatsapp=AsyncMock(),
            memory=AsyncMock(),
            history=AsyncMock(),
        )

        tool_call = MagicMock()
        tool_call.id = "call_inbox_4"
        tool_call.function.name = "get_whatsapp_messages"
        tool_call.function.arguments = json.dumps({})

        result = await agent._execute_tool_call(tool_call, chat_id="web-user-1")

        assert "error" in result

    async def test_get_messages_limit_capped(self):
        """Limit is capped at 50."""
        from niles.agent.core import NilesAgent

        inbox_mock = AsyncMock()
        inbox_mock.get_messages.return_value = []

        agent = NilesAgent(
            config=_make_settings(),
            contacts=AsyncMock(),
            whatsapp=AsyncMock(),
            memory=AsyncMock(),
            history=AsyncMock(),
            whatsapp_inbox=inbox_mock,
        )

        tool_call = MagicMock()
        tool_call.id = "call_inbox_5"
        tool_call.function.name = "get_whatsapp_messages"
        tool_call.function.arguments = json.dumps({"limit": 999})

        await agent._execute_tool_call(tool_call, chat_id="web-user-1")

        inbox_mock.get_messages.assert_called_once_with(
            contact=None, phone=None, limit=50,
        )
