"""Tests for web GUI router."""

from unittest.mock import AsyncMock, MagicMock

from niles.config import Settings
from niles.sources.web import (
    COOKIE_NAME,
    CSRF_COOKIE_NAME,
    WEB_CHAT_ID,
    _login_attempts,
    _verify_cookie,
    _verify_csrf,
    chat_clear,
    chat_page,
    chat_send,
    login_submit,
    logout,
    settings_page,
    update_setting,
)

CSRF_TOKEN = "test-csrf-token"


def _make_settings(**overrides):
    defaults = dict(
        _env_file=None,
        postgres_password="test",
        evolution_api_key="test",
        niles_api_key="test-niles-key",
    )
    defaults.update(overrides)
    return Settings(**defaults)


def _make_request(*, cookies=None, settings=None, agent=None, history=None,
                  settings_store=None, headers=None, client_ip="127.0.0.1"):
    """Build a mock Request with app.state."""
    request = MagicMock()
    request.cookies = cookies or {}
    request.headers = headers or {}
    request.app.state.settings = settings or _make_settings()
    request.app.state.agent = agent or AsyncMock()
    request.app.state.history = history or AsyncMock()
    request.app.state.settings_store = settings_store or AsyncMock()
    request.client.host = client_ip
    request.url.scheme = "http"
    return request


def _auth_cookies():
    """Cookies for an authenticated request with CSRF token."""
    return {COOKIE_NAME: "test-niles-key", CSRF_COOKIE_NAME: CSRF_TOKEN}


def _csrf_headers():
    """Headers with CSRF token."""
    return {"x-csrf-token": CSRF_TOKEN}


class TestWebAuth:
    def test_verify_cookie_valid(self):
        request = _make_request(cookies={COOKIE_NAME: "test-niles-key"})
        assert _verify_cookie(request) is True

    def test_verify_cookie_invalid(self):
        request = _make_request(cookies={COOKIE_NAME: "wrong-key"})
        assert _verify_cookie(request) is False

    def test_verify_cookie_missing(self):
        request = _make_request(cookies={})
        assert _verify_cookie(request) is False

    def test_verify_cookie_too_long(self):
        request = _make_request(cookies={COOKIE_NAME: "x" * 300})
        assert _verify_cookie(request) is False

    def test_verify_csrf_valid(self):
        request = _make_request(
            cookies={CSRF_COOKIE_NAME: CSRF_TOKEN},
            headers={"x-csrf-token": CSRF_TOKEN},
        )
        assert _verify_csrf(request) is True

    def test_verify_csrf_missing_header(self):
        request = _make_request(cookies={CSRF_COOKIE_NAME: CSRF_TOKEN})
        assert _verify_csrf(request) is False

    def test_verify_csrf_missing_cookie(self):
        request = _make_request(headers={"x-csrf-token": CSRF_TOKEN})
        assert _verify_csrf(request) is False

    def test_verify_csrf_mismatch(self):
        request = _make_request(
            cookies={CSRF_COOKIE_NAME: "token-a"},
            headers={"x-csrf-token": "token-b"},
        )
        assert _verify_csrf(request) is False

    async def test_login_submit_valid_key(self):
        request = _make_request()
        response = await login_submit(request, api_key="test-niles-key")
        assert response.status_code == 303
        assert response.headers["location"] == "/ui/chat"

    async def test_login_submit_invalid_key(self):
        request = _make_request()
        response = await login_submit(request, api_key="wrong-key")
        assert response.status_code == 401

    async def test_login_rate_limiting(self):
        """Login blocks after too many attempts from same IP."""
        _login_attempts.clear()
        request = _make_request(client_ip="10.0.0.99")
        # 5 failed attempts should exhaust the limit
        for _ in range(5):
            await login_submit(request, api_key="wrong")
        # 6th attempt should be rate-limited
        response = await login_submit(request, api_key="wrong")
        assert response.status_code == 429
        _login_attempts.clear()

    async def test_logout_clears_cookie(self):
        response = await logout()
        assert response.status_code == 303
        assert response.headers["location"] == "/ui/login"

    async def test_chat_page_redirects_without_cookie(self):
        request = _make_request(cookies={})
        response = await chat_page(request)
        assert response.status_code == 303
        assert response.headers["location"] == "/ui/login"

    async def test_settings_page_redirects_without_cookie(self):
        request = _make_request(cookies={})
        response = await settings_page(request)
        assert response.status_code == 303
        assert response.headers["location"] == "/ui/login"


class TestChatEndpoints:
    async def test_chat_send_returns_fragment(self):
        agent = AsyncMock()
        agent.process_event.return_value = "Hello from Niles"
        request = _make_request(
            cookies=_auth_cookies(),
            headers=_csrf_headers(),
            agent=agent,
        )

        await chat_send(request, message="Hi there")

        agent.process_event.assert_called_once()
        event = agent.process_event.call_args[0][0]
        assert event["type"] == "web"
        assert event["from"] == WEB_CHAT_ID
        assert event["content"] == "Hi there"

    async def test_chat_send_rejects_without_cookie(self):
        request = _make_request(cookies={})
        response = await chat_send(request, message="test")
        assert response.status_code == 401
        assert response.headers.get("HX-Redirect") == "/ui/login"

    async def test_chat_send_rejects_without_csrf(self):
        request = _make_request(
            cookies={COOKIE_NAME: "test-niles-key"},
        )
        response = await chat_send(request, message="test")
        assert response.status_code == 403

    async def test_chat_send_handles_agent_error(self):
        agent = AsyncMock()
        agent.process_event.side_effect = RuntimeError("LLM down")
        request = _make_request(
            cookies=_auth_cookies(),
            headers=_csrf_headers(),
            agent=agent,
        )
        response = await chat_send(request, message="hello")
        body = response.body.decode()
        assert "Fehler" in body

    async def test_chat_clear_calls_history_clear(self):
        history = AsyncMock()
        request = _make_request(
            cookies=_auth_cookies(),
            headers=_csrf_headers(),
            history=history,
        )

        await chat_clear(request)

        history.clear.assert_called_once_with(WEB_CHAT_ID)

    async def test_chat_clear_rejects_without_cookie(self):
        request = _make_request(cookies={})
        response = await chat_clear(request)
        assert response.status_code == 401

    async def test_chat_clear_rejects_without_csrf(self):
        request = _make_request(
            cookies={COOKIE_NAME: "test-niles-key"},
        )
        response = await chat_clear(request)
        assert response.status_code == 403

    async def test_chat_page_loads_history_paginated(self):
        history = AsyncMock()
        history.get_recent.return_value = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]
        request = _make_request(
            cookies={COOKIE_NAME: "test-niles-key"},
            history=history,
        )

        await chat_page(request)

        history.get_recent.assert_called_once_with(WEB_CHAT_ID, limit=20)


class TestSettingsEndpoints:
    async def test_update_feature_flag(self):
        settings = _make_settings()
        settings_store = AsyncMock()
        request = _make_request(
            cookies=_auth_cookies(),
            headers=_csrf_headers(),
            settings=settings,
            settings_store=settings_store,
        )

        await update_setting(request, key="feature_whatsapp_auto_reply", value="true")

        settings_store.set.assert_called_once_with("feature_whatsapp_auto_reply", True)
        # apply_overrides updates app.state.settings
        new_settings = request.app.state.settings
        assert new_settings.feature_whatsapp_auto_reply is True

    async def test_update_text_setting(self):
        settings = _make_settings()
        settings_store = AsyncMock()
        request = _make_request(
            cookies=_auth_cookies(),
            headers=_csrf_headers(),
            settings=settings,
            settings_store=settings_store,
        )

        await update_setting(request, key="llm_model", value="new-model")

        settings_store.set.assert_called_once_with("llm_model", "new-model")
        new_settings = request.app.state.settings
        assert new_settings.llm_model == "new-model"

    async def test_update_non_editable_rejected(self):
        settings_store = AsyncMock()
        settings_store.set.side_effect = ValueError("Setting 'postgres_password' is not editable at runtime")
        request = _make_request(
            cookies=_auth_cookies(),
            headers=_csrf_headers(),
            settings_store=settings_store,
        )

        response = await update_setting(request, key="postgres_password", value="hacked")

        # Should return error toast, not crash
        assert response.status_code == 200  # toast fragment always returns 200

    async def test_update_rejects_without_cookie(self):
        request = _make_request(cookies={})
        response = await update_setting(request, key="llm_model", value="test")
        assert response.status_code == 401

    async def test_update_rejects_without_csrf(self):
        request = _make_request(
            cookies={COOKIE_NAME: "test-niles-key"},
        )
        response = await update_setting(request, key="llm_model", value="test")
        assert response.status_code == 403

    async def test_settings_page_masks_passwords(self):
        settings = _make_settings(carddav_password="secret123", caldav_password="secret456")
        request = _make_request(
            cookies={COOKIE_NAME: "test-niles-key"},
            settings=settings,
        )

        response = await settings_page(request)

        body = response.body.decode()
        assert "secret123" not in body
        assert "secret456" not in body
        assert "********" in body

    async def test_settings_page_shows_not_set_for_empty_passwords(self):
        settings = _make_settings(carddav_password="", caldav_password="")
        request = _make_request(
            cookies={COOKIE_NAME: "test-niles-key"},
            settings=settings,
        )

        response = await settings_page(request)

        body = response.body.decode()
        assert "(not set)" in body
