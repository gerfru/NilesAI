"""Tests for MessageDispatch — the unified send-policy + send (W12)."""

from unittest.mock import AsyncMock

from niles.actions.message_dispatch import SEND_OTHERS_DISABLED, MessageDispatch
from niles.config import Settings


def _settings(**overrides):
    defaults = dict(
        _env_file=None,
        postgres_password="test",  # pragma: allowlist secret
        evolution_api_key="test",  # pragma: allowlist secret
    )
    defaults.update(overrides)
    return Settings(**defaults)


async def _no_own(chat_id):
    return None


def _dispatch(config, *, whatsapp=None, signal=None, own=_no_own):
    return MessageDispatch(config, whatsapp or AsyncMock(), signal, get_own_phone_number=own)


class TestPolicy:
    async def test_signal_self_allowed(self):
        d = _dispatch(_settings(signal_phone_number="+43111"))
        is_self, allowed = await d.policy("signal", "+43111", "c")
        assert is_self and allowed

    async def test_signal_other_blocked_when_flag_off(self):
        d = _dispatch(_settings(feature_signal_send_others=False))
        is_self, allowed = await d.policy("signal", "+43999", "c")
        assert not is_self and not allowed

    async def test_signal_other_allowed_when_flag_on(self):
        d = _dispatch(_settings(feature_signal_send_others=True))
        _, allowed = await d.policy("signal", "+43999", "c")
        assert allowed

    async def test_whatsapp_self_via_own_number(self):
        async def own(c):
            return "436601234"

        d = _dispatch(_settings(feature_whatsapp_send_others=False), own=own)
        is_self, allowed = await d.policy("whatsapp", "436601234", "c")
        assert is_self and allowed

    async def test_whatsapp_other_blocked_when_flag_off(self):
        d = _dispatch(_settings(feature_whatsapp_send_others=False))
        is_self, allowed = await d.policy("whatsapp", "436609999", "c")
        assert not is_self and not allowed


class TestSend:
    async def test_send_signal_blocked_returns_error_without_sending(self):
        signal = AsyncMock()
        d = _dispatch(_settings(feature_signal_send_others=False), signal=signal)
        out = await d.send_signal(to="+43999", text="hi")
        assert out == {"error": SEND_OTHERS_DISABLED}
        signal.send_message.assert_not_called()

    async def test_send_signal_not_configured(self):
        d = _dispatch(_settings(), signal=None)
        assert "error" in await d.send_signal(to="+43999", text="hi")

    async def test_send_whatsapp_blocked_returns_error_without_sending(self):
        wa = AsyncMock()
        d = _dispatch(_settings(feature_whatsapp_send_others=False), whatsapp=wa)
        out = await d.send_whatsapp(to="436609999", text="hi", instance=None, chat_id="c")
        assert out == {"error": SEND_OTHERS_DISABLED}
        wa.send_message.assert_not_called()

    async def test_send_whatsapp_allowed_calls_action(self):
        wa = AsyncMock()
        wa.send_message.return_value = {"status": "sent"}
        d = _dispatch(_settings(feature_whatsapp_send_others=True), whatsapp=wa)
        out = await d.send_whatsapp(to="436609999", text="hi", instance="inst", chat_id="c")
        assert out == {"status": "sent"}
        wa.send_message.assert_called_once_with(to="436609999", text="hi", instance="inst")
