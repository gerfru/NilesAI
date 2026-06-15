"""Auth-guard and basic behavior tests for untested web route handlers.

Tests verify that unauthenticated / non-admin requests are rejected and
that happy-path calls invoke the correct app.state actions.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg
import httpx
from itsdangerous import URLSafeTimedSerializer

from niles.config import Settings
from niles.sources.web._admin import (
    admin_create_user,
    admin_deactivate_user,
    admin_delete_user,
    admin_reset_password,
    admin_users_page,
)
from niles.sources.web._briefing import briefing_test
from niles.sources.web._calendar import (
    calendar_source_add,
    calendar_source_remove,
    calendar_source_sync,
    calendar_sources_list,
)
from niles.sources.web._contacts import (
    contacts_connect,
    contacts_disconnect,
    contacts_status,
    contacts_sync,
)
from niles.sources.web._core import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME
from niles.sources.web._signal import signal_disconnect, signal_link, signal_qrcode, signal_status
from niles.sources.web._vikunja import vikunja_connect, vikunja_disconnect, vikunja_status
from niles.sources.web._weather import weather_location_remove, weather_location_search, weather_location_set
from niles.sources.web._whatsapp import whatsapp_connect, whatsapp_disconnect, whatsapp_status

_SECRET = "test-session-secret"  # pragma: allowlist secret
_CSRF = "test-csrf-token"

_USER = {"uid": 1, "email": "u@t.com", "display_name": "U", "avatar_url": "", "is_admin": False}
_ADMIN = {"uid": 1, "email": "a@t.com", "display_name": "A", "avatar_url": "", "is_admin": True}

# DB-row dicts returned by user_store.get_by_id (schema differs from session dict)
_DB_USER = {"id": 1, "email": "u@t.com", "display_name": "U", "avatar_url": "", "is_admin": False}
_DB_ADMIN = {"id": 1, "email": "a@t.com", "display_name": "A", "avatar_url": "", "is_admin": True}


def _settings(**kw):
    d = dict(
        _env_file=None,
        postgres_password="test",  # pragma: allowlist secret
        evolution_api_key="test",  # pragma: allowlist secret
        niles_api_key="test-key",  # pragma: allowlist secret
        session_secret=_SECRET,  # pragma: allowlist secret
    )
    d.update(kw)
    return Settings(**d)


def _token(user=None):
    return URLSafeTimedSerializer(_SECRET).dumps(user or _USER)


def _admin_token():
    return _token(_ADMIN)


def _req(*, cookies=None, headers=None, db_user=None, **state_kw):
    """Build mock Request with app.state extras.

    db_user: dict returned by user_store.get_by_id (controls is_admin refresh).
    """
    r = MagicMock()
    r.cookies = cookies or {}
    r.headers = headers or {}
    r.app.state.settings = _settings()
    r.app.state.agent = AsyncMock()
    r.app.state.history = AsyncMock()
    r.app.state.settings_store = AsyncMock()
    r.app.state.settings_action = AsyncMock()
    r.app.state.admin_action = AsyncMock()
    user_store = AsyncMock()
    user_store.get_by_id.return_value = db_user
    r.app.state.user_store = user_store
    r.app.state.wa_store = None
    r.app.state.vikunja_provisioner = None
    r.app.state.shutdown_event = None
    r.app.state.http_clients = MagicMock()
    r.app.state.calendar_manager = AsyncMock()
    r.app.state.caldav = AsyncMock()
    r.app.state.contacts_action = AsyncMock()
    r.app.state.carddav_manager = AsyncMock()
    r.app.state.vikunja_setup_action = AsyncMock()
    r.app.state.wa_setup_action = AsyncMock()
    r.app.state.weather_action = AsyncMock()
    r.app.state.signal_setup_action = AsyncMock()
    r.app.state.signal_action = AsyncMock()
    r.app.state.signal_disabled = False
    r.app.state.signal_task = None
    r.client.host = "127.0.0.1"
    r.url.scheme = "http"
    for k, v in state_kw.items():
        setattr(r.app.state, k, v)
    return r


def _auth_cookies():
    return {SESSION_COOKIE_NAME: _token(), CSRF_COOKIE_NAME: _CSRF}


def _admin_cookies():
    return {SESSION_COOKIE_NAME: _admin_token(), CSRF_COOKIE_NAME: _CSRF}


def _csrf_h():
    return {"x-csrf-token": _CSRF}


def _noauth():
    return _req()


def _authed():
    return _req(cookies=_auth_cookies(), headers=_csrf_h(), db_user=_DB_USER)


def _admin():
    return _req(cookies=_admin_cookies(), headers=_csrf_h(), db_user=_DB_ADMIN)


# ---- Calendar Routes ----


class TestCalendarAuthGuards:
    async def test_sources_list_rejects_unauthenticated(self):
        resp = await calendar_sources_list(_noauth())
        assert resp.status_code == 401

    async def test_source_add_rejects_unauthenticated(self):
        resp = await calendar_source_add(
            _noauth(), source_type="ical", name="c", url="http://x", auth_user="", auth_password=""
        )
        assert resp.status_code == 401

    async def test_source_add_happy_path(self):
        r = _authed()
        r.app.state.calendar_manager.add_source.return_value = {"id": 1, "name": "cal"}
        r.app.state.calendar_manager.get_sources.return_value = [{"id": 1, "name": "cal"}]
        await calendar_source_add(r, source_type="ical", name="cal", url="http://x", auth_user="", auth_password="")
        r.app.state.calendar_manager.add_source.assert_called_once()

    async def test_source_remove_rejects_unauthenticated(self):
        resp = await calendar_source_remove(_noauth(), source_id=1)
        assert resp.status_code == 401

    async def test_source_sync_rejects_unauthenticated(self):
        resp = await calendar_source_sync(_noauth(), source_id=1)
        assert resp.status_code == 401


# ---- Contacts Routes ----


class TestContactsAuthGuards:
    async def test_status_rejects_unauthenticated(self):
        resp = await contacts_status(_noauth())
        assert resp.status_code == 401

    async def test_connect_rejects_unauthenticated(self):
        resp = await contacts_connect(_noauth(), url="http://x", username="u", password="p")
        assert resp.status_code == 401

    async def test_disconnect_rejects_unauthenticated(self):
        resp = await contacts_disconnect(_noauth(), source_id=1)
        assert resp.status_code == 401

    async def test_sync_rejects_unauthenticated(self):
        resp = await contacts_sync(_noauth(), source_id=1)
        assert resp.status_code == 401


# ---- Briefing Routes ----


class TestBriefingAuthGuards:
    async def test_briefing_test_rejects_non_admin(self):
        resp = await briefing_test(_authed(), briefing_type="daily")
        assert resp.status_code == 403

    async def test_briefing_test_rejects_unauthenticated(self):
        resp = await briefing_test(_noauth(), briefing_type="daily")
        assert resp.status_code == 401


# ---- Vikunja Routes ----


class TestVikunjaAuthGuards:
    async def test_status_rejects_unauthenticated(self):
        resp = await vikunja_status(_noauth())
        assert resp.status_code == 401

    async def test_connect_rejects_unauthenticated(self):
        resp = await vikunja_connect(_noauth(), api_token="tok", api_url="http://x")
        assert resp.status_code == 401

    async def test_disconnect_rejects_unauthenticated(self):
        resp = await vikunja_disconnect(_noauth())
        assert resp.status_code == 401

    async def test_status_uses_injected_dependency(self):
        """DI pilot: the action is injected via Depends, not read from app.state."""
        resp = await vikunja_status(_authed(), vikunja_setup=None)
        assert resp.status_code == 200
        assert "nicht verfuegbar" in resp.body.decode().lower()


# ---- WhatsApp Routes ----


class TestWhatsAppAuthGuards:
    async def test_status_rejects_unauthenticated(self):
        resp = await whatsapp_status(_noauth())
        assert resp.status_code == 401

    async def test_connect_rejects_unauthenticated(self):
        resp = await whatsapp_connect(_noauth())
        assert resp.status_code == 401

    async def test_disconnect_rejects_unauthenticated(self):
        resp = await whatsapp_disconnect(_noauth())
        assert resp.status_code == 401


# ---- Weather Routes ----


class TestWeatherAuthGuards:
    async def test_search_rejects_unauthenticated(self):
        resp = await weather_location_search(_noauth(), q="Berlin")
        assert resp.status_code == 401

    async def test_set_rejects_unauthenticated(self):
        resp = await weather_location_set(_noauth(), latitude="52.5", longitude="13.4", location_name="Berlin")
        assert resp.status_code == 401

    async def test_remove_rejects_unauthenticated(self):
        resp = await weather_location_remove(_noauth())
        assert resp.status_code == 401


# ---- Admin Routes ----


class TestAdminAuthGuards:
    async def test_users_page_rejects_non_admin(self):
        resp = await admin_users_page(_authed())
        assert resp.status_code == 303

    async def test_users_page_rejects_unauthenticated(self):
        resp = await admin_users_page(_noauth())
        assert resp.status_code == 303

    async def test_create_user_rejects_non_admin(self):
        resp = await admin_create_user(
            _authed(),
            email="x@t.com",
            display_name="X",
            password="pw",  # pragma: allowlist secret
        )
        assert resp.status_code == 403

    async def test_reset_password_rejects_non_admin(self):
        resp = await admin_reset_password(_authed(), user_id=2, password="pw")  # pragma: allowlist secret
        assert resp.status_code == 403

    async def test_deactivate_user_rejects_non_admin(self):
        resp = await admin_deactivate_user(_authed(), user_id=2)
        assert resp.status_code == 403

    async def test_delete_user_rejects_non_admin(self):
        resp = await admin_delete_user(_authed(), user_id=2)
        assert resp.status_code == 403

    async def test_create_user_happy_path(self):
        r = _admin()
        r.app.state.admin_action.create_user.return_value = {
            "id": 2,
            "email": "x@t.com",
            "display_name": "X",
        }
        r.app.state.admin_action.list_users.return_value = []
        await admin_create_user(r, email="x@t.com", display_name="X", password="pw123456")  # pragma: allowlist secret
        r.app.state.admin_action.create_user.assert_called_once()

    async def test_deactivate_user_happy_path(self):
        r = _admin()
        r.app.state.admin_action.deactivate_user.return_value = True
        await admin_deactivate_user(r, user_id=2)
        r.app.state.admin_action.deactivate_user.assert_called_once()


# ---- Signal Routes (previously untested) ----


class TestSignalRoutes:
    async def test_status_not_configured(self):
        r = _admin()
        r.app.state.signal_setup_action = None
        resp = await signal_status(r)
        assert "nicht konfiguriert" in resp.body.decode().lower()

    async def test_status_happy_path(self):
        r = _admin()
        r.app.state.signal_setup_action.get_status = AsyncMock(
            return_value={"signal_status": "connected", "signal_phone": "+4366"}
        )
        resp = await signal_status(r)
        assert resp.status_code == 200
        r.app.state.signal_setup_action.get_status.assert_awaited_once()

    async def test_qrcode_no_action(self):
        r = _admin()
        r.app.state.signal_action = None
        resp = await signal_qrcode(r)
        assert resp.status_code == 404

    async def test_qrcode_unavailable(self):
        r = _admin()
        r.app.state.signal_action.get_qr_link = AsyncMock(return_value=None)
        resp = await signal_qrcode(r)
        assert resp.status_code == 502

    async def test_qrcode_happy_path(self):
        r = _admin()
        r.app.state.signal_action.get_qr_link = AsyncMock(return_value=b"PNGDATA")
        resp = await signal_qrcode(r)
        assert resp.status_code == 200
        assert resp.media_type == "image/png"

    async def test_link_happy_path(self):
        r = _admin()
        resp = await signal_link(r)
        assert resp.status_code == 200
        r.app.state.signal_setup_action.enable_linking.assert_awaited_once()
        assert r.app.state.signal_disabled is False

    async def test_link_rejects_non_admin(self):
        resp = await signal_link(_authed())
        assert resp.status_code == 403

    async def test_disconnect_happy_path(self):
        r = _admin()
        resp = await signal_disconnect(r)
        assert resp.status_code == 200
        r.app.state.signal_setup_action.disconnect.assert_awaited_once()
        assert r.app.state.signal_disabled is True


# ---- Weather Routes (happy / error paths) ----


class TestWeatherBehaviour:
    async def test_search_returns_results(self):
        r = _authed()
        r.app.state.weather_action.search_locations = AsyncMock(
            return_value=[{"name": "Berlin", "admin1": "BE", "country": "DE", "latitude": 52.5, "longitude": 13.4}]
        )
        resp = await weather_location_search(r, q="Berlin")
        assert resp.status_code == 200
        assert "Berlin" in resp.body.decode()

    async def test_search_no_results(self):
        r = _authed()
        r.app.state.weather_action.search_locations = AsyncMock(return_value=[])
        resp = await weather_location_search(r, q="Nirgendwo")
        assert "Kein Ergebnis" in resp.body.decode()

    async def test_search_http_error(self):
        r = _authed()
        r.app.state.weather_action.search_locations = AsyncMock(side_effect=httpx.HTTPError("boom"))
        resp = await weather_location_search(r, q="Berlin")
        assert "fehlgeschlagen" in resp.body.decode()

    async def test_set_happy_path(self):
        r = _authed()
        r.app.state.weather_action.set_location = AsyncMock(return_value=_settings())
        resp = await weather_location_set(r, latitude="52.5", longitude="13.4", location_name="Berlin")
        assert resp.status_code == 200
        r.app.state.weather_action.set_location.assert_awaited_once()

    async def test_set_invalid_returns_toast(self):
        r = _authed()
        r.app.state.weather_action.set_location = AsyncMock(side_effect=ValueError("ungueltig"))
        resp = await weather_location_set(r, latitude="x", longitude="y", location_name="")
        assert "ungueltig" in resp.body.decode()

    async def test_remove_happy_path(self):
        r = _authed()
        r.app.state.weather_action.remove_location = AsyncMock(return_value=_settings())
        resp = await weather_location_remove(r)
        assert resp.status_code == 200
        r.app.state.weather_action.remove_location.assert_awaited_once()


# ---- WhatsApp Routes (happy / error paths) ----


class TestWhatsAppBehaviour:
    async def test_status_unavailable(self):
        r = _authed()
        r.app.state.wa_setup_action = None
        resp = await whatsapp_status(r)
        assert "nicht verfuegbar" in resp.body.decode().lower()

    async def test_status_happy_path(self):
        r = _authed()
        r.app.state.wa_setup_action.get_status = AsyncMock(
            return_value={"wa_status": "connected", "wa_phone": "+4366", "wa_qr": ""}
        )
        resp = await whatsapp_status(r)
        assert resp.status_code == 200

    async def test_connect_happy_path(self):
        r = _authed()
        r.app.state.wa_setup_action.connect = AsyncMock(
            return_value={"wa_status": "connecting", "wa_phone": "", "wa_qr": "data"}
        )
        resp = await whatsapp_connect(r)
        assert resp.status_code == 200
        r.app.state.wa_setup_action.connect.assert_awaited_once()

    async def test_connect_fk_violation(self):
        r = _authed()
        r.app.state.wa_setup_action.connect = AsyncMock(side_effect=asyncpg.ForeignKeyViolationError("fk"))
        resp = await whatsapp_connect(r)
        assert resp.status_code == 401

    async def test_disconnect_happy_path(self):
        r = _authed()
        resp = await whatsapp_disconnect(r)
        assert resp.status_code == 200
        r.app.state.wa_setup_action.disconnect.assert_awaited_once()


# ---- Calendar Routes (happy paths) ----


class TestCalendarBehaviour:
    async def test_sources_list_happy_path(self):
        r = _authed()
        r.app.state.calendar_manager.get_sources.return_value = []
        resp = await calendar_sources_list(r)
        assert resp.status_code == 200
        r.app.state.calendar_manager.claim_orphan_sources.assert_awaited_once()

    async def test_remove_happy_path(self):
        r = _authed()
        r.app.state.calendar_manager.remove_source.return_value = True
        r.app.state.calendar_manager.get_sources.return_value = []
        resp = await calendar_source_remove(r, source_id=1)
        assert resp.status_code == 200
        r.app.state.calendar_manager.remove_source.assert_awaited_once()

    async def test_sync_happy_path(self):
        r = _authed()
        r.app.state.calendar_manager.sync_source.return_value = 3
        r.app.state.calendar_manager.get_sources.return_value = []
        resp = await calendar_source_sync(r, source_id=1)
        assert resp.status_code == 200
        r.app.state.calendar_manager.sync_source.assert_awaited_once()


# ---- Contacts Routes (happy paths) ----


class TestContactsBehaviour:
    def _wire(self, r):
        r.app.state.carddav_manager.get_sources.return_value = []
        r.app.state.contacts_action.get_sync_status.return_value = {"cnt": 0, "last_sync": None}

    async def test_status_happy_path(self):
        r = _authed()
        self._wire(r)
        resp = await contacts_status(r)
        assert resp.status_code == 200

    async def test_connect_happy_path(self):
        r = _authed()
        self._wire(r)
        resp = await contacts_connect(r, url="https://dav.x", username="u", password="p")
        assert resp.status_code == 200
        r.app.state.contacts_action.connect.assert_awaited_once()

    async def test_connect_error_shows_message(self):
        r = _authed()
        self._wire(r)
        r.app.state.contacts_action.connect = AsyncMock(side_effect=ConnectionError("dav kaputt"))
        resp = await contacts_connect(r, url="https://dav.x", username="u", password="p")
        assert "dav kaputt" in resp.body.decode()

    async def test_disconnect_happy_path(self):
        r = _authed()
        self._wire(r)
        resp = await contacts_disconnect(r, source_id=1)
        assert resp.status_code == 200
        r.app.state.contacts_action.disconnect.assert_awaited_once()

    async def test_sync_happy_path(self):
        r = _authed()
        self._wire(r)
        resp = await contacts_sync(r, source_id=1)
        assert resp.status_code == 200
        r.app.state.carddav_manager.sync_source.assert_awaited_once()


# ---- Briefing Route (admin happy / validation) ----


class TestBriefingBehaviour:
    async def test_unknown_type_returns_toast(self):
        resp = await briefing_test(_admin(), briefing_type="bogus")
        assert "Unbekannter Briefing-Typ" in resp.body.decode()

    async def test_daily_happy_path(self):
        with patch("niles.jobs.briefing.send_daily_briefing", new=AsyncMock(return_value=True)):
            resp = await briefing_test(_admin(), briefing_type="daily")
        assert "gesendet" in resp.body.decode()

    async def test_daily_not_sent(self):
        with patch("niles.jobs.briefing.send_daily_briefing", new=AsyncMock(return_value=False)):
            resp = await briefing_test(_admin(), briefing_type="daily")
        assert "Kein WhatsApp" in resp.body.decode()


# ---- Vikunja Routes (happy paths via injected dependency) ----


class TestVikunjaBehaviour:
    async def test_connect_happy_path(self):
        setup = AsyncMock()
        setup.save_credentials = AsyncMock(return_value=3)
        resp = await vikunja_connect(_authed(), api_token="tok", api_url="http://x", vikunja_setup=setup)
        assert resp.status_code == 200
        setup.save_credentials.assert_awaited_once()

    async def test_disconnect_happy_path(self):
        setup = AsyncMock()
        resp = await vikunja_disconnect(_authed(), vikunja_setup=setup)
        assert resp.status_code == 200
        setup.delete_credentials.assert_awaited_once()
