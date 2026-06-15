"""Tests for WhatsApp self-chat trigger."""

import hashlib
import hmac
from unittest.mock import AsyncMock, MagicMock

import pytest

from niles.config import Settings
from niles.sources.triggers import is_niles_trigger, strip_trigger
from niles.sources.whatsapp import _echo_guard

_SESSION_SECRET = "test-session-secret"  # pragma: allowlist secret
# Mirrors config.webhook_token (derived from session_secret).
VALID_WEBHOOK_TOKEN = hmac.new(_SESSION_SECRET.encode(), b"whatsapp-webhook", hashlib.sha256).hexdigest()


class TestIsNilesTrigger:
    def test_hey_niles(self):
        assert is_niles_trigger("Hey Niles, was geht?") is True

    def test_hi_niles(self):
        assert is_niles_trigger("Hi Niles was steht an") is True

    def test_hallo_niles(self):
        assert is_niles_trigger("Hallo Niles!") is True

    def test_just_niles(self):
        assert is_niles_trigger("Niles Termin morgen") is True

    def test_case_insensitive(self):
        assert is_niles_trigger("HEY NILES was geht") is True
        assert is_niles_trigger("hey niles") is True

    def test_with_leading_whitespace(self):
        assert is_niles_trigger("  Hey Niles, test") is True

    def test_no_trigger(self):
        assert is_niles_trigger("Einkaufsliste") is False
        assert is_niles_trigger("Was macht Niles?") is False
        assert is_niles_trigger("") is False

    def test_niles_in_middle(self):
        """'Niles' in the middle of a sentence should NOT trigger."""
        assert is_niles_trigger("Ich frage Niles mal") is False

    def test_word_boundary_nilesh(self):
        """'Nilesh' should NOT trigger (name starts with 'niles')."""
        assert is_niles_trigger("Nilesh, kannst du...") is False

    def test_word_boundary_nilesarmy(self):
        """'nilesarmy' should NOT trigger (word continues after 'niles')."""
        assert is_niles_trigger("nilesarmy is cool") is False

    def test_word_boundary_hey_nilesh(self):
        """'Hey Nilesh' should NOT trigger."""
        assert is_niles_trigger("Hey Nilesh was geht") is False


class TestStripTrigger:
    def test_hey_niles_comma(self):
        assert strip_trigger("Hey Niles, was steht an?") == "was steht an?"

    def test_hey_niles_space(self):
        assert strip_trigger("Hey Niles was steht an?") == "was steht an?"

    def test_niles_colon(self):
        assert strip_trigger("Niles: Termin morgen") == "Termin morgen"

    def test_hey_niles_dash(self):
        assert strip_trigger("Hey Niles - mach mal") == "mach mal"

    def test_only_trigger(self):
        assert strip_trigger("Hey Niles") == ""

    def test_preserves_case(self):
        result = strip_trigger("Hey Niles, Termin mit Julia")
        assert result == "Termin mit Julia"

    def test_case_insensitive_strip(self):
        result = strip_trigger("HEY NILES was geht")
        assert result == "was geht"


class TestSelfChatWebhook:
    """Integration tests for the self-chat webhook flow."""

    VALID_TOKEN = "test-api-key"

    @pytest.fixture
    def mock_app(self):
        app = MagicMock()
        app.state.agent = AsyncMock()
        app.state.whatsapp_action = AsyncMock()
        app.state.history = AsyncMock()
        app.state.wa_store = AsyncMock()
        app.state.settings = Settings(
            _env_file=None,
            postgres_password="test",
            evolution_api_key=self.VALID_TOKEN,
            session_secret=_SESSION_SECRET,
        )
        return app

    def _self_chat_payload(self, text: str) -> dict:
        return {
            "event": "messages.upsert",
            "instance": "niles-wa-1",
            "data": {
                "key": {
                    "remoteJid": "435000000000@s.whatsapp.net",
                    "fromMe": True,
                },
                "message": {
                    "conversation": text,
                },
            },
        }

    async def test_self_chat_trigger_processes_and_replies(self, mock_app):
        from niles.sources.whatsapp import whatsapp_webhook

        mock_app.state.agent.process_event.return_value = "Morgen hast du 2 Termine."

        request = AsyncMock()
        request.app = mock_app
        request.json.return_value = self._self_chat_payload("Hey Niles, was steht morgen an?")

        result = await whatsapp_webhook(request, token=VALID_WEBHOOK_TOKEN)

        assert result == {"status": "processed", "trigger": "self-chat"}
        mock_app.state.agent.process_event.assert_called_once()

        event = mock_app.state.agent.process_event.call_args[0][0]
        assert event["content"] == "was steht morgen an?"
        assert event["from"] == "wa-self-435000000000"
        assert event["metadata"]["self_chat"] is True

        mock_app.state.whatsapp_action.send_message.assert_called_once_with(
            to="435000000000@s.whatsapp.net",
            text="Morgen hast du 2 Termine.",
            instance="niles-wa-1",
        )

    async def test_self_chat_without_trigger_ignored(self, mock_app):
        from niles.sources.whatsapp import whatsapp_webhook

        request = AsyncMock()
        request.app = mock_app
        request.json.return_value = self._self_chat_payload("Einkaufsliste fuer morgen")

        result = await whatsapp_webhook(request, token=VALID_WEBHOOK_TOKEN)

        assert result == {"status": "ignored", "reason": "own message without trigger"}
        mock_app.state.agent.process_event.assert_not_called()

    async def test_self_chat_only_trigger_sends_greeting(self, mock_app):
        from niles.sources.whatsapp import whatsapp_webhook

        mock_app.state.agent.process_event.return_value = "Hallo! Wie kann ich helfen?"

        request = AsyncMock()
        request.app = mock_app
        request.json.return_value = self._self_chat_payload("Hey Niles")

        result = await whatsapp_webhook(request, token=VALID_WEBHOOK_TOKEN)

        assert result == {"status": "processed", "trigger": "self-chat"}
        event = mock_app.state.agent.process_event.call_args[0][0]
        assert event["content"] == "Hallo!"

    async def test_incoming_message_never_auto_replies(self, mock_app):
        """Messages from others are acknowledged, no LLM call, no reply."""
        from niles.sources.whatsapp import whatsapp_webhook

        request = AsyncMock()
        request.app = mock_app
        request.json.return_value = {
            "event": "messages.upsert",
            "data": {
                "key": {
                    "remoteJid": "436609999999@s.whatsapp.net",
                    "fromMe": False,
                    "id": "MSG_INCOMING",
                },
                "message": {
                    "conversation": "Hallo, bist du da?",
                },
            },
        }

        result = await whatsapp_webhook(request, token=VALID_WEBHOOK_TOKEN)

        assert result == {"status": "received", "sender": "436609999999"}
        mock_app.state.agent.process_event.assert_not_called()
        mock_app.state.whatsapp_action.send_message.assert_not_called()

    async def test_echo_of_own_reply_is_ignored(self, mock_app):
        """A message ID recorded via echo guard must be skipped."""
        from niles.sources.whatsapp import whatsapp_webhook

        # Simulate: agent previously sent a message with this ID
        _echo_guard.record("ABCDEF123")

        request = AsyncMock()
        request.app = mock_app
        request.json.return_value = {
            "event": "messages.upsert",
            "instance": "niles-wa-1",
            "data": {
                "key": {
                    "remoteJid": "435000000000@s.whatsapp.net",
                    "fromMe": True,
                    "id": "ABCDEF123",
                },
                "message": {
                    "conversation": "Niles hier: dein Termin ist morgen",
                },
            },
        }

        result = await whatsapp_webhook(request, token=VALID_WEBHOOK_TOKEN)

        assert result == {"status": "ignored", "reason": "echo of own reply"}
        mock_app.state.agent.process_event.assert_not_called()

        # Cleanup
        _echo_guard._cache.clear()

    async def test_reply_records_sent_id(self, mock_app):
        """After sending a self-chat reply, the message ID is recorded."""
        from niles.sources.whatsapp import whatsapp_webhook

        _echo_guard._cache.clear()
        mock_app.state.agent.process_event.return_value = "Antwort"
        mock_app.state.whatsapp_action.send_message.return_value = {
            "key": {"id": "SENT999"},
        }

        request = AsyncMock()
        request.app = mock_app
        request.json.return_value = self._self_chat_payload("Hey Niles, test")

        await whatsapp_webhook(request, token=VALID_WEBHOOK_TOKEN)

        assert _echo_guard.is_echo("SENT999")

        # Cleanup
        _echo_guard._cache.clear()
