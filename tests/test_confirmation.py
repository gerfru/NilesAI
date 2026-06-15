"""Tests for the tool confirmation pattern (prompt injection defense)."""

import time
from unittest.mock import AsyncMock

import pytest

from niles.config import Settings


def _make_settings(**overrides):
    defaults = dict(
        _env_file=None,
        postgres_password="test",
        evolution_api_key="test-api-key",
    )
    defaults.update(overrides)
    return Settings(**defaults)


def _make_context_builder(**overrides):
    """Create a ContextBuilder with minimal mocks."""
    from niles.agent.context import ContextBuilder

    defaults = dict(
        config=_make_settings(),
        contacts=AsyncMock(),
        whatsapp=AsyncMock(),
        memory=AsyncMock(),
        history=AsyncMock(),
        base_prompt="test prompt",
    )
    defaults.update(overrides)
    return ContextBuilder(**defaults)


class TestHandleConfirmation:
    """Test the confirmation flow in ContextBuilder."""

    async def test_no_pending_returns_none(self):
        ctx = _make_context_builder()
        result = await ctx.handle_confirmation("chat-1", "ja")
        assert result is None

    async def test_accept_executes_whatsapp(self):
        ctx = _make_context_builder()
        ctx.whatsapp.send_message.return_value = {"status": "sent"}
        ctx._pending_confirmations["chat-1"] = {
            "action": "send_whatsapp",
            "params": {"to": "436601234", "text": "Hello", "instance": None},
            "display": "WhatsApp an Max: Hello",
            "expires_at": time.monotonic() + 300,
        }
        result = await ctx.handle_confirmation("chat-1", "ja")
        assert "gesendet" in result
        ctx.whatsapp.send_message.assert_called_once_with(to="436601234", text="Hello", instance=None)
        assert "chat-1" not in ctx._pending_confirmations

    async def test_accept_yes_also_works(self):
        ctx = _make_context_builder()
        ctx.whatsapp.send_message.return_value = {"status": "sent"}
        ctx._pending_confirmations["chat-1"] = {
            "action": "send_whatsapp",
            "params": {"to": "436601234", "text": "Hi", "instance": None},
            "display": "test",
            "expires_at": time.monotonic() + 300,
        }
        result = await ctx.handle_confirmation("chat-1", "yes")
        assert "gesendet" in result

    async def test_reject_cancels(self):
        ctx = _make_context_builder()
        ctx._pending_confirmations["chat-1"] = {
            "action": "send_whatsapp",
            "params": {"to": "436601234", "text": "Hi", "instance": None},
            "display": "test",
            "expires_at": time.monotonic() + 300,
        }
        result = await ctx.handle_confirmation("chat-1", "nein")
        assert result == "Aktion abgebrochen."
        assert "chat-1" not in ctx._pending_confirmations

    async def test_reject_no_also_works(self):
        ctx = _make_context_builder()
        ctx._pending_confirmations["chat-1"] = {
            "action": "send_whatsapp",
            "params": {"to": "1234", "text": "X", "instance": None},
            "display": "test",
            "expires_at": time.monotonic() + 300,
        }
        result = await ctx.handle_confirmation("chat-1", "no")
        assert result == "Aktion abgebrochen."

    async def test_expired_returns_none(self):
        ctx = _make_context_builder()
        ctx._pending_confirmations["chat-1"] = {
            "action": "send_whatsapp",
            "params": {"to": "1234", "text": "X", "instance": None},
            "display": "test",
            "expires_at": time.monotonic() - 1,  # already expired
        }
        result = await ctx.handle_confirmation("chat-1", "ja")
        assert result is None
        assert "chat-1" not in ctx._pending_confirmations

    async def test_unrecognized_input_clears_and_returns_none(self):
        ctx = _make_context_builder()
        ctx._pending_confirmations["chat-1"] = {
            "action": "send_whatsapp",
            "params": {"to": "1234", "text": "X", "instance": None},
            "display": "test",
            "expires_at": time.monotonic() + 300,
        }
        result = await ctx.handle_confirmation("chat-1", "Was meinst du?")
        assert result is None
        assert "chat-1" not in ctx._pending_confirmations

    async def test_signal_confirmation(self):
        signal_mock = AsyncMock()
        signal_mock.send_message.return_value = {"status": "sent"}
        # Sending to others must be enabled — the same gate is re-applied at replay.
        ctx = _make_context_builder(
            signal=signal_mock,
            config=_make_settings(feature_signal_send_others=True),
        )
        ctx._pending_confirmations["chat-1"] = {
            "action": "send_signal",
            "params": {"to": "+436601234", "text": "Signal msg"},
            "display": "Signal an Max",
            "expires_at": time.monotonic() + 300,
        }
        result = await ctx.handle_confirmation("chat-1", "ok")
        assert "gesendet" in result

    async def test_replay_re_applies_feature_gate(self):
        """Security (W12): the send-others gate is re-checked at confirmation
        replay, so a flag disabled after confirming blocks the send."""
        ctx = _make_context_builder(config=_make_settings(feature_whatsapp_send_others=False))
        ctx._pending_confirmations["chat-1"] = {
            "action": "send_whatsapp",
            "params": {"to": "436601234", "text": "Hi", "instance": None},
            "display": "x",
            "expires_at": time.monotonic() + 300,
        }
        result = await ctx.handle_confirmation("chat-1", "ja")
        assert "Fehler beim Senden" in result
        ctx.whatsapp.send_message.assert_not_called()

    async def test_create_event_confirmation(self):
        cal_mgr = AsyncMock()
        cal_mgr.create_event.return_value = {"status": "created"}
        ctx = _make_context_builder(calendar_manager=cal_mgr)
        ctx._pending_confirmations["chat-1"] = {
            "action": "create_event",
            "params": {
                "source": {"id": 1, "name": "Test"},
                "summary": "Meeting",
                "dtstart_str": "2026-06-10T14:00",
                "dtend_str": None,
                "description": "",
                "location": "",
            },
            "display": "Termin: Meeting am 2026-06-10T14:00",
            "expires_at": time.monotonic() + 300,
        }
        result = await ctx.handle_confirmation("chat-1", "j")
        assert "erstellt" in result


class TestSendWhatsAppConfirmation:
    """Test that send_whatsapp returns confirmation instead of sending."""

    @pytest.fixture
    def ctx(self):
        from niles.agent.tools import ToolContext

        return ToolContext(
            config=_make_settings(feature_whatsapp_send_others=True),
            contacts=AsyncMock(),
            whatsapp=AsyncMock(),
            signal=None,
            signal_store=None,
            memory=AsyncMock(),
            calendar=None,
            calendar_manager=None,
            vikunja_store=None,
            wa_store=None,
            mcp=None,
            resolve_contact_phone=AsyncMock(return_value=("436601234", None)),
            resolve_wa_instance=AsyncMock(return_value=None),
            resolve_vikunja=AsyncMock(return_value=None),
            get_own_phone_number=AsyncMock(return_value="436609999"),
            pending_phone_choices={},
            pending_confirmations={},
        )

    async def test_sends_to_others_returns_confirm(self, ctx):
        from niles.agent.tools.whatsapp import handle_send_whatsapp

        result = await handle_send_whatsapp({"to": "436601234", "text": "Hello"}, "chat-1", ctx)
        assert "confirm" in result
        assert "chat-1" in ctx.pending_confirmations
        assert ctx.pending_confirmations["chat-1"]["action"] == "send_whatsapp"

    async def test_sends_to_self_no_confirm(self, ctx):
        from niles.agent.tools.whatsapp import handle_send_whatsapp

        # Own number matches
        ctx.get_own_phone_number = AsyncMock(return_value="436601234")
        ctx.whatsapp.send_message.return_value = {"status": "sent"}
        result = await handle_send_whatsapp({"to": "436601234", "text": "Note to self"}, "chat-1", ctx)
        assert "status" in result
        assert result["status"] == "sent"
        assert "chat-1" not in ctx.pending_confirmations


class TestSendSignalConfirmation:
    """Test that send_signal returns confirmation instead of sending."""

    async def test_sends_to_others_returns_confirm(self):
        from niles.agent.tools import ToolContext
        from niles.agent.tools.signal import handle_send_signal

        ctx = ToolContext(
            config=_make_settings(
                feature_signal_send_others=True,
                signal_phone_number="+436609999",
            ),
            contacts=AsyncMock(),
            whatsapp=AsyncMock(),
            signal=AsyncMock(),
            signal_store=None,
            memory=AsyncMock(),
            calendar=None,
            calendar_manager=None,
            vikunja_store=None,
            wa_store=None,
            mcp=None,
            resolve_contact_phone=AsyncMock(return_value=("436601234", None)),
            resolve_wa_instance=AsyncMock(return_value=None),
            resolve_vikunja=AsyncMock(return_value=None),
            get_own_phone_number=AsyncMock(return_value=None),
            pending_phone_choices={},
            pending_confirmations={},
        )
        result = await handle_send_signal({"to": "+436601234", "text": "Hello via Signal"}, "chat-1", ctx)
        assert "confirm" in result
        assert ctx.pending_confirmations["chat-1"]["action"] == "send_signal"
