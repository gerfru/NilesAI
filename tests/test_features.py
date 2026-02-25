"""Tests for feature flags."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from niles.config import Settings


class TestFeatureFlagDefaults:
    def test_send_others_enabled_by_default(self):
        settings = Settings(
            _env_file=None,
            postgres_password="test",
            evolution_api_key="test",
        )
        assert settings.feature_whatsapp_send_others is True

    def test_flags_from_env(self, monkeypatch):
        monkeypatch.setenv("FEATURE_WHATSAPP_SEND_OTHERS", "false")
        settings = Settings(
            postgres_password="test",
            evolution_api_key="test",
        )
        assert settings.feature_whatsapp_send_others is False

    def test_old_flags_ignored(self, monkeypatch):
        """Old feature flags in .env should not cause errors (extra=ignore)."""
        monkeypatch.setenv("FEATURE_WHATSAPP_AUTO_REPLY", "true")
        monkeypatch.setenv("FEATURE_TOOL_SEND_WHATSAPP", "false")
        settings = Settings(
            postgres_password="test",
            evolution_api_key="test",
        )
        # Old flags are silently ignored
        assert not hasattr(settings, "feature_whatsapp_auto_reply")
        assert not hasattr(settings, "feature_tool_send_whatsapp")


class TestSendWhatsAppOthersFlag:
    @pytest.fixture
    def disabled_config(self):
        return Settings(
            _env_file=None,
            postgres_password="test",
            evolution_api_key="test",
            feature_whatsapp_send_others=False,
        )

    @pytest.fixture
    def enabled_config(self):
        return Settings(
            _env_file=None,
            postgres_password="test",
            evolution_api_key="test",
            feature_whatsapp_send_others=True,
        )

    async def test_send_to_others_disabled_returns_error(self, disabled_config):
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

    async def test_send_to_others_enabled_sends(self, enabled_config):
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

    async def test_send_to_self_always_allowed(self, disabled_config):
        """Sending to own number is allowed even when send_others is disabled."""
        from niles.agent.core import NilesAgent

        whatsapp_mock = AsyncMock()
        whatsapp_mock.send_message.return_value = {"status": "sent"}

        wa_store = AsyncMock()
        wa_store.get_session.return_value = {
            "user_id": 1,
            "instance_name": "niles-wa-1",
            "phone_number": "436601234567",
            "status": "connected",
        }

        agent = NilesAgent(
            config=disabled_config,
            contacts=AsyncMock(),
            whatsapp=whatsapp_mock,
            memory=AsyncMock(),
            history=AsyncMock(),
            wa_store=wa_store,
        )

        tool_call = MagicMock()
        tool_call.id = "call_123"
        tool_call.function.name = "send_whatsapp"
        tool_call.function.arguments = json.dumps(
            {"to": "436601234567", "text": "Reminder"}
        )

        # chat_id = web-user-1 so _get_own_phone_number can look up the session
        result = await agent._execute_tool_call(tool_call, chat_id="web-user-1")

        assert result == {"status": "sent", "to": "436601234567"}
        whatsapp_mock.send_message.assert_called_once()

    async def test_send_to_self_via_self_chat_id(self, disabled_config):
        """Self-chat chat_id (wa-self-{phone}) allows sending to own number."""
        from niles.agent.core import NilesAgent

        whatsapp_mock = AsyncMock()
        whatsapp_mock.send_message.return_value = {"status": "sent"}

        agent = NilesAgent(
            config=disabled_config,
            contacts=AsyncMock(),
            whatsapp=whatsapp_mock,
            memory=AsyncMock(),
            history=AsyncMock(),
        )

        tool_call = MagicMock()
        tool_call.id = "call_123"
        tool_call.function.name = "send_whatsapp"
        tool_call.function.arguments = json.dumps(
            {"to": "436601234567", "text": "Note"}
        )

        result = await agent._execute_tool_call(
            tool_call, chat_id="wa-self-436601234567"
        )

        assert result == {"status": "sent", "to": "436601234567"}
        whatsapp_mock.send_message.assert_called_once()


class TestWebhookAuth:
    """Token validation tests (unchanged by self-chat feature)."""

    VALID_TOKEN = "test-api-key"

    @pytest.fixture
    def mock_app(self):
        app = MagicMock()
        app.state.agent = AsyncMock()
        app.state.whatsapp_action = AsyncMock()
        app.state.settings = Settings(
            _env_file=None,
            postgres_password="test",
            evolution_api_key=self.VALID_TOKEN,
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

    async def test_webhook_rejects_invalid_token(self, mock_app, webhook_payload):
        from niles.sources.whatsapp import whatsapp_webhook

        request = AsyncMock()
        request.app = mock_app
        request.json.return_value = webhook_payload

        result = await whatsapp_webhook(request, token="wrong-token")

        assert result.status_code == 401
        mock_app.state.agent.process_event.assert_not_called()

    async def test_webhook_rejects_missing_token(self, mock_app, webhook_payload):
        from niles.sources.whatsapp import whatsapp_webhook

        request = AsyncMock()
        request.app = mock_app
        request.json.return_value = webhook_payload

        result = await whatsapp_webhook(request, token="")

        assert result.status_code == 401
        mock_app.state.agent.process_event.assert_not_called()
