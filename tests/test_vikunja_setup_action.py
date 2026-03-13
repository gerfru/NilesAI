"""Tests for VikunjaSetupAction."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from niles.actions.vikunja_setup import VikunjaSetupAction


class TestValidateUrl:
    def test_valid_https(self):
        VikunjaSetupAction.validate_url("https://vikunja.example.com")

    def test_valid_http(self):
        VikunjaSetupAction.validate_url("http://vikunja.example.com")

    def test_reject_ftp(self):
        with pytest.raises(ValueError, match="scheme"):
            VikunjaSetupAction.validate_url("ftp://example.com")

    def test_reject_private_ip(self):
        with pytest.raises(ValueError, match="private IP"):
            VikunjaSetupAction.validate_url("http://192.168.1.1/api")

    def test_reject_loopback_ip(self):
        with pytest.raises(ValueError, match="private IP"):
            VikunjaSetupAction.validate_url("http://127.0.0.1:3456")

    def test_allow_docker_hostname(self):
        VikunjaSetupAction.validate_url("http://vikunja:3456")

    def test_allow_localhost_hostname(self):
        VikunjaSetupAction.validate_url("http://localhost:3456")


class TestSaveCredentials:
    @pytest.mark.asyncio
    async def test_success_returns_count(self):
        store = AsyncMock()
        response = MagicMock()
        response.json.return_value = [{"id": 1}, {"id": 2}, {"id": 3}]
        response.raise_for_status = MagicMock()
        client = AsyncMock()
        client.get.return_value = response

        action = VikunjaSetupAction(store, http_client=client, default_api_url="")
        count = await action.save_credentials(
            user_id=1, api_token="tok", api_url="https://vikunja.example.com"
        )

        assert count == 3
        store.upsert_credentials.assert_called_once_with(
            user_id=1, api_token="tok", api_url="https://vikunja.example.com"
        )

    @pytest.mark.asyncio
    async def test_uses_default_url(self):
        store = AsyncMock()
        response = MagicMock()
        response.json.return_value = [{"id": 1}]
        response.raise_for_status = MagicMock()
        client = AsyncMock()
        client.get.return_value = response

        action = VikunjaSetupAction(
            store, http_client=client, default_api_url="https://default.example.com"
        )
        count = await action.save_credentials(user_id=1, api_token="tok")

        assert count == 1
        client.get.assert_called_once_with(
            "https://default.example.com/projects",
            headers={"Authorization": "Bearer tok"},
            timeout=10,
        )
        # Default URL is only used for connection test, not persisted
        store.upsert_credentials.assert_called_once_with(
            user_id=1, api_token="tok", api_url=""
        )

    @pytest.mark.asyncio
    async def test_no_url_raises_value_error(self):
        store = AsyncMock()
        action = VikunjaSetupAction(store, http_client=AsyncMock(), default_api_url="")

        with pytest.raises(ValueError, match="Keine API-URL"):
            await action.save_credentials(user_id=1, api_token="tok")

        store.upsert_credentials.assert_not_called()

    @pytest.mark.asyncio
    async def test_connection_failure_raises(self):
        store = AsyncMock()
        client = AsyncMock()
        client.get.side_effect = Exception("Connection refused")

        action = VikunjaSetupAction(store, http_client=client, default_api_url="")

        with pytest.raises(ConnectionError, match="Verbindung fehlgeschlagen"):
            await action.save_credentials(
                user_id=1, api_token="tok", api_url="https://vikunja.example.com"
            )

        store.upsert_credentials.assert_not_called()


class TestDeleteCredentials:
    @pytest.mark.asyncio
    async def test_delegates_to_store(self):
        store = AsyncMock()
        action = VikunjaSetupAction(store, http_client=AsyncMock(), default_api_url="")

        await action.delete_credentials(user_id=42)

        store.delete_credentials.assert_called_once_with(42)


class TestGetStatus:
    @pytest.mark.asyncio
    async def test_no_credentials(self):
        store = AsyncMock()
        store.get_credentials.return_value = None
        action = VikunjaSetupAction(store, http_client=AsyncMock(), default_api_url="")

        result = await action.get_status(user_id=1)

        assert result["vikunja_connected"] is False
        assert result["vikunja_project_count"] == 0
        assert result["vikunja_error"] is None

    @pytest.mark.asyncio
    async def test_connected_with_projects(self):
        store = AsyncMock()
        store.get_credentials.return_value = {
            "api_url": "https://vikunja.example.com",
            "api_token": "tok",
        }
        response = MagicMock()
        response.json.return_value = [{"id": 1}, {"id": 2}]
        response.raise_for_status = MagicMock()
        client = AsyncMock()
        client.get.return_value = response

        action = VikunjaSetupAction(store, http_client=client, default_api_url="")

        result = await action.get_status(user_id=1)

        assert result["vikunja_connected"] is True
        assert result["vikunja_project_count"] == 2
        assert result["vikunja_error"] is None

    @pytest.mark.asyncio
    async def test_connection_error(self):
        store = AsyncMock()
        store.get_credentials.return_value = {
            "api_url": "https://vikunja.example.com",
            "api_token": "tok",
        }
        client = AsyncMock()
        client.get.side_effect = Exception("timeout")

        action = VikunjaSetupAction(store, http_client=client, default_api_url="")

        result = await action.get_status(user_id=1)

        assert result["vikunja_connected"] is True
        assert (
            result["vikunja_error"] == "Verbindung zum Vikunja-Server fehlgeschlagen."
        )

    @pytest.mark.asyncio
    async def test_no_api_url_configured(self):
        store = AsyncMock()
        store.get_credentials.return_value = {
            "api_url": "",
            "api_token": "tok",
        }
        action = VikunjaSetupAction(store, http_client=AsyncMock(), default_api_url="")

        result = await action.get_status(user_id=1)

        assert result["vikunja_connected"] is True
        assert result["vikunja_error"] == "Keine Vikunja API-URL konfiguriert."
