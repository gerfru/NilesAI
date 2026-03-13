"""Tests for SignalSetupAction."""

from unittest.mock import AsyncMock


from niles.actions.signal_setup import SignalSetupAction
from niles.config import Settings


def _make_settings(**overrides):
    defaults = dict(
        _env_file=None,
        postgres_password="test",
        evolution_api_key="test",
        signal_api_url="http://signal:8080",
        signal_phone_number="",
    )
    defaults.update(overrides)
    return Settings(**defaults)


def _make_action(signal_action=None, settings_store=None):
    return SignalSetupAction(
        signal_action or AsyncMock(),
        settings_store=settings_store or AsyncMock(),
    )


# ---------------------------------------------------------------------------
# get_status
# ---------------------------------------------------------------------------


class TestGetStatus:
    async def test_known_phone_returns_connected(self):
        settings = _make_settings(signal_phone_number="+436601234567")
        action = _make_action()

        ctx = await action.get_status(settings)

        assert ctx["signal_status"] == "connected"
        assert ctx["signal_phone"] == "+436601234567"
        assert ctx["phone_discovered"] is None

    async def test_disabled_returns_disconnected_no_discovery(self):
        settings = _make_settings()
        sa = AsyncMock()
        action = _make_action(signal_action=sa)

        ctx = await action.get_status(settings, signal_disabled=True)

        assert ctx["signal_status"] == "disconnected"
        assert ctx["signal_phone"] == ""
        # Should NOT call get_accounts when disabled
        sa.get_accounts.assert_not_awaited()

    async def test_auto_discovers_phone(self):
        settings = _make_settings()
        sa = AsyncMock()
        sa.get_accounts.return_value = ["+436601234567"]
        store = AsyncMock()
        action = _make_action(signal_action=sa, settings_store=store)

        ctx = await action.get_status(settings)

        assert ctx["signal_status"] == "connected"
        assert ctx["signal_phone"] == "+436601234567"
        assert ctx["phone_discovered"] == "+436601234567"
        store.set.assert_awaited_once_with("signal_phone_number", "+436601234567")

    async def test_empty_accounts_returns_disconnected(self):
        settings = _make_settings()
        sa = AsyncMock()
        sa.get_accounts.return_value = []
        action = _make_action(signal_action=sa)

        ctx = await action.get_status(settings)

        assert ctx["signal_status"] == "disconnected"
        assert ctx["phone_discovered"] is None

    async def test_returns_phone_discovered_for_route(self):
        """phone_discovered is set only when a new phone was found."""
        settings = _make_settings()
        sa = AsyncMock()
        sa.get_accounts.return_value = ["+43123"]
        action = _make_action(signal_action=sa)

        ctx = await action.get_status(settings)
        assert ctx["phone_discovered"] == "+43123"

        # Already known — no discovery
        known = _make_settings(signal_phone_number="+43123")
        ctx2 = await action.get_status(known)
        assert ctx2["phone_discovered"] is None


# ---------------------------------------------------------------------------
# enable_linking
# ---------------------------------------------------------------------------


class TestEnableLinking:
    async def test_deletes_disabled_flag(self):
        store = AsyncMock()
        action = _make_action(settings_store=store)

        await action.enable_linking()

        store.delete.assert_awaited_once_with("signal_disabled")


# ---------------------------------------------------------------------------
# disconnect
# ---------------------------------------------------------------------------


class TestDisconnect:
    async def test_unlinks_and_clears_db(self):
        sa = AsyncMock()
        store = AsyncMock()
        action = _make_action(signal_action=sa, settings_store=store)

        await action.disconnect("+436601234567")

        sa.unlink.assert_awaited_once_with("+436601234567")
        store.delete.assert_awaited_once_with("signal_phone_number")
        store.set.assert_awaited_once_with("signal_disabled", "true")

    async def test_empty_phone_skips_unlink(self):
        sa = AsyncMock()
        store = AsyncMock()
        action = _make_action(signal_action=sa, settings_store=store)

        await action.disconnect("")

        sa.unlink.assert_not_awaited()
        # DB cleanup still happens
        store.delete.assert_awaited_once_with("signal_phone_number")
        store.set.assert_awaited_once_with("signal_disabled", "true")

    async def test_sets_disabled_flag_in_db(self):
        store = AsyncMock()
        action = _make_action(settings_store=store)

        await action.disconnect("+43123")

        store.set.assert_awaited_once_with("signal_disabled", "true")
