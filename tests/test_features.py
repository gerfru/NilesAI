"""Tests for feature flags."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from niles.config import Settings


class TestFeatureFlagDefaults:
    def test_auto_reply_disabled_by_default(self):
        settings = Settings(
            postgres_password="test",
            evolution_api_key="test",
        )
        assert settings.feature_whatsapp_auto_reply is False

    def test_send_whatsapp_enabled_by_default(self):
        settings = Settings(
            postgres_password="test",
            evolution_api_key="test",
        )
        assert settings.feature_tool_send_whatsapp is True

    def test_flags_from_env(self, monkeypatch):
        monkeypatch.setenv("FEATURE_WHATSAPP_AUTO_REPLY", "true")
        monkeypatch.setenv("FEATURE_TOOL_SEND_WHATSAPP", "false")
        settings = Settings(
            postgres_password="test",
            evolution_api_key="test",
        )
        assert settings.feature_whatsapp_auto_reply is True
        assert settings.feature_tool_send_whatsapp is False


class TestAutoReplyFlag:
    @pytest.fixture
    def mock_app(self):
        """Create a mock app with state."""
        app = MagicMock()
        app.state.agent = AsyncMock()
        app.state.whatsapp_action = AsyncMock()
        app.state.settings = Settings(
            postgres_password="test",
            evolution_api_key="test",
        )
        return app

    @pytest.fixture
    def webhook_payload(self):
        return {
            "event": "messages.upsert",
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

    async def test_auto_reply_disabled_suppresses_send(self, mock_app, webhook_payload):
        from niles.sources.whatsapp import whatsapp_webhook

        mock_app.state.agent.process_event.return_value = "Reply text"
        mock_app.state.settings.feature_whatsapp_auto_reply = False

        request = AsyncMock()
        request.app = mock_app
        request.json.return_value = webhook_payload

        result = await whatsapp_webhook(request)

        assert result == {"status": "processed"}
        mock_app.state.agent.process_event.assert_called_once()
        mock_app.state.whatsapp_action.send_message.assert_not_called()

    async def test_auto_reply_enabled_sends_response(self, mock_app, webhook_payload):
        from niles.sources.whatsapp import whatsapp_webhook

        mock_app.state.agent.process_event.return_value = "Reply text"
        mock_app.state.settings.feature_whatsapp_auto_reply = True

        request = AsyncMock()
        request.app = mock_app
        request.json.return_value = webhook_payload

        result = await whatsapp_webhook(request)

        assert result == {"status": "processed"}
        mock_app.state.agent.process_event.assert_called_once()
        mock_app.state.whatsapp_action.send_message.assert_called_once_with(
            to="436601234567@s.whatsapp.net",
            text="Reply text",
        )


class TestSendWhatsAppFlag:
    @pytest.fixture
    def disabled_config(self):
        return Settings(
            postgres_password="test",
            evolution_api_key="test",
            feature_tool_send_whatsapp=False,
        )

    @pytest.fixture
    def enabled_config(self):
        return Settings(
            postgres_password="test",
            evolution_api_key="test",
            feature_tool_send_whatsapp=True,
        )

    async def test_send_whatsapp_disabled_returns_error(self, disabled_config):
        from niles.agent.core import NilesAgent

        agent = NilesAgent(
            config=disabled_config,
            contacts=AsyncMock(),
            whatsapp=AsyncMock(),
            memory=AsyncMock(),
            history=AsyncMock(),
        )

        tool_call = MagicMock()
        tool_call.id = "call_123"
        tool_call.function.name = "send_whatsapp"
        tool_call.function.arguments = json.dumps({"to": "436601234567", "text": "Hi"})

        result = await agent._execute_tool_call(tool_call)

        assert "error" in result
        assert "deaktiviert" in result["error"]
        agent.whatsapp.send_message.assert_not_called()

    async def test_send_whatsapp_enabled_sends(self, enabled_config):
        from niles.agent.core import NilesAgent

        whatsapp_mock = AsyncMock()
        whatsapp_mock.send_message.return_value = {"status": "sent"}

        agent = NilesAgent(
            config=enabled_config,
            contacts=AsyncMock(),
            whatsapp=whatsapp_mock,
            memory=AsyncMock(),
            history=AsyncMock(),
        )

        tool_call = MagicMock()
        tool_call.id = "call_123"
        tool_call.function.name = "send_whatsapp"
        tool_call.function.arguments = json.dumps({"to": "436601234567", "text": "Hi"})

        result = await agent._execute_tool_call(tool_call)

        assert result == {"status": "sent", "to": "436601234567"}
        whatsapp_mock.send_message.assert_called_once()
