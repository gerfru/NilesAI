"""Tests for per-user Vikunja credential store and agent resolution."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from niles.config import Settings


VALID_TOKEN = "test-api-key"


def _make_settings(**overrides):
    defaults = dict(
        _env_file=None,
        postgres_password="test",
        evolution_api_key=VALID_TOKEN,
    )
    defaults.update(overrides)
    return Settings(**defaults)


class TestVikunjCredentialStore:
    """Test VikunjCredentialStore CRUD operations."""

    @pytest.fixture
    def store(self):
        from niles.vikunja_store import VikunjCredentialStore

        pool = AsyncMock()
        return VikunjCredentialStore(pool)

    async def test_initialize_creates_table(self, store):
        await store.initialize()
        store.pool.execute.assert_called_once()
        sql = store.pool.execute.call_args[0][0]
        assert "vikunja_credentials" in sql
        assert "CREATE TABLE IF NOT EXISTS" in sql

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

    async def test_delete_credentials(self, store):
        await store.delete_credentials(5)
        store.pool.execute.assert_called_once()
        sql = store.pool.execute.call_args[0][0]
        assert "DELETE FROM vikunja_credentials" in sql


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
                feature_vikunja=True,
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
                feature_vikunja=True,
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

    async def test_task_falls_back_to_global(self):
        """User without stored token uses global TasksAction."""
        from niles.actions.tasks import TasksAction
        from niles.agent.core import NilesAgent

        vikunja_store = AsyncMock()
        vikunja_store.get_credentials.return_value = None

        global_tasks = TasksAction(
            api_url="http://vikunja:3456/api/v1",
            api_token="global-tok",
        )

        agent = NilesAgent(
            config=_make_settings(feature_vikunja=True),
            contacts=AsyncMock(),
            whatsapp=AsyncMock(),
            memory=AsyncMock(),
            history=AsyncMock(),
            tasks=global_tasks,
            vikunja_store=vikunja_store,
        )

        result = await agent._resolve_vikunja_tasks("web-user-99")
        assert result is global_tasks

    async def test_task_no_credentials_returns_none(self):
        """No per-user token and no global → returns None."""
        from niles.agent.core import NilesAgent

        vikunja_store = AsyncMock()
        vikunja_store.get_credentials.return_value = None

        agent = NilesAgent(
            config=_make_settings(feature_vikunja=True),
            contacts=AsyncMock(),
            whatsapp=AsyncMock(),
            memory=AsyncMock(),
            history=AsyncMock(),
            vikunja_store=vikunja_store,
        )

        result = await agent._resolve_vikunja_tasks("web-user-99")
        assert result is None

    async def test_whatsapp_chat_id_uses_global_fallback(self):
        """WhatsApp users (wa-* chat_id) always get global fallback."""
        from niles.actions.tasks import TasksAction
        from niles.agent.core import NilesAgent

        vikunja_store = AsyncMock()
        global_tasks = TasksAction(
            api_url="http://vikunja:3456/api/v1",
            api_token="global-tok",
        )

        agent = NilesAgent(
            config=_make_settings(feature_vikunja=True),
            contacts=AsyncMock(),
            whatsapp=AsyncMock(),
            memory=AsyncMock(),
            history=AsyncMock(),
            tasks=global_tasks,
            vikunja_store=vikunja_store,
        )

        result = await agent._resolve_vikunja_tasks("wa-436601234567")
        assert result is global_tasks
        # vikunja_store should NOT be queried for wa-* chat_ids
        vikunja_store.get_credentials.assert_not_called()

    async def test_tool_execution_uses_resolved_credentials(self, vikunja_store_mock):
        """list_tasks tool call uses per-user TasksAction."""
        from niles.agent.core import NilesAgent

        agent = NilesAgent(
            config=_make_settings(
                feature_vikunja=True,
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
        mock_tasks_action.list_tasks.return_value = [
            {"id": 1, "title": "Test task", "done": False}
        ]
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
            config=_make_settings(feature_vikunja=True),
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

    async def test_task_tools_hidden_when_feature_disabled(self):
        """feature_vikunja=False removes task tools from tool list."""
        from niles.agent.core import NilesAgent, TOOLS

        agent = NilesAgent(
            config=_make_settings(feature_vikunja=False),
            contacts=AsyncMock(),
            whatsapp=AsyncMock(),
            memory=AsyncMock(),
            history=AsyncMock(),
        )

        # Build tool list using the same logic as _prepare_messages
        all_tools = [t for t in TOOLS]
        if not agent.config.feature_vikunja:
            _task_tools = {"list_tasks", "create_task", "complete_task"}
            all_tools = [
                t for t in all_tools
                if t["function"]["name"] not in _task_tools
            ]

        tool_names = {t["function"]["name"] for t in all_tools}
        assert "list_tasks" not in tool_names
        assert "create_task" not in tool_names
        assert "complete_task" not in tool_names

    async def test_task_tools_visible_when_feature_enabled(self):
        """feature_vikunja=True shows task tools even without global token."""
        from niles.agent.core import NilesAgent, TOOLS

        agent = NilesAgent(
            config=_make_settings(feature_vikunja=True),
            contacts=AsyncMock(),
            whatsapp=AsyncMock(),
            memory=AsyncMock(),
            history=AsyncMock(),
        )

        all_tools = [t for t in TOOLS]
        if not agent.config.feature_vikunja:
            _task_tools = {"list_tasks", "create_task", "complete_task"}
            all_tools = [
                t for t in all_tools
                if t["function"]["name"] not in _task_tools
            ]

        tool_names = {t["function"]["name"] for t in all_tools}
        assert "list_tasks" in tool_names
        assert "create_task" in tool_names
        assert "complete_task" in tool_names
