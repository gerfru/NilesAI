"""Auth-guard and basic behavior tests for untested web route handlers.

Tests verify that unauthenticated / non-admin requests are rejected and
that happy-path calls invoke the correct app.state actions.
"""

from unittest.mock import AsyncMock, MagicMock

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
