"""Tests for web GUI router."""

from unittest.mock import AsyncMock, MagicMock

from niles.config import Settings
from niles.sources.web import (
    COOKIE_NAME,
    WEB_CHAT_ID,
    _verify_cookie,
    chat_clear,
    chat_page,
    chat_send,
    login_submit,
    logout,
    settings_page,
    update_setting,
)


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
                  settings_store=None):
    """Build a mock Request with app.state."""
    request = MagicMock()
    request.cookies = cookies or {}
    request.app.state.settings = settings or _make_settings()
    request.app.state.agent = agent or AsyncMock()
    request.app.state.history = history or AsyncMock()
    request.app.state.settings_store = settings_store or AsyncMock()
    return request


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

    async def test_login_submit_valid_key(self):
        request = _make_request()
        response = await login_submit(request, api_key="test-niles-key")
        assert response.status_code == 303
        assert response.headers["location"] == "/ui/chat"

    async def test_login_submit_invalid_key(self):
        request = _make_request()
        response = await login_submit(request, api_key="wrong-key")
        assert response.status_code == 401

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
            cookies={COOKIE_NAME: "test-niles-key"},
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

    async def test_chat_clear_calls_history_clear(self):
        history = AsyncMock()
        request = _make_request(
            cookies={COOKIE_NAME: "test-niles-key"},
            history=history,
        )

        await chat_clear(request)

        history.clear.assert_called_once_with(WEB_CHAT_ID)

    async def test_chat_clear_rejects_without_cookie(self):
        request = _make_request(cookies={})
        response = await chat_clear(request)
        assert response.status_code == 401

    async def test_chat_page_loads_history(self):
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

        history.get_recent.assert_called_once_with(WEB_CHAT_ID, limit=50)


class TestSettingsEndpoints:
    async def test_update_feature_flag(self):
        settings = _make_settings()
        settings_store = AsyncMock()
        request = _make_request(
            cookies={COOKIE_NAME: "test-niles-key"},
            settings=settings,
            settings_store=settings_store,
        )

        await update_setting(request, key="feature_whatsapp_auto_reply", value="true")

        settings_store.set.assert_called_once_with("feature_whatsapp_auto_reply", True)
        assert settings.feature_whatsapp_auto_reply is True

    async def test_update_text_setting(self):
        settings = _make_settings()
        settings_store = AsyncMock()
        request = _make_request(
            cookies={COOKIE_NAME: "test-niles-key"},
            settings=settings,
            settings_store=settings_store,
        )

        await update_setting(request, key="llm_model", value="new-model")

        settings_store.set.assert_called_once_with("llm_model", "new-model")
        assert settings.llm_model == "new-model"

    async def test_update_non_editable_rejected(self):
        settings_store = AsyncMock()
        settings_store.set.side_effect = ValueError("Setting 'postgres_password' is not editable at runtime")
        request = _make_request(
            cookies={COOKIE_NAME: "test-niles-key"},
            settings_store=settings_store,
        )

        response = await update_setting(request, key="postgres_password", value="hacked")

        # Should return error toast, not crash
        assert response.status_code == 200  # toast fragment always returns 200

    async def test_update_rejects_without_cookie(self):
        request = _make_request(cookies={})
        response = await update_setting(request, key="llm_model", value="test")
        assert response.status_code == 401

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
