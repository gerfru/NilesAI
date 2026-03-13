"""Tests for WhatsAppSetupAction."""

from unittest.mock import AsyncMock

import asyncpg
import pytest

from niles.actions.whatsapp_setup import WhatsAppSetupAction


def _make_action(
    wa_store=None,
    whatsapp_action=None,
    webhook_base_url="http://niles_core:8000",
    api_key="test-api-key",
):
    return WhatsAppSetupAction(
        wa_store or AsyncMock(),
        whatsapp_action or AsyncMock(),
        webhook_base_url=webhook_base_url,
        evolution_api_key=api_key,
    )


# ---------------------------------------------------------------------------
# get_status
# ---------------------------------------------------------------------------


class TestGetStatus:
    async def test_no_session_returns_disconnected(self):
        store = AsyncMock()
        store.get_session.return_value = None
        action = _make_action(wa_store=store)

        ctx = await action.get_status(42)

        assert ctx == {"wa_status": "disconnected", "wa_phone": "", "wa_qr": ""}
        store.get_session.assert_awaited_once_with(42)

    async def test_connected_with_known_phone(self):
        store = AsyncMock()
        store.get_session.return_value = {
            "instance_name": "niles-wa-1",
            "phone_number": "436601234567",
            "status": "connected",
        }
        wa = AsyncMock()
        wa.get_connection_state.return_value = "open"
        action = _make_action(wa_store=store, whatsapp_action=wa)

        ctx = await action.get_status(1)

        assert ctx["wa_status"] == "connected"
        assert ctx["wa_phone"] == "436601234567"
        # Should NOT call get_owner_jid when phone is already known and connected
        wa.get_owner_jid.assert_not_awaited()

    async def test_discovers_phone_from_owner_jid(self):
        store = AsyncMock()
        store.get_session.return_value = {
            "instance_name": "niles-wa-1",
            "phone_number": None,
            "status": "connecting",
        }
        wa = AsyncMock()
        wa.get_connection_state.return_value = "open"
        wa.get_owner_jid.return_value = "436601234567@s.whatsapp.net"
        action = _make_action(wa_store=store, whatsapp_action=wa)

        ctx = await action.get_status(1)

        assert ctx["wa_status"] == "connected"
        assert ctx["wa_phone"] == "436601234567"
        wa.get_owner_jid.assert_awaited_once_with("niles-wa-1")
        store.update_status.assert_awaited_once_with(
            1, "connected", phone_number="436601234567"
        )

    async def test_connecting_returns_qr_code(self):
        store = AsyncMock()
        store.get_session.return_value = {
            "instance_name": "niles-wa-5",
            "phone_number": None,
            "status": "connecting",
        }
        wa = AsyncMock()
        wa.get_connection_state.return_value = "close"
        wa.get_qr_code.return_value = {"base64": "QR_DATA_HERE"}
        action = _make_action(wa_store=store, whatsapp_action=wa)

        ctx = await action.get_status(5)

        assert ctx["wa_status"] == "connecting"
        assert ctx["wa_qr"] == "QR_DATA_HERE"
        wa.get_qr_code.assert_awaited_once_with("niles-wa-5")

    async def test_stale_session_returns_disconnected(self):
        """Evolution says 'close' and DB status is not 'connecting' → stale."""
        store = AsyncMock()
        store.get_session.return_value = {
            "instance_name": "niles-wa-3",
            "phone_number": "436601234567",
            "status": "connected",
        }
        wa = AsyncMock()
        wa.get_connection_state.return_value = "close"
        action = _make_action(wa_store=store, whatsapp_action=wa)

        ctx = await action.get_status(3)

        assert ctx["wa_status"] == "disconnected"


# ---------------------------------------------------------------------------
# connect
# ---------------------------------------------------------------------------


class TestConnect:
    async def test_creates_instance_and_returns_qr(self):
        store = AsyncMock()
        wa = AsyncMock()
        wa.create_instance.return_value = {"qrcode": {"base64": "NEW_QR_CODE"}}
        action = _make_action(wa_store=store, whatsapp_action=wa)

        ctx = await action.connect(7)

        assert ctx["wa_status"] == "connecting"
        assert ctx["wa_qr"] == "NEW_QR_CODE"
        wa.create_instance.assert_awaited_once()
        store.upsert_session.assert_awaited_once_with(
            7, "niles-wa-7", status="connecting"
        )

    async def test_fallback_qr_on_existing_instance(self):
        store = AsyncMock()
        wa = AsyncMock()
        wa.create_instance.return_value = {"error": "instance already exists"}
        wa.get_qr_code.return_value = {"base64": "FALLBACK_QR"}
        action = _make_action(wa_store=store, whatsapp_action=wa)

        ctx = await action.connect(2)

        assert ctx["wa_qr"] == "FALLBACK_QR"
        wa.get_qr_code.assert_awaited_once_with("niles-wa-2")

    async def test_instance_name_uses_user_id(self):
        wa = AsyncMock()
        wa.create_instance.return_value = {"qrcode": {"base64": ""}}
        action = _make_action(whatsapp_action=wa)

        await action.connect(42)

        args = wa.create_instance.call_args
        assert args[0][0] == "niles-wa-42"

    async def test_webhook_url_construction(self):
        wa = AsyncMock()
        wa.create_instance.return_value = {"qrcode": {"base64": ""}}
        action = _make_action(
            whatsapp_action=wa,
            webhook_base_url="http://niles_core:8000/",
            api_key="my-secret",
        )

        await action.connect(1)

        args = wa.create_instance.call_args
        webhook_url = args[0][1]
        assert webhook_url == (
            "http://niles_core:8000/webhook/whatsapp?token=my-secret"
        )

    async def test_fk_violation_propagates(self):
        store = AsyncMock()
        store.upsert_session.side_effect = asyncpg.ForeignKeyViolationError(
            "insert violates FK"
        )
        wa = AsyncMock()
        wa.create_instance.return_value = {"qrcode": {"base64": ""}}
        action = _make_action(wa_store=store, whatsapp_action=wa)

        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await action.connect(999)


# ---------------------------------------------------------------------------
# disconnect
# ---------------------------------------------------------------------------


class TestDisconnect:
    async def test_orchestrates_logout_delete_cleanup(self):
        store = AsyncMock()
        store.get_session.return_value = {
            "instance_name": "niles-wa-10",
            "phone_number": "436601234567",
            "status": "connected",
        }
        wa = AsyncMock()
        action = _make_action(wa_store=store, whatsapp_action=wa)

        await action.disconnect(10)

        wa.logout_instance.assert_awaited_once_with("niles-wa-10")
        wa.delete_instance.assert_awaited_once_with("niles-wa-10")
        store.delete_session.assert_awaited_once_with(10)

    async def test_noop_when_no_session(self):
        store = AsyncMock()
        store.get_session.return_value = None
        wa = AsyncMock()
        action = _make_action(wa_store=store, whatsapp_action=wa)

        await action.disconnect(99)

        wa.logout_instance.assert_not_awaited()
        wa.delete_instance.assert_not_awaited()
        store.delete_session.assert_not_awaited()
