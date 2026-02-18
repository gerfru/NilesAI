"""Tests for MCP client manager and agent integration."""

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from niles.mcp.client import MCPManager, _expand_env, _mcp_tool_to_openai


class TestExpandEnv:
    def test_expands_existing_var(self, monkeypatch):
        monkeypatch.setenv("TEST_VAR", "hello")
        assert _expand_env("${TEST_VAR}") == "hello"

    def test_expands_missing_var_to_empty(self, monkeypatch):
        monkeypatch.delenv("NONEXISTENT_VAR", raising=False)
        assert _expand_env("${NONEXISTENT_VAR}") == ""

    def test_expands_multiple_vars(self, monkeypatch):
        monkeypatch.setenv("A", "foo")
        monkeypatch.setenv("B", "bar")
        assert _expand_env("${A}/${B}") == "foo/bar"

    def test_leaves_plain_text(self):
        assert _expand_env("no vars here") == "no vars here"


class TestMCPToolToOpenAI:
    def test_converts_tool(self):
        mock_tool = MagicMock()
        mock_tool.description = "A test tool"
        mock_tool.inputSchema = {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        }

        result = _mcp_tool_to_openai("mcp__test__search", mock_tool)

        assert result["type"] == "function"
        assert result["function"]["name"] == "mcp__test__search"
        assert result["function"]["description"] == "A test tool"
        assert result["function"]["parameters"]["properties"]["query"]["type"] == "string"

    def test_handles_none_description(self):
        mock_tool = MagicMock()
        mock_tool.description = None
        mock_tool.inputSchema = {"type": "object", "properties": {}}

        result = _mcp_tool_to_openai("mcp__s__t", mock_tool)
        assert result["function"]["description"] == ""

    def test_handles_none_schema(self):
        mock_tool = MagicMock()
        mock_tool.description = "test"
        mock_tool.inputSchema = None

        result = _mcp_tool_to_openai("mcp__s__t", mock_tool)
        assert result["function"]["parameters"] == {"type": "object", "properties": {}}


class TestMCPManagerConfig:
    def test_load_empty_config(self, tmp_path):
        config = tmp_path / "mcp.yaml"
        config.write_text("servers: {}\n")

        manager = MCPManager(config_path=config)
        servers = manager._load_config()
        assert servers == {}

    def test_load_missing_config(self, tmp_path):
        manager = MCPManager(config_path=tmp_path / "nonexistent.yaml")
        servers = manager._load_config()
        assert servers == {}

    def test_load_config_with_servers(self, tmp_path):
        config = tmp_path / "mcp.yaml"
        config.write_text(
            "servers:\n"
            "  myserver:\n"
            "    command: echo\n"
            "    args: [hello]\n"
        )

        manager = MCPManager(config_path=config)
        servers = manager._load_config()
        assert "myserver" in servers
        assert servers["myserver"]["command"] == "echo"
        assert servers["myserver"]["args"] == ["hello"]

    def test_load_null_servers(self, tmp_path):
        config = tmp_path / "mcp.yaml"
        config.write_text("servers:\n")

        manager = MCPManager(config_path=config)
        servers = manager._load_config()
        assert servers == {}


class TestMCPManagerTools:
    def test_get_openai_tools_empty(self):
        manager = MCPManager()
        assert manager.get_openai_tools() == []

    def test_is_mcp_tool_false(self):
        manager = MCPManager()
        assert not manager.is_mcp_tool("find_contact")
        assert not manager.is_mcp_tool("mcp__unknown__tool")

    def test_is_mcp_tool_true(self):
        manager = MCPManager()
        manager._tool_map["mcp__server__tool"] = ("server", "tool")
        assert manager.is_mcp_tool("mcp__server__tool")


class TestMCPManagerLifecycle:
    async def test_start_all_empty_config(self, tmp_path):
        config = tmp_path / "mcp.yaml"
        config.write_text("servers: {}\n")

        manager = MCPManager(config_path=config)
        await manager.start_all()

        assert len(manager._sessions) == 0
        assert len(manager.get_openai_tools()) == 0

        await manager.stop_all()

    async def test_stop_all_clears_state(self):
        manager = MCPManager()
        manager._sessions["test"] = MagicMock()
        manager._tool_map["mcp__test__t"] = ("test", "t")
        manager._openai_tools.append({"type": "function"})

        await manager.stop_all()

        assert len(manager._sessions) == 0
        assert len(manager._tool_map) == 0
        assert len(manager._openai_tools) == 0


class TestMCPManagerCallTool:
    async def test_call_tool_success(self):
        manager = MCPManager()

        mock_session = AsyncMock()
        mock_content = MagicMock()
        mock_content.text = "result text"
        mock_result = MagicMock()
        mock_result.isError = False
        mock_result.content = [mock_content]
        mock_session.call_tool.return_value = mock_result

        manager._sessions["myserver"] = mock_session
        manager._tool_map["mcp__myserver__mytool"] = ("myserver", "mytool")

        result = await manager.call_tool("mcp__myserver__mytool", {"key": "value"})

        assert result == "result text"
        mock_session.call_tool.assert_called_once_with(
            name="mytool", arguments={"key": "value"}
        )

    async def test_call_tool_error(self):
        manager = MCPManager()

        mock_session = AsyncMock()
        mock_content = MagicMock()
        mock_content.text = "something went wrong"
        mock_result = MagicMock()
        mock_result.isError = True
        mock_result.content = [mock_content]
        mock_session.call_tool.return_value = mock_result

        manager._sessions["srv"] = mock_session
        manager._tool_map["mcp__srv__fail"] = ("srv", "fail")

        result = await manager.call_tool("mcp__srv__fail", {})
        assert "Error:" in result


class TestAgentMCPDispatch:
    async def test_agent_dispatches_mcp_tool(self):
        from niles.agent.core import NilesAgent
        from niles.config import Settings

        settings = Settings(
            postgres_password="test",
            evolution_api_key="test",
            niles_api_key="test",
        )

        mock_mcp = MagicMock()
        mock_mcp.is_mcp_tool.return_value = True
        mock_mcp.call_tool = AsyncMock(return_value="mcp result")

        agent = NilesAgent(
            config=settings,
            contacts=MagicMock(),
            whatsapp=MagicMock(),
            memory=MagicMock(),
            history=MagicMock(),
            mcp_manager=mock_mcp,
        )

        tool_call = MagicMock()
        tool_call.function.name = "mcp__server__tool"
        tool_call.function.arguments = '{"arg": "val"}'
        tool_call.id = "call_123"

        result = await agent._execute_tool_call(tool_call)

        assert result == {"result": "mcp result"}
        mock_mcp.call_tool.assert_called_once_with("mcp__server__tool", {"arg": "val"})

    async def test_agent_ignores_mcp_for_builtin(self):
        from niles.agent.core import NilesAgent
        from niles.config import Settings

        settings = Settings(
            postgres_password="test",
            evolution_api_key="test",
            niles_api_key="test",
        )

        mock_mcp = MagicMock()
        mock_mcp.is_mcp_tool.return_value = False
        mock_mcp.get_openai_tools.return_value = []

        mock_memory = AsyncMock()
        mock_memory.set = AsyncMock()

        agent = NilesAgent(
            config=settings,
            contacts=MagicMock(),
            whatsapp=MagicMock(),
            memory=mock_memory,
            history=MagicMock(),
            mcp_manager=mock_mcp,
        )

        tool_call = MagicMock()
        tool_call.function.name = "remember"
        tool_call.function.arguments = '{"key": "test", "value": "hello"}'
        tool_call.id = "call_456"

        result = await agent._execute_tool_call(tool_call)

        assert result == {"status": "saved", "key": "test"}
        mock_mcp.call_tool.assert_not_called()
