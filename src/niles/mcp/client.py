"""MCP client manager -- starts MCP servers and exposes their tools."""

import asyncio
import logging
import os
import re
from contextlib import AsyncExitStack
from pathlib import Path

import yaml
from mcp import ClientSession, StdioServerParameters, stdio_client
from mcp.types import Tool

logger = logging.getLogger(__name__)

# Separator between server name and tool name in prefixed tool names
_SEP = "__"
_STARTUP_TIMEOUT = 30  # seconds
_VALID_TOOL_NAME = re.compile(r"^[a-zA-Z0-9_-]+$")


def _expand_env(value: str) -> str:
    """Expand ${VAR} references in a string using os.environ."""

    def _replacer(match: re.Match) -> str:
        var_name = match.group(1)
        if var_name not in os.environ:
            logger.warning("Environment variable ${%s} not set, using empty string", var_name)
        return os.environ.get(var_name, "")

    return re.sub(r"\$\{(\w+)\}", _replacer, value)


class MCPManager:
    """Manages MCP server connections and tool discovery."""

    def __init__(self, config_path: str | Path = "config/mcp_servers.yaml"):
        self._config_path = Path(config_path)
        self._exit_stack = AsyncExitStack()
        # server_name -> ClientSession
        self._sessions: dict[str, ClientSession] = {}
        # prefixed_tool_name -> (server_name, original_tool_name)
        self._tool_map: dict[str, tuple[str, str]] = {}
        # cached OpenAI-format tool definitions
        self._openai_tools: list[dict] = []

    def _load_config(self) -> dict:
        """Load and parse the YAML config file."""
        if not self._config_path.exists():
            logger.info("MCP config not found at %s, no servers to start", self._config_path)
            return {}

        with open(self._config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        return data.get("servers", {}) or {}

    async def start_all(self) -> None:
        """Start all configured MCP servers and discover their tools."""
        servers = self._load_config()

        if not servers:
            logger.info("No MCP servers configured")
            return

        for name, config in servers.items():
            try:
                await self._start_server(name, config)
            except Exception:
                logger.exception("Failed to start MCP server '%s'", name)

        tool_count = len(self._tool_map)
        server_count = len(self._sessions)
        logger.info("MCP: %d server(s) started, %d tool(s) available", server_count, tool_count)

    async def _start_server(self, name: str, config: dict) -> None:
        """Start a single MCP server and register its tools."""
        command = config.get("command", "")
        args = config.get("args", [])
        env_config = config.get("env", {})

        # Expand environment variables in env config
        env = {k: _expand_env(str(v)) for k, v in env_config.items()} if env_config else None

        params = StdioServerParameters(command=command, args=args, env=env)

        async with asyncio.timeout(_STARTUP_TIMEOUT):
            # Enter the stdio_client context via the exit stack
            read_stream, write_stream = await self._exit_stack.enter_async_context(
                stdio_client(params)
            )

            session = await self._exit_stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )

            await session.initialize()
            self._sessions[name] = session

            # Discover tools
            result = await session.list_tools()

        for tool in result.tools:
            if not _VALID_TOOL_NAME.match(tool.name):
                logger.warning("Skipping tool with invalid name: %s", tool.name)
                continue
            prefixed = f"mcp{_SEP}{name}{_SEP}{tool.name}"
            self._tool_map[prefixed] = (name, tool.name)
            self._openai_tools.append(_mcp_tool_to_openai(prefixed, tool))

        logger.info(
            "MCP server '%s' started (%d tools)", name, len(result.tools)
        )

    def get_openai_tools(self) -> list[dict]:
        """Return MCP tools in OpenAI function-calling format."""
        return self._openai_tools

    def is_mcp_tool(self, name: str) -> bool:
        """Check if a tool name is an MCP tool."""
        return name in self._tool_map

    async def call_tool(self, prefixed_name: str, arguments: dict) -> str:
        """Call an MCP tool by its prefixed name and return the result as text."""
        server_name, tool_name = self._tool_map[prefixed_name]
        session = self._sessions[server_name]

        result = await session.call_tool(name=tool_name, arguments=arguments)

        texts = []
        for c in result.content:
            if hasattr(c, "text"):
                texts.append(c.text)
            else:
                logger.debug("Skipping non-text content item: %s", type(c).__name__)

        if result.isError:
            return f"Error: {' '.join(texts)}" if texts else "Error: unknown MCP error"

        return "\n".join(texts) if texts else ""

    async def stop_all(self) -> None:
        """Shut down all MCP server connections."""
        await self._exit_stack.aclose()
        self._sessions.clear()
        self._tool_map.clear()
        self._openai_tools.clear()
        logger.info("MCP: all servers stopped")


def _mcp_tool_to_openai(prefixed_name: str, tool: Tool) -> dict:
    """Convert an MCP Tool to OpenAI function-calling format."""
    return {
        "type": "function",
        "function": {
            "name": prefixed_name,
            "description": tool.description or "",
            "parameters": tool.inputSchema or {"type": "object", "properties": {}},
        },
    }
