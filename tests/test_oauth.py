"""Tests for Google OAuth callback (callback_google) — 10 branches."""

from unittest.mock import AsyncMock, MagicMock

import httpx

from niles.config import Settings
from niles.sources.web._auth import callback_google

_TEST_SESSION_SECRET = "test-session-secret"  # pragma: allowlist secret


def _make_settings(**overrides):
    defaults = dict(
        _env_file=None,
        postgres_password="test",  # pragma: allowlist secret
        evolution_api_key="test",  # pragma: allowlist secret
        niles_api_key="test-key",  # pragma: allowlist secret
        session_secret=_TEST_SESSION_SECRET,  # pragma: allowlist secret
        google_client_id="cid",
        google_client_secret="csec",  # pragma: allowlist secret
        google_allowed_emails="allowed@test.com",
        base_url="https://niles.example.ts.net",
    )
    defaults.update(overrides)
    return Settings(**defaults)


def _make_request(*, cookies=None, settings=None, user_store=None, http_clients=None):
    request = MagicMock()
    request.cookies = cookies or {}
    request.headers = {}
    request.app.state.settings = settings or _make_settings()
    request.app.state.user_store = user_store or AsyncMock()
    request.app.state.http_clients = http_clients or MagicMock()
    request.app.state.vikunja_provisioner = None
    request.url.scheme = "http"
    request.url.hostname = "localhost"
    request.url.port = 8000
    request.base_url = "http://localhost:8000/"
    return request


def _mock_token_response(*, status=200, json_data=None):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = json_data or {"access_token": "tok123"}
    return resp


def _mock_userinfo_response(*, status=200, json_data=None):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = json_data or {
        "email": "allowed@test.com",
        "verified_email": True,
        "name": "Allowed User",
        "picture": "https://example.com/avatar.png",
    }
    return resp


class TestCallbackGoogleErrors:
    """Error-path branches (no token exchange needed)."""

    async def test_error_parameter_returns_template(self):
        """Branch 1: error query param (e.g. access_denied)."""
        request = _make_request()
        resp = await callback_google(request, code="", state="", error="access_denied")
        assert resp.status_code == 200
        assert resp.template.name == "login.html"
        assert "Zugriff verweigert" in resp.context["error"]

    async def test_error_unknown_code_returns_generic_message(self):
        request = _make_request()
        resp = await callback_google(request, code="", state="", error="server_error")
        assert "erneut versuchen" in resp.context["error"]

    async def test_csrf_state_mismatch_returns_error(self):
        """Branch 2: state doesn't match stored cookie."""
        request = _make_request(cookies={"oauth_state": "stored-state"})
        resp = await callback_google(request, code="abc", state="wrong-state", error="")
        assert "OAuth-State" in resp.context["error"]

    async def test_csrf_state_missing_returns_error(self):
        request = _make_request(cookies={})
        resp = await callback_google(request, code="abc", state="some-state", error="")
        assert "OAuth-State" in resp.context["error"]

    async def test_callback_without_base_url_returns_error(self):
        """OAuth callback without BASE_URL shows config error."""
        request = _make_request(
            cookies={"oauth_state": "valid-state"},
            settings=_make_settings(base_url=""),
        )
        resp = await callback_google(request, code="code", state="valid-state", error="")
        assert resp.status_code == 200
        assert "BASE_URL" in resp.context["error"]


class TestCallbackGoogleTokenExchange:
    """Branches involving token exchange and userinfo."""

    def _setup_request(self, *, token_resp=None, userinfo_resp=None, user_store=None, settings=None):
        google_client = AsyncMock()
        google_client.post.return_value = token_resp or _mock_token_response()
        google_client.get.return_value = userinfo_resp or _mock_userinfo_response()
        http_clients = MagicMock()
        http_clients.google_oauth = google_client

        request = _make_request(
            cookies={"oauth_state": "valid-state"},
            settings=settings or _make_settings(),
            user_store=user_store,
            http_clients=http_clients,
        )
        return request

    async def test_token_exchange_http_error_returns_template(self):
        """Branch 3: token exchange returns non-200."""
        request = self._setup_request(token_resp=_mock_token_response(status=400))
        resp = await callback_google(request, code="code", state="valid-state", error="")
        assert "Token-Austausch fehlgeschlagen" in resp.context["error"]

    async def test_userinfo_http_error_returns_template(self):
        """Branch 4: userinfo returns non-200."""
        request = self._setup_request(userinfo_resp=_mock_userinfo_response(status=500))
        resp = await callback_google(request, code="code", state="valid-state", error="")
        assert "Benutzerinformationen" in resp.context["error"]

    async def test_httpx_error_returns_template(self):
        """Branch 5: httpx.HTTPError during token exchange."""
        google_client = AsyncMock()
        google_client.post.side_effect = httpx.ConnectError("connection refused")
        http_clients = MagicMock()
        http_clients.google_oauth = google_client

        request = _make_request(
            cookies={"oauth_state": "valid-state"},
            http_clients=http_clients,
        )
        resp = await callback_google(request, code="code", state="valid-state", error="")
        assert "Verbindung zu Google fehlgeschlagen" in resp.context["error"]

    async def test_missing_email_returns_template(self):
        """Branch 6: userinfo has no email."""
        request = self._setup_request(userinfo_resp=_mock_userinfo_response(json_data={"name": "No Email"}))
        resp = await callback_google(request, code="code", state="valid-state", error="")
        assert "Keine E-Mail" in resp.context["error"]

    async def test_unverified_email_returns_template(self):
        """Branch 7: email not verified."""
        request = self._setup_request(
            userinfo_resp=_mock_userinfo_response(
                json_data={
                    "email": "unverified@test.com",
                    "verified_email": False,
                    "name": "Unverified",
                }
            )
        )
        resp = await callback_google(request, code="code", state="valid-state", error="")
        assert "nicht verifiziert" in resp.context["error"]

    async def test_email_not_in_whitelist_returns_error(self):
        """Branch 8: email not in allowed_emails."""
        request = self._setup_request(
            userinfo_resp=_mock_userinfo_response(
                json_data={
                    "email": "notallowed@test.com",
                    "verified_email": True,
                    "name": "Not Allowed",
                }
            )
        )
        resp = await callback_google(request, code="code", state="valid-state", error="")
        assert "nicht berechtigt" in resp.context["error"]

    async def test_deactivated_user_returns_403(self):
        """Branch 9: user exists but is deactivated."""
        user_store = AsyncMock()
        user_store.create_or_update.return_value = None  # deactivated
        request = self._setup_request(user_store=user_store)
        resp = await callback_google(request, code="code", state="valid-state", error="")
        assert resp.status_code == 403
        assert "deaktiviert" in resp.context["error"]

    async def test_happy_path_sets_session_and_redirects(self):
        """Branch 10: successful OAuth login."""
        user_store = AsyncMock()
        user_store.create_or_update.return_value = {
            "id": 1,
            "email": "allowed@test.com",
            "display_name": "Allowed User",
            "avatar_url": "https://example.com/avatar.png",
            "is_admin": False,
        }
        request = self._setup_request(user_store=user_store)
        resp = await callback_google(request, code="code", state="valid-state", error="")
        assert resp.status_code == 303
        assert resp.headers.get("location") == "/ui/chat"

    async def test_no_whitelist_allows_any_verified_email(self):
        """When google_allowed_emails is empty, any verified email is accepted."""
        user_store = AsyncMock()
        user_store.create_or_update.return_value = {
            "id": 2,
            "email": "anyone@test.com",
            "display_name": "Anyone",
            "avatar_url": None,
            "is_admin": False,
        }
        request = self._setup_request(
            user_store=user_store,
            settings=_make_settings(google_allowed_emails=""),
            userinfo_resp=_mock_userinfo_response(
                json_data={
                    "email": "anyone@test.com",
                    "verified_email": True,
                    "name": "Anyone",
                }
            ),
        )
        resp = await callback_google(request, code="code", state="valid-state", error="")
        assert resp.status_code == 303
