"""Tests for WhatsApp chat history fetching from Evolution API."""

import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from niles.sources.web._chat import _fetch_wa_history


def _make_raw_msg(text: str, ts: int | None = None, from_me: bool = True) -> dict:
    """Build a message dict matching WhatsAppAction.fetch_messages() output."""
    return {
        "from_me": from_me,
        "text": text,
        "timestamp": int(time.time()) if ts is None else ts,
        "push_name": "Test",
    }


@pytest.fixture()
def wa_action():
    """WhatsAppAction mock with configurable fetch_messages return."""
    action = AsyncMock()
    action.fetch_messages = AsyncMock(return_value=[])
    return action


class TestFetchWaHistory:
    @pytest.mark.asyncio
    async def test_empty_messages(self, wa_action):
        messages, has_more = await _fetch_wa_history(wa_action, "436601234567", "niles-wa-1")
        assert messages == []
        assert has_more is False
        wa_action.fetch_messages.assert_awaited_once_with("436601234567@s.whatsapp.net", instance="niles-wa-1")

    @pytest.mark.asyncio
    async def test_trigger_message_is_user_role(self, wa_action):
        wa_action.fetch_messages.return_value = [
            _make_raw_msg("Hey Niles, wie wird das Wetter?", ts=1000),
        ]
        messages, _ = await _fetch_wa_history(wa_action, "436601234567", "inst")

        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "wie wird das Wetter?"

    @pytest.mark.asyncio
    async def test_non_trigger_message_is_assistant_role(self, wa_action):
        wa_action.fetch_messages.return_value = [
            _make_raw_msg("Das Wetter wird sonnig, 22 Grad.", ts=1000),
        ]
        messages, _ = await _fetch_wa_history(wa_action, "436601234567", "inst")

        assert len(messages) == 1
        assert messages[0]["role"] == "assistant"
        assert messages[0]["content"] == "Das Wetter wird sonnig, 22 Grad."

    @pytest.mark.asyncio
    async def test_mixed_conversation(self, wa_action):
        wa_action.fetch_messages.return_value = [
            _make_raw_msg("Hey Niles, wie wird das Wetter?", ts=1000),
            _make_raw_msg("Das Wetter wird sonnig.", ts=1001),
            _make_raw_msg("Niles, Termin morgen?", ts=1002),
            _make_raw_msg("Morgen hast du keine Termine.", ts=1003),
        ]
        messages, _ = await _fetch_wa_history(wa_action, "436601234567", "inst", limit=20)

        assert len(messages) == 4
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"
        assert messages[2]["role"] == "user"
        assert messages[3]["role"] == "assistant"

    @pytest.mark.asyncio
    async def test_briefing_message_is_assistant(self, wa_action):
        wa_action.fetch_messages.return_value = [
            _make_raw_msg("Guten Morgen! Keine Termine heute.", ts=1000),
        ]
        messages, _ = await _fetch_wa_history(wa_action, "436601234567", "inst")

        assert len(messages) == 1
        assert messages[0]["role"] == "assistant"

    @pytest.mark.asyncio
    async def test_timestamp_conversion(self, wa_action):
        ts = 1780749563
        wa_action.fetch_messages.return_value = [
            _make_raw_msg("Test", ts=ts),
        ]
        messages, _ = await _fetch_wa_history(wa_action, "436601234567", "inst")

        expected = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        assert messages[0]["timestamp"] == expected

    @pytest.mark.asyncio
    async def test_zero_timestamp(self, wa_action):
        wa_action.fetch_messages.return_value = [
            _make_raw_msg("Test", ts=0),
        ]
        messages, _ = await _fetch_wa_history(wa_action, "436601234567", "inst")

        assert messages[0]["timestamp"] == ""

    @pytest.mark.asyncio
    async def test_pagination_first_page(self, wa_action):
        # 5 messages, page size 2 → first page = last 2
        wa_action.fetch_messages.return_value = [_make_raw_msg(f"msg-{i}", ts=1000 + i) for i in range(5)]
        messages, has_more = await _fetch_wa_history(wa_action, "436601234567", "inst", limit=2, offset=0)

        assert len(messages) == 2
        assert has_more is True
        # Offset 0 → newest 2 messages (msg-3, msg-4)
        assert messages[0]["content"] == "msg-3"
        assert messages[1]["content"] == "msg-4"

    @pytest.mark.asyncio
    async def test_pagination_second_page(self, wa_action):
        wa_action.fetch_messages.return_value = [_make_raw_msg(f"msg-{i}", ts=1000 + i) for i in range(5)]
        messages, has_more = await _fetch_wa_history(wa_action, "436601234567", "inst", limit=2, offset=2)

        assert len(messages) == 2
        assert has_more is True
        assert messages[0]["content"] == "msg-1"
        assert messages[1]["content"] == "msg-2"

    @pytest.mark.asyncio
    async def test_pagination_last_page(self, wa_action):
        wa_action.fetch_messages.return_value = [_make_raw_msg(f"msg-{i}", ts=1000 + i) for i in range(5)]
        messages, has_more = await _fetch_wa_history(wa_action, "436601234567", "inst", limit=2, offset=4)

        assert len(messages) == 1
        assert has_more is False
        assert messages[0]["content"] == "msg-0"

    @pytest.mark.asyncio
    async def test_pagination_beyond_end(self, wa_action):
        wa_action.fetch_messages.return_value = [
            _make_raw_msg("msg", ts=1000),
        ]
        messages, has_more = await _fetch_wa_history(wa_action, "436601234567", "inst", limit=20, offset=5)

        assert messages == []
        assert has_more is False

    @pytest.mark.asyncio
    async def test_empty_text_skipped(self, wa_action):
        wa_action.fetch_messages.return_value = [
            _make_raw_msg("", ts=1000),
            _make_raw_msg("Real message", ts=1001),
        ]
        messages, _ = await _fetch_wa_history(wa_action, "436601234567", "inst")

        assert len(messages) == 1
        assert messages[0]["content"] == "Real message"

    @pytest.mark.asyncio
    async def test_trigger_only_message(self, wa_action):
        """'Hey Niles' without further text → show original."""
        wa_action.fetch_messages.return_value = [
            _make_raw_msg("Hey Niles", ts=1000),
        ]
        messages, _ = await _fetch_wa_history(wa_action, "436601234567", "inst")

        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        # strip_trigger returns "" for just "Hey Niles", fallback to original
        assert messages[0]["content"] == "Hey Niles"

    @pytest.mark.asyncio
    async def test_jid_construction(self, wa_action):
        """Phone number should be formatted as JID for Evolution API."""
        await _fetch_wa_history(wa_action, "4366012345678", "niles-wa-1")

        wa_action.fetch_messages.assert_awaited_once_with("4366012345678@s.whatsapp.net", instance="niles-wa-1")
