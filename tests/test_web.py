"""Tests for web GUI router."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

from itsdangerous import URLSafeTimedSerializer

from niles.config import Settings
from argon2.exceptions import VerifyMismatchError

from niles.sources.web import (
    CSRF_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    _get_session_user,
    _require_admin,
    _require_auth_and_csrf,
    admin_create_user,
    admin_deactivate_user,
    admin_reset_password,
    chat_clear,
    chat_page,
    chat_send,
    chat_stream,
    login_submit,
    logout,
    ollama_models,
    settings_page,
    update_setting,
)
from niles.sources.web._auth import _login_attempts
from niles.sources.web._chat import _CHAT_PAGE_SIZE
from niles.sources.web._core import _verify_csrf

CSRF_TOKEN = "test-csrf-token"
_TEST_NILES_KEY = "test-niles-key"
_TEST_SESSION_SECRET = "test-session-secret"
_TEST_USER = {
    "uid": 1,
    "email": "test@example.com",
    "display_name": "Test User",
    "avatar_url": "",
    "is_admin": True,
}
_TEST_USER_NON_ADMIN = {
    "uid": 2,
    "email": "user@example.com",
    "display_name": "Regular User",
    "avatar_url": "",
    "is_admin": False,
}


def _make_session_token(user=None, secret=_TEST_SESSION_SECRET):
    """Create a signed session token for testing."""
    serializer = URLSafeTimedSerializer(secret)
    return serializer.dumps(user or _TEST_USER)


def _make_settings(**overrides):
    defaults = dict(
        _env_file=None,
        postgres_password="test",
        evolution_api_key="test",
        niles_api_key=_TEST_NILES_KEY,
        session_secret=_TEST_SESSION_SECRET,
    )
    defaults.update(overrides)
    return Settings(**defaults)


def _make_request(
    *,
    cookies=None,
    settings=None,
    agent=None,
    history=None,
    settings_store=None,
    settings_action=None,
    admin_action=None,
    user_store=None,
    wa_store=None,
    headers=None,
    client_ip="127.0.0.1",
    http_clients=None,
):
    """Build a mock Request with app.state."""
    request = MagicMock()
    request.cookies = cookies or {}
    request.headers = headers or {}
    request.app.state.settings = settings or _make_settings()
    request.app.state.agent = agent or AsyncMock()
    request.app.state.history = history or AsyncMock()
    request.app.state.settings_store = settings_store or AsyncMock()
    request.app.state.settings_action = settings_action or AsyncMock()
    request.app.state.admin_action = admin_action or AsyncMock()
    request.app.state.user_store = user_store or AsyncMock()
    request.app.state.wa_store = wa_store
    request.app.state.vikunja_provisioner = None
    request.app.state.shutdown_event = None
    request.app.state.http_clients = http_clients or MagicMock()
    request.client.host = client_ip
    request.url.scheme = "http"
    return request


def _auth_cookies():
    """Cookies for an authenticated request with signed session + CSRF token."""
    return {SESSION_COOKIE_NAME: _make_session_token(), CSRF_COOKIE_NAME: CSRF_TOKEN}


def _session_only_cookies():
    """Cookies with only the session (no CSRF)."""
    return {SESSION_COOKIE_NAME: _make_session_token()}


def _csrf_headers():
    """Headers with CSRF token."""
    return {"x-csrf-token": CSRF_TOKEN}


class TestWebAuth:
    def test_get_session_user_valid(self):
        request = _make_request(cookies={SESSION_COOKIE_NAME: _make_session_token()})
        user = _get_session_user(request)
        assert user is not None
        assert user["uid"] == 1
        assert user["email"] == "test@example.com"

    def test_get_session_user_invalid(self):
        request = _make_request(cookies={SESSION_COOKIE_NAME: "invalid-token"})
        assert _get_session_user(request) is None

    def test_get_session_user_missing(self):
        request = _make_request(cookies={})
        assert _get_session_user(request) is None

    def test_get_session_user_too_long(self):
        request = _make_request(cookies={SESSION_COOKIE_NAME: "x" * 5000})
        assert _get_session_user(request) is None

    def test_get_session_user_wrong_secret(self):
        token = _make_session_token(secret="wrong-secret")
        request = _make_request(cookies={SESSION_COOKIE_NAME: token})
        assert _get_session_user(request) is None

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

    async def test_login_submit_valid_password(self):
        """Correct email + password → redirect to /ui/chat."""
        user_store = AsyncMock()
        user_store.has_password_users.return_value = True
        user_store.get_with_hash.return_value = {
            "id": 1,
            "email": "test@example.com",
            "display_name": "Test User",
            "avatar_url": None,
            "password_hash": "hashed",
            "auth_method": "password",
            "is_admin": True,
        }
        user_store.pool = AsyncMock()
        request = _make_request(user_store=user_store, client_ip="10.1.0.1")
        _login_attempts.clear()
        with patch("niles.sources.web._auth._ph") as mock_ph:
            mock_ph.verify.return_value = True
            response = await login_submit(request, email="test@example.com", password="correct")
        assert response.status_code == 303
        assert response.headers["location"] == "/ui/chat"
        _login_attempts.clear()

    async def test_login_submit_wrong_password(self):
        """Wrong password → 401."""
        user_store = AsyncMock()
        user_store.has_password_users.return_value = True
        user_store.get_with_hash.return_value = {
            "id": 1,
            "email": "test@example.com",
            "display_name": "Test User",
            "avatar_url": None,
            "password_hash": "hashed",
            "auth_method": "password",
            "is_admin": False,
        }
        request = _make_request(user_store=user_store, client_ip="10.1.0.2")
        _login_attempts.clear()
        with patch("niles.sources.web._auth._ph") as mock_ph:
            mock_ph.verify.side_effect = VerifyMismatchError()
            response = await login_submit(request, email="test@example.com", password="wrong")
        assert response.status_code == 401
        _login_attempts.clear()

    async def test_login_submit_unknown_email(self):
        """Non-existent email → 401 (same error as wrong password)."""
        user_store = AsyncMock()
        user_store.has_password_users.return_value = True
        user_store.get_with_hash.return_value = None
        request = _make_request(user_store=user_store, client_ip="10.1.0.3")
        _login_attempts.clear()
        with patch("niles.sources.web._auth._ph") as mock_ph:
            response = await login_submit(request, email="nobody@test.com", password="test")
        assert response.status_code == 401
        # Dummy hash called for timing defense
        mock_ph.hash.assert_called_once()
        _login_attempts.clear()

    async def test_login_submit_google_user_rejected(self):
        """Google OAuth user cannot login with password form → 401."""
        user_store = AsyncMock()
        user_store.has_password_users.return_value = True
        user_store.get_with_hash.return_value = {
            "id": 1,
            "email": "google@example.com",
            "display_name": "Google User",
            "avatar_url": None,
            "password_hash": None,
            "auth_method": "google",
            "is_admin": False,
        }
        request = _make_request(user_store=user_store, client_ip="10.1.0.4")
        _login_attempts.clear()
        with patch("niles.sources.web._auth._ph"):
            response = await login_submit(request, email="google@example.com", password="test")
        assert response.status_code == 401
        _login_attempts.clear()

    async def test_login_rate_limiting(self):
        """Login blocks after too many attempts from same IP."""
        _login_attempts.clear()
        user_store = AsyncMock()
        user_store.has_password_users.return_value = True
        user_store.get_with_hash.return_value = None
        request = _make_request(user_store=user_store, client_ip="10.0.0.99")
        with patch("niles.sources.web._auth._ph"):
            # 5 failed attempts should exhaust the limit
            for _ in range(5):
                await login_submit(request, email="x@x.com", password="wrong")
            # 6th attempt should be rate-limited
            response = await login_submit(request, email="x@x.com", password="wrong")
        assert response.status_code == 429
        _login_attempts.clear()

    async def test_logout_redirects_via_htmx(self):
        request = _make_request(headers={"hx-request": "true"})
        response = await logout(request)
        assert response.status_code == 200
        assert response.headers.get("HX-Redirect") == "/ui/login"

    async def test_logout_redirects_without_htmx(self):
        request = _make_request()
        response = await logout(request)
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

    async def test_stale_session_returns_401(self):
        """Session cookie valid but user row deleted from DB → 401 + cookie cleared."""
        user_store = AsyncMock()
        user_store.get_by_id.return_value = None  # user not in DB
        request = _make_request(
            cookies=_auth_cookies(),
            headers=_csrf_headers(),
            user_store=user_store,
        )
        user, error = await _require_auth_and_csrf(request)
        assert user is None
        assert error is not None
        assert error.status_code == 401
        assert error.headers.get("HX-Redirect") == "/ui/login"
        user_store.get_by_id.assert_awaited_once_with(1)

    async def test_valid_session_with_existing_user_passes(self):
        """Session cookie valid and user exists in DB → returns user dict."""
        user_store = AsyncMock()
        user_store.get_by_id.return_value = {
            "id": 1,
            "email": "test@example.com",
            "is_admin": True,
        }
        request = _make_request(
            cookies=_auth_cookies(),
            headers=_csrf_headers(),
            user_store=user_store,
        )
        user, error = await _require_auth_and_csrf(request)
        assert error is None
        assert user is not None
        assert user["uid"] == 1
        assert user["is_admin"] is True

    async def test_is_admin_synced_from_db(self):
        """is_admin in session cookie is overridden by DB value."""
        user_store = AsyncMock()
        # DB says admin=True, but session cookie has admin=False
        user_store.get_by_id.return_value = {
            "id": 2,
            "email": "user@example.com",
            "is_admin": True,
        }
        request = _make_request(
            cookies={
                SESSION_COOKIE_NAME: _make_session_token(_TEST_USER_NON_ADMIN),
                CSRF_COOKIE_NAME: CSRF_TOKEN,
            },
            headers=_csrf_headers(),
            user_store=user_store,
        )
        user, error = await _require_auth_and_csrf(request)
        assert error is None
        assert user["is_admin"] is True


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
        assert event["from"] == "web-user-1"
        assert event["content"] == "Hi there"

    async def test_chat_send_rejects_without_cookie(self):
        request = _make_request(cookies={})
        response = await chat_send(request, message="test")
        assert response.status_code == 401
        assert response.headers.get("HX-Redirect") == "/ui/login"

    async def test_chat_send_rejects_without_csrf(self):
        request = _make_request(cookies=_session_only_cookies())
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

        history.clear.assert_called_once_with("web-user-1")

    async def test_chat_clear_rejects_without_cookie(self):
        request = _make_request(cookies={})
        response = await chat_clear(request)
        assert response.status_code == 401

    async def test_chat_clear_rejects_without_csrf(self):
        request = _make_request(cookies=_session_only_cookies())
        response = await chat_clear(request)
        assert response.status_code == 403

    async def test_chat_page_loads_history_paginated(self):
        history = AsyncMock()
        history.get_recent.return_value = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]
        request = _make_request(
            cookies={SESSION_COOKIE_NAME: _make_session_token()},
            history=history,
        )

        await chat_page(request)

        history.get_recent.assert_called_once_with("web-user-1", limit=_CHAT_PAGE_SIZE)


class TestSettingsEndpoints:
    async def test_update_feature_flag(self):
        settings = _make_settings()
        updated = _make_settings(feature_whatsapp_send_others=False)
        settings_action = AsyncMock()
        settings_action.update.return_value = updated
        request = _make_request(
            cookies=_auth_cookies(),
            headers=_csrf_headers(),
            settings=settings,
            settings_action=settings_action,
        )

        await update_setting(request, key="feature_whatsapp_send_others", value="false")

        settings_action.update.assert_called_once_with("feature_whatsapp_send_others", "false", settings)
        assert request.app.state.settings is updated

    async def test_update_text_setting(self):
        settings = _make_settings()
        updated = _make_settings(llm_model="new-model")
        settings_action = AsyncMock()
        settings_action.update.return_value = updated
        request = _make_request(
            cookies=_auth_cookies(),
            headers=_csrf_headers(),
            settings=settings,
            settings_action=settings_action,
        )

        await update_setting(request, key="llm_model", value="new-model")

        settings_action.update.assert_called_once_with("llm_model", "new-model", settings)
        assert request.app.state.settings is updated

    async def test_update_llm_model_propagates_to_agent(self):
        agent = AsyncMock()
        updated = _make_settings(llm_model="llama3.1:8b")
        settings_action = AsyncMock()
        settings_action.update.return_value = updated
        request = _make_request(
            cookies=_auth_cookies(),
            headers=_csrf_headers(),
            settings_action=settings_action,
            agent=agent,
        )

        await update_setting(request, key="llm_model", value="llama3.1:8b")

        agent.update_llm.assert_called_once_with(model="llama3.1:8b")

    async def test_update_llm_base_url_propagates_to_agent(self):
        agent = AsyncMock()
        updated = _make_settings(llm_base_url="http://localhost:9999/v1")
        settings_action = AsyncMock()
        settings_action.update.return_value = updated
        request = _make_request(
            cookies=_auth_cookies(),
            headers=_csrf_headers(),
            settings_action=settings_action,
            agent=agent,
        )

        await update_setting(request, key="llm_base_url", value="http://localhost:9999/v1")

        agent.update_llm.assert_called_once_with(base_url="http://localhost:9999/v1")

    async def test_update_action_error_returns_toast(self):
        settings_action = AsyncMock()
        settings_action.update.side_effect = ValueError("Unbekannte Einstellung: 'postgres_password'")
        request = _make_request(
            cookies=_auth_cookies(),
            headers=_csrf_headers(),
            settings_action=settings_action,
        )

        response = await update_setting(request, key="postgres_password", value="hacked")

        # Should return error toast, not crash
        assert response.status_code == 200  # toast fragment always returns 200

    async def test_update_rejects_without_cookie(self):
        request = _make_request(cookies={})
        response = await update_setting(request, key="llm_model", value="test")
        assert response.status_code == 401

    async def test_update_rejects_without_csrf(self):
        request = _make_request(cookies=_session_only_cookies())
        response = await update_setting(request, key="llm_model", value="test")
        assert response.status_code == 403

    async def test_settings_page_masks_passwords(self):
        settings = _make_settings(carddav_password="secret123", caldav_password="secret456")
        request = _make_request(
            cookies={SESSION_COOKIE_NAME: _make_session_token()},
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
            cookies={SESSION_COOKIE_NAME: _make_session_token()},
            settings=settings,
        )

        response = await settings_page(request)

        body = response.body.decode()
        assert "(not set)" in body


class TestOllamaModelsEndpoint:
    def _admin_user_store(self):
        """User store that returns an admin user for get_by_id."""
        store = AsyncMock()
        store.get_by_id.return_value = {"is_admin": True}
        return store

    async def test_returns_options_from_ollama(self):
        settings = _make_settings(llm_model="llama3.1:8b")
        settings_action = AsyncMock()
        settings_action.list_ollama_models.return_value = [
            {"name": "llama3.1:8b", "selected": True},
            {"name": "mistral:7b", "selected": False},
            {"name": "qwen2.5:7b", "selected": False},
        ]

        request = _make_request(
            cookies=_auth_cookies(),
            settings=settings,
            user_store=self._admin_user_store(),
            settings_action=settings_action,
        )

        response = await ollama_models(request)

        body = response.body.decode()
        assert "llama3.1:8b" in body
        assert "mistral:7b" in body
        assert "qwen2.5:7b" in body
        assert "selected" in body  # current model should be selected

    async def test_returns_current_model_when_ollama_unreachable(self):
        settings = _make_settings(llm_model="llama3.1:8b")
        settings_action = AsyncMock()
        settings_action.list_ollama_models.side_effect = Exception("Connection refused")

        request = _make_request(
            cookies=_auth_cookies(),
            settings=settings,
            user_store=self._admin_user_store(),
            settings_action=settings_action,
        )

        response = await ollama_models(request)

        body = response.body.decode()
        assert "llama3.1:8b" in body
        assert "nicht erreichbar" in body

    async def test_rejects_unauthenticated(self):
        request = _make_request(cookies={})
        response = await ollama_models(request)
        assert response.status_code == 303  # redirect to login


class TestChatStreamEndpoint:
    async def test_stream_returns_sse_response(self):
        async def fake_stream(event):
            yield {"type": "chunk", "text": "Hello"}
            yield {"type": "done"}

        agent = AsyncMock()
        agent.process_event_stream = fake_stream
        request = _make_request(
            cookies=_auth_cookies(),
            headers=_csrf_headers(),
            agent=agent,
        )

        response = await chat_stream(request, message="Hi")

        assert response.media_type == "text/event-stream"
        assert response.headers.get("X-Accel-Buffering") == "no"

        # Collect SSE body
        body = b""
        async for chunk in response.body_iterator:
            body += chunk.encode() if isinstance(chunk, str) else chunk

        lines = body.decode().strip().split("\n\n")
        events = [json.loads(line.removeprefix("data: ")) for line in lines]
        assert events[0] == {"type": "chunk", "text": "Hello"}
        assert events[1] == {"type": "done"}

    async def test_stream_rejects_without_auth(self):
        request = _make_request(cookies={})
        response = await chat_stream(request, message="test")
        assert response.status_code == 401

    async def test_stream_rejects_without_csrf(self):
        request = _make_request(cookies=_session_only_cookies())
        response = await chat_stream(request, message="test")
        assert response.status_code == 403

    async def test_stream_rejects_long_message(self):
        request = _make_request(
            cookies=_auth_cookies(),
            headers=_csrf_headers(),
        )
        response = await chat_stream(request, message="x" * 2001)
        assert response.status_code == 400

    async def test_stream_handles_agent_error(self):
        async def failing_stream(event):
            raise RuntimeError("LLM down")
            yield  # make it a generator  # noqa: E303

        agent = AsyncMock()
        agent.process_event_stream = failing_stream
        request = _make_request(
            cookies=_auth_cookies(),
            headers=_csrf_headers(),
            agent=agent,
        )

        response = await chat_stream(request, message="hello")

        body = b""
        async for chunk in response.body_iterator:
            body += chunk.encode() if isinstance(chunk, str) else chunk

        events = [json.loads(line.removeprefix("data: ")) for line in body.decode().strip().split("\n\n")]
        # Should contain error message and done event
        assert any("Fehler" in e.get("text", "") for e in events)
        assert events[-1]["type"] == "done"


def _admin_cookies():
    """Session cookies for an admin user."""
    return {
        SESSION_COOKIE_NAME: _make_session_token(_TEST_USER),
        CSRF_COOKIE_NAME: CSRF_TOKEN,
    }


def _non_admin_cookies():
    """Session cookies for a non-admin user."""
    return {
        SESSION_COOKIE_NAME: _make_session_token(_TEST_USER_NON_ADMIN),
        CSRF_COOKIE_NAME: CSRF_TOKEN,
    }


class TestAdminEndpoints:
    """Tests for admin user-management endpoints."""

    async def test_require_admin_passes_for_admin(self):
        user_store = AsyncMock()
        user_store.get_by_id.return_value = {
            "id": 1,
            "email": "test@example.com",
            "is_admin": True,
        }
        request = _make_request(
            cookies=_admin_cookies(),
            headers=_csrf_headers(),
            user_store=user_store,
        )
        user, error = await _require_admin(request)
        assert error is None
        assert user is not None
        assert user["is_admin"] is True

    async def test_require_admin_rejects_non_admin(self):
        user_store = AsyncMock()
        user_store.get_by_id.return_value = {
            "id": 2,
            "email": "user@example.com",
            "is_admin": False,
        }
        request = _make_request(
            cookies=_non_admin_cookies(),
            headers=_csrf_headers(),
            user_store=user_store,
        )
        user, error = await _require_admin(request)
        assert user is None
        assert error is not None
        assert error.status_code == 403

    async def test_admin_create_user_success(self):
        user_store = AsyncMock()
        user_store.get_by_id.return_value = {
            "id": 1,
            "email": "admin@test.com",
            "is_admin": True,
        }
        admin_action = AsyncMock()
        admin_action.create_user.return_value = {
            "id": 3,
            "email": "new@test.com",
            "display_name": "New User",
        }
        admin_action.list_users.return_value = []
        request = _make_request(
            cookies=_admin_cookies(),
            headers=_csrf_headers(),
            user_store=user_store,
            admin_action=admin_action,
        )
        response = await admin_create_user(
            request,
            email="new@test.com",
            display_name="New User",
            password="secure1234",
        )
        assert response.status_code == 200
        admin_action.create_user.assert_awaited_once_with("new@test.com", "New User", "secure1234")

    async def test_admin_create_user_short_password(self):
        user_store = AsyncMock()
        user_store.get_by_id.return_value = {
            "id": 1,
            "email": "admin@test.com",
            "is_admin": True,
        }
        admin_action = AsyncMock()
        admin_action.create_user.side_effect = ValueError("Passwort muss mindestens 12 Zeichen lang sein.")
        admin_action.list_users.return_value = []
        request = _make_request(
            cookies=_admin_cookies(),
            headers=_csrf_headers(),
            user_store=user_store,
            admin_action=admin_action,
        )
        response = await admin_create_user(request, email="x@test.com", display_name="X", password="short")
        assert response.status_code == 400

    async def test_admin_create_user_duplicate_email(self):
        user_store = AsyncMock()
        user_store.get_by_id.return_value = {
            "id": 1,
            "email": "admin@test.com",
            "is_admin": True,
        }
        admin_action = AsyncMock()
        from niles.actions.admin import DuplicateEmailError

        admin_action.create_user.side_effect = DuplicateEmailError("E-Mail 'dup@test.com' ist bereits vergeben.")
        admin_action.list_users.return_value = []
        request = _make_request(
            cookies=_admin_cookies(),
            headers=_csrf_headers(),
            user_store=user_store,
            admin_action=admin_action,
        )
        response = await admin_create_user(request, email="dup@test.com", display_name="Dup", password="secure1234")
        assert response.status_code == 409

    async def test_admin_create_user_rejects_non_admin(self):
        user_store = AsyncMock()
        user_store.get_by_id.return_value = {
            "id": 2,
            "email": "user@test.com",
            "is_admin": False,
        }
        request = _make_request(
            cookies=_non_admin_cookies(),
            headers=_csrf_headers(),
            user_store=user_store,
        )
        response = await admin_create_user(request, email="x@test.com", display_name="X", password="secure1234")
        assert response.status_code == 403

    async def test_admin_deactivate_user_success(self):
        user_store = AsyncMock()
        user_store.get_by_id.return_value = {
            "id": 1,
            "email": "admin@test.com",
            "is_admin": True,
        }
        admin_action = AsyncMock()
        request = _make_request(
            cookies=_admin_cookies(),
            headers=_csrf_headers(),
            user_store=user_store,
            admin_action=admin_action,
        )
        response = await admin_deactivate_user(request, user_id=5)
        assert response.status_code == 200
        admin_action.deactivate_user.assert_awaited_once_with(5, 1)

    async def test_admin_deactivate_self_rejected(self):
        user_store = AsyncMock()
        user_store.get_by_id.return_value = {
            "id": 1,
            "email": "admin@test.com",
            "is_admin": True,
        }
        admin_action = AsyncMock()
        admin_action.deactivate_user.side_effect = ValueError("Eigenen Account kann man nicht deaktivieren.")
        request = _make_request(
            cookies=_admin_cookies(),
            headers=_csrf_headers(),
            user_store=user_store,
            admin_action=admin_action,
        )
        response = await admin_deactivate_user(request, user_id=1)
        assert response.status_code == 400

    async def test_admin_reset_password_success(self):
        user_store = AsyncMock()
        user_store.get_by_id.return_value = {
            "id": 1,
            "email": "admin@test.com",
            "is_admin": True,
        }
        admin_action = AsyncMock()
        request = _make_request(
            cookies=_admin_cookies(),
            headers=_csrf_headers(),
            user_store=user_store,
            admin_action=admin_action,
        )
        response = await admin_reset_password(request, user_id=5, password="newpassword123")
        assert response.status_code == 200
        admin_action.reset_password.assert_awaited_once_with(5, "newpassword123")

    async def test_admin_reset_password_short(self):
        user_store = AsyncMock()
        user_store.get_by_id.return_value = {
            "id": 1,
            "email": "admin@test.com",
            "is_admin": True,
        }
        admin_action = AsyncMock()
        admin_action.reset_password.side_effect = ValueError("Passwort muss mindestens 12 Zeichen lang sein.")
        request = _make_request(
            cookies=_admin_cookies(),
            headers=_csrf_headers(),
            user_store=user_store,
            admin_action=admin_action,
        )
        response = await admin_reset_password(request, user_id=5, password="short")
        assert response.status_code == 400
