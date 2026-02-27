"""Tests for Vikunja auto-provisioning."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from niles.vikunja_provisioning import VikunjaProvisioner


@pytest.fixture
def store():
    s = AsyncMock()
    s.get_credentials.return_value = None
    return s


@pytest.fixture
def provisioner(store):
    return VikunjaProvisioner(
        api_url="http://vikunja:3456/api/v1",
        session_secret="test-secret-key-for-hmac",
        store=store,
    )


class TestDerivePassword:
    def test_deterministic(self, provisioner):
        """Same inputs always produce the same password."""
        p1 = provisioner._derive_password(1, "user@example.com")
        p2 = provisioner._derive_password(1, "user@example.com")
        assert p1 == p2

    def test_different_users_different_passwords(self, provisioner):
        """Different user_ids produce different passwords."""
        p1 = provisioner._derive_password(1, "user@example.com")
        p2 = provisioner._derive_password(2, "user@example.com")
        assert p1 != p2

    def test_password_length(self, provisioner):
        """Password is 24 characters."""
        p = provisioner._derive_password(1, "user@example.com")
        assert len(p) == 24


class TestDeriveUsername:
    def test_basic(self):
        assert (
            VikunjaProvisioner._derive_username(1, "gerhard@example.com") == "gerhard_1"
        )

    def test_strips_dots_and_plus(self):
        assert (
            VikunjaProvisioner._derive_username(2, "ger.hard+test@gmail.com")
            == "gerhardtest_2"
        )

    def test_truncates_long_prefix(self):
        username = VikunjaProvisioner._derive_username(3, "a" * 30 + "@example.com")
        assert username == "a" * 20 + "_3"


class TestEnsureProvisioned:
    @pytest.mark.asyncio
    async def test_already_provisioned(self, provisioner, store):
        """If credentials exist, return True immediately."""
        store.get_credentials.return_value = {"api_token": "tk_existing"}
        result = await provisioner.ensure_provisioned(1, "user@example.com")
        assert result is True
        store.upsert_credentials.assert_not_called()

    @pytest.mark.asyncio
    async def test_full_provisioning_flow(self, provisioner, store):
        """Register → Login → Create Token → Store."""
        provisioner._register = AsyncMock()
        provisioner._login = AsyncMock(return_value="jwt-token-123")
        provisioner._create_api_token = AsyncMock(return_value="tk_new_token")

        result = await provisioner.ensure_provisioned(1, "user@example.com")
        assert result is True
        provisioner._register.assert_called_once()
        provisioner._login.assert_called_once()
        provisioner._create_api_token.assert_called_once_with("jwt-token-123")
        store.upsert_credentials.assert_called_once_with(
            1, "tk_new_token", "http://vikunja:3456/api/v1"
        )

    @pytest.mark.asyncio
    async def test_login_fails_returns_false(self, provisioner, store):
        """If login fails, return False."""
        provisioner._register = AsyncMock()
        provisioner._login = AsyncMock(return_value=None)

        result = await provisioner.ensure_provisioned(1, "user@example.com")
        assert result is False
        store.upsert_credentials.assert_not_called()

    @pytest.mark.asyncio
    async def test_token_creation_fails_returns_false(self, provisioner, store):
        """If token creation fails, return False."""
        provisioner._register = AsyncMock()
        provisioner._login = AsyncMock(return_value="jwt-123")
        provisioner._create_api_token = AsyncMock(return_value=None)

        result = await provisioner.ensure_provisioned(1, "user@example.com")
        assert result is False
        store.upsert_credentials.assert_not_called()


class TestRegister:
    @pytest.mark.asyncio
    async def test_success(self, provisioner):
        """Successful registration completes without raising."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("niles.vikunja_provisioning.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post.return_value = (
                mock_resp
            )
            await provisioner._register("user_1", "user@example.com", "pass")

    @pytest.mark.asyncio
    async def test_user_exists(self, provisioner):
        """400 (user exists) is tolerated without raising."""
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = "user already exists"

        with patch("niles.vikunja_provisioning.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post.return_value = (
                mock_resp
            )
            await provisioner._register("user_1", "user@example.com", "pass")

    @pytest.mark.asyncio
    async def test_connection_error(self, provisioner):
        """Network error is swallowed (logged, not raised)."""
        with patch("niles.vikunja_provisioning.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post.side_effect = (
                ConnectionError("unreachable")
            )
            await provisioner._register("user_1", "user@example.com", "pass")


class TestLogin:
    @pytest.mark.asyncio
    async def test_success(self, provisioner):
        """Successful login returns JWT token."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"token": "jwt-abc-123"}

        with patch("niles.vikunja_provisioning.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post.return_value = (
                mock_resp
            )
            result = await provisioner._login("user_1", "pass")
            assert result == "jwt-abc-123"

    @pytest.mark.asyncio
    async def test_bad_credentials(self, provisioner):
        """403 returns None."""
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.text = "Invalid credentials"

        with patch("niles.vikunja_provisioning.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post.return_value = (
                mock_resp
            )
            result = await provisioner._login("user_1", "wrong-pass")
            assert result is None


class TestCreateApiToken:
    @pytest.mark.asyncio
    async def test_success(self, provisioner):
        """Successful token creation returns tk_... token."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "id": 1,
            "token": "tk_new_persistent_token",
            "title": "Niles Auto-Provisioned",
        }

        with patch("niles.vikunja_provisioning.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.put.return_value = (
                mock_resp
            )
            result = await provisioner._create_api_token("jwt-123")
            assert result == "tk_new_persistent_token"

    @pytest.mark.asyncio
    async def test_failure(self, provisioner):
        """Non-200 returns None."""
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.text = "Unauthorized"

        with patch("niles.vikunja_provisioning.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.put.return_value = (
                mock_resp
            )
            result = await provisioner._create_api_token("expired-jwt")
            assert result is None
