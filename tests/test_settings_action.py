"""Tests for SettingsAction."""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from niles.actions.settings import SettingsAction
from niles.config import Settings


def _make_settings(**overrides):
    defaults = dict(
        _env_file=None,
        postgres_password="test",
        evolution_api_key="test",
        niles_api_key="test-key",
        session_secret="test-secret",
    )
    defaults.update(overrides)
    return Settings(**defaults)


class TestSettingsActionUpdate:
    @pytest.mark.asyncio
    async def test_update_text_setting(self):
        store = AsyncMock()
        action = SettingsAction(store, http_client=AsyncMock())
        settings = _make_settings()

        new_settings = await action.update("llm_model", "llama3.2:3b", settings)

        store.set.assert_called_once_with("llm_model", "llama3.2:3b")
        assert new_settings.llm_model == "llama3.2:3b"

    @pytest.mark.asyncio
    async def test_update_feature_bool_true(self):
        store = AsyncMock()
        action = SettingsAction(store, http_client=AsyncMock())
        settings = _make_settings()

        new_settings = await action.update(
            "feature_whatsapp_send_others", "true", settings
        )

        store.set.assert_called_once_with("feature_whatsapp_send_others", True)
        assert new_settings.feature_whatsapp_send_others is True

    @pytest.mark.asyncio
    async def test_update_feature_bool_false(self):
        store = AsyncMock()
        action = SettingsAction(store, http_client=AsyncMock())
        settings = _make_settings()

        new_settings = await action.update(
            "feature_whatsapp_send_others", "false", settings
        )

        store.set.assert_called_once_with("feature_whatsapp_send_others", False)
        assert new_settings.feature_whatsapp_send_others is False

    @pytest.mark.asyncio
    async def test_update_unknown_key_raises(self):
        store = AsyncMock()
        action = SettingsAction(store, http_client=AsyncMock())
        settings = _make_settings()

        with pytest.raises(ValueError, match="Unbekannte Einstellung"):
            await action.update("nonexistent_key", "value", settings)

        store.set.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_propagates_store_error(self):
        store = AsyncMock()
        store.set.side_effect = ValueError("Not editable")
        action = SettingsAction(store, http_client=AsyncMock())
        settings = _make_settings()

        with pytest.raises(ValueError, match="Not editable"):
            await action.update("llm_model", "test", settings)


class TestSettingsActionOllamaModels:
    @pytest.mark.asyncio
    async def test_list_models_success(self):
        response = MagicMock()
        response.json.return_value = {
            "models": [
                {"name": "llama3.1:8b"},
                {"name": "codestral:latest"},
            ]
        }
        response.raise_for_status = MagicMock()
        client = AsyncMock()
        client.get.return_value = response
        action = SettingsAction(AsyncMock(), http_client=client)

        models = await action.list_ollama_models(
            "http://localhost:11434/v1", "llama3.1:8b"
        )

        assert len(models) == 2
        # Sorted alphabetically
        assert models[0] == {"name": "codestral:latest", "selected": False}
        assert models[1] == {"name": "llama3.1:8b", "selected": True}
        # /v1 stripped from URL
        client.get.assert_called_once_with("http://localhost:11434/api/tags", timeout=5)

    @pytest.mark.asyncio
    async def test_list_models_empty(self):
        response = MagicMock()
        response.json.return_value = {"models": []}
        response.raise_for_status = MagicMock()
        client = AsyncMock()
        client.get.return_value = response
        action = SettingsAction(AsyncMock(), http_client=client)

        models = await action.list_ollama_models(
            "http://localhost:11434", "llama3.1:8b"
        )

        assert models == []

    @pytest.mark.asyncio
    async def test_list_models_connection_error(self):
        client = AsyncMock()
        client.get.side_effect = httpx.ConnectError("Connection refused")
        action = SettingsAction(AsyncMock(), http_client=client)

        with pytest.raises(httpx.ConnectError):
            await action.list_ollama_models("http://localhost:11434", "llama3.1:8b")
