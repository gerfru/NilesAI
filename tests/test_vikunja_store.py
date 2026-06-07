"""Tests for per-user Vikunja credential store and agent resolution."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from niles.config import Settings
from niles.crypto import FieldEncryptor


VALID_TOKEN = "test-api-key"


def _make_settings(**overrides):
    defaults = dict(
        _env_file=None,
        postgres_password="test",
        evolution_api_key=VALID_TOKEN,
    )
    defaults.update(overrides)
    return Settings(**defaults)


class TestVikunjaCredentialStore:
    """Test VikunjaCredentialStore CRUD operations."""

    @pytest.fixture
    def store(self):
        from niles.vikunja_store import VikunjaCredentialStore

        pool = AsyncMock()
        return VikunjaCredentialStore(pool)

    async def test_get_credentials_found(self, store):
        store.pool.fetchrow.return_value = {
            "user_id": 5,
            "api_token": "tok-abc",
            "api_url": "http://vikunja:3456/api/v1",
        }
        result = await store.get_credentials(5)
        assert result == {
            "user_id": 5,
            "api_token": "tok-abc",
            "api_url": "http://vikunja:3456/api/v1",
        }

    async def test_get_credentials_not_found(self, store):
        store.pool.fetchrow.return_value = None
        result = await store.get_credentials(999)
        assert result is None

    async def test_upsert_credentials(self, store):
        await store.upsert_credentials(5, "tok-abc", "http://vikunja:3456/api/v1")
        store.pool.execute.assert_called_once()
        sql = store.pool.execute.call_args[0][0]
        assert "INSERT INTO vikunja_credentials" in sql
        assert "ON CONFLICT" in sql

    async def test_upsert_credentials_default_url(self, store):
        await store.upsert_credentials(5, "tok-abc")
        args = store.pool.execute.call_args[0]
        assert args[3] == ""  # api_url defaults to empty

    async def test_set_password_synced(self, store):
        await store.set_password_synced(5, True)
        store.pool.execute.assert_called_once()
        args = store.pool.execute.call_args[0]
        assert "password_synced" in args[0]
        assert args[1] is True
        assert args[2] == 5

    async def test_set_password_unsynced(self, store):
        await store.set_password_synced(5, False)
        args = store.pool.execute.call_args[0]
        assert args[1] is False

    async def test_delete_credentials(self, store):
        await store.delete_credentials(5)
        store.pool.execute.assert_called_once()
        sql = store.pool.execute.call_args[0][0]
        assert "DELETE FROM vikunja_credentials" in sql


class TestVikunjaCredentialStoreEncryption:
    """Test that VikunjaCredentialStore encrypts/decrypts api_token."""

    @pytest.fixture
    def enc(self):
        return FieldEncryptor(FieldEncryptor.generate_key())

    @pytest.fixture
    def store(self, enc):
        from niles.vikunja_store import VikunjaCredentialStore

        pool = AsyncMock()
        return VikunjaCredentialStore(pool, encryptor=enc)

    async def test_upsert_encrypts_token(self, store, enc):
        await store.upsert_credentials(5, "tok-secret", "http://vikunja:3456/api/v1")
        args = store.pool.execute.call_args[0]
        # args[2] = enc_token
        assert args[2].startswith("v1:")
        assert enc.decrypt(args[2]) == "tok-secret"

    async def test_get_decrypts_token(self, store, enc):
        store.pool.fetchrow.return_value = {
            "user_id": 5,
            "api_token": enc.encrypt("tok-secret"),
            "api_url": "http://vikunja:3456/api/v1",
        }
        result = await store.get_credentials(5)
        assert result["api_token"] == "tok-secret"

    async def test_get_decrypts_legacy_plaintext(self, store):
        """Pre-encryption plaintext tokens are returned as-is."""
        store.pool.fetchrow.return_value = {
            "user_id": 5,
            "api_token": "legacy-plaintext-token",
            "api_url": "",
        }
        result = await store.get_credentials(5)
        assert result["api_token"] == "legacy-plaintext-token"


class TestAgentPerUserVikunja:
    """Test that agent resolves per-user Vikunja credentials."""

    @pytest.fixture
    def vikunja_store_mock(self):
        store = AsyncMock()
        store.get_credentials.return_value = {
            "user_id": 7,
            "api_token": "user-tok-7",
            "api_url": "",
        }
        return store

    async def test_task_uses_per_user_credentials(self, vikunja_store_mock):
        """User with stored token gets a TasksAction with their credentials."""
        from niles.agent.core import NilesAgent

        agent = NilesAgent(
            config=_make_settings(
                vikunja_api_url="http://vikunja:3456/api/v1",
            ),
            contacts=AsyncMock(),
            whatsapp=AsyncMock(),
            memory=AsyncMock(),
            history=AsyncMock(),
            vikunja_store=vikunja_store_mock,
        )

        result = await agent._resolve_vikunja_tasks("web-user-7")
        assert result is not None
        assert result.api_url == "http://vikunja:3456/api/v1"
        assert result.headers == {"Authorization": "Bearer user-tok-7"}

    async def test_per_user_url_overrides_global(self, vikunja_store_mock):
        """Per-user api_url takes precedence over global config."""
        from niles.agent.core import NilesAgent

        vikunja_store_mock.get_credentials.return_value = {
            "user_id": 7,
            "api_token": "user-tok-7",
            "api_url": "http://custom:9999/api/v1",
        }

        agent = NilesAgent(
            config=_make_settings(
                vikunja_api_url="http://vikunja:3456/api/v1",
            ),
            contacts=AsyncMock(),
            whatsapp=AsyncMock(),
            memory=AsyncMock(),
            history=AsyncMock(),
            vikunja_store=vikunja_store_mock,
        )

        result = await agent._resolve_vikunja_tasks("web-user-7")
        assert result is not None
        assert result.api_url == "http://custom:9999/api/v1"

    async def test_no_credentials_returns_none(self):
        """User without stored token gets None (no global fallback)."""
        from niles.agent.core import NilesAgent

        vikunja_store = AsyncMock()
        vikunja_store.get_credentials.return_value = None

        agent = NilesAgent(
            config=_make_settings(vikunja_api_url="http://vikunja:3456/api/v1"),
            contacts=AsyncMock(),
            whatsapp=AsyncMock(),
            memory=AsyncMock(),
            history=AsyncMock(),
            vikunja_store=vikunja_store,
        )

        result = await agent._resolve_vikunja_tasks("web-user-99")
        assert result is None

    async def test_whatsapp_chat_id_returns_none(self):
        """WhatsApp users (wa-* chat_id) get None without per-user creds."""
        from niles.agent.core import NilesAgent

        vikunja_store = AsyncMock()

        agent = NilesAgent(
            config=_make_settings(vikunja_api_url="http://vikunja:3456/api/v1"),
            contacts=AsyncMock(),
            whatsapp=AsyncMock(),
            memory=AsyncMock(),
            history=AsyncMock(),
            vikunja_store=vikunja_store,
        )

        result = await agent._resolve_vikunja_tasks("wa-436601234567")
        assert result is None
        # vikunja_store should NOT be queried for wa-* chat_ids
        vikunja_store.get_credentials.assert_not_called()

    async def test_tool_execution_uses_resolved_credentials(self, vikunja_store_mock):
        """list_tasks tool call uses per-user TasksAction."""
        from niles.agent.core import NilesAgent

        agent = NilesAgent(
            config=_make_settings(
                vikunja_api_url="http://vikunja:3456/api/v1",
            ),
            contacts=AsyncMock(),
            whatsapp=AsyncMock(),
            memory=AsyncMock(),
            history=AsyncMock(),
            vikunja_store=vikunja_store_mock,
        )

        # Mock the resolved TasksAction's list_tasks method
        mock_tasks_action = AsyncMock()
        mock_tasks_action.list_tasks.return_value = [{"id": 1, "title": "Test task", "done": False}]
        agent._resolve_vikunja_tasks = AsyncMock(return_value=mock_tasks_action)

        tool_call = MagicMock()
        tool_call.id = "call_vk_1"
        tool_call.function.name = "list_tasks"
        tool_call.function.arguments = json.dumps({})

        result = await agent._execute_tool_call(tool_call, chat_id="web-user-7")
        assert result["count"] == 1
        assert result["tasks"][0]["title"] == "Test task"

    async def test_tool_execution_no_credentials_returns_error(self):
        """list_tasks without credentials returns helpful error."""
        from niles.agent.core import NilesAgent

        vikunja_store = AsyncMock()
        vikunja_store.get_credentials.return_value = None

        agent = NilesAgent(
            config=_make_settings(vikunja_api_url="http://vikunja:3456/api/v1"),
            contacts=AsyncMock(),
            whatsapp=AsyncMock(),
            memory=AsyncMock(),
            history=AsyncMock(),
            vikunja_store=vikunja_store,
        )

        tool_call = MagicMock()
        tool_call.id = "call_vk_2"
        tool_call.function.name = "list_tasks"
        tool_call.function.arguments = json.dumps({})

        result = await agent._execute_tool_call(tool_call, chat_id="web-user-99")
        assert "error" in result
        assert "Einstellungen" in result["error"]

    async def test_task_tools_hidden_when_no_api_url(self):
        """No vikunja_api_url removes task tools from tool list."""
        from niles.agent.core import NilesAgent, TOOLS

        agent = NilesAgent(
            config=_make_settings(vikunja_api_url=""),
            contacts=AsyncMock(),
            whatsapp=AsyncMock(),
            memory=AsyncMock(),
            history=AsyncMock(),
        )

        # Build tool list using the same logic as _prepare_messages
        all_tools = [t for t in TOOLS]
        if not agent.config.vikunja_api_url:
            _task_tools = {"list_tasks", "create_task", "complete_task"}
            all_tools = [t for t in all_tools if t["function"]["name"] not in _task_tools]

        tool_names = {t["function"]["name"] for t in all_tools}
        assert "list_tasks" not in tool_names
        assert "create_task" not in tool_names
        assert "complete_task" not in tool_names

    async def test_task_tools_visible_when_api_url_set(self):
        """vikunja_api_url set shows task tools even without global token."""
        from niles.agent.core import NilesAgent, TOOLS

        agent = NilesAgent(
            config=_make_settings(vikunja_api_url="http://vikunja:3456/api/v1"),
            contacts=AsyncMock(),
            whatsapp=AsyncMock(),
            memory=AsyncMock(),
            history=AsyncMock(),
        )

        all_tools = [t for t in TOOLS]
        if not agent.config.vikunja_api_url:
            _task_tools = {"list_tasks", "create_task", "complete_task"}
            all_tools = [t for t in all_tools if t["function"]["name"] not in _task_tools]

        tool_names = {t["function"]["name"] for t in all_tools}
        assert "list_tasks" in tool_names
        assert "create_task" in tool_names
        assert "complete_task" in tool_names
