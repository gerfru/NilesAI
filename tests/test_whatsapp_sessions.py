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
    """Test that webhook routes messages to the correct per-user chat ID."""

    @pytest.fixture
    def mock_app(self):
        app = MagicMock()
        app.state.agent = AsyncMock()
        app.state.whatsapp_action = AsyncMock()
        app.state.settings = _make_settings()
        app.state.wa_store = AsyncMock()
        app.state.history = AsyncMock()
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
                },
                "message": {
                    "conversation": "Hello Niles",
                },
            },
        }

    async def test_per_user_routing(self, mock_app, webhook_payload):
        """Message from a per-user instance is stored with that user's chat_id."""
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

        # Verify history stored with per-user chat_id
        mock_app.state.history.add_message.assert_called_once_with(
            "web-user-42", "user", "Hello Niles",
        )

    async def test_fallback_routing(self, mock_app, webhook_payload):
        """Unknown instance falls back to wa-{sender} chat_id."""
        from niles.sources.whatsapp import whatsapp_webhook

        mock_app.state.wa_store.get_by_instance.return_value = None

        request = AsyncMock()
        request.app = mock_app
        request.json.return_value = webhook_payload

        await whatsapp_webhook(request, token=VALID_TOKEN)

        # Verify history stored with fallback chat_id
        mock_app.state.history.add_message.assert_called_once_with(
            "wa-436601234567", "user", "Hello Niles",
        )

    async def test_incoming_message_never_auto_replies(self, mock_app, webhook_payload):
        """Incoming messages from others are stored in history, no LLM call, no reply."""
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

        # Message stored in history (no LLM call, no reply)
        mock_app.state.history.add_message.assert_called_once_with(
            "web-user-42", "user", "Hello Niles",
        )
        mock_app.state.agent.process_event.assert_not_called()
        mock_app.state.whatsapp_action.send_message.assert_not_called()


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
