"""MCP client manager -- starts MCP servers and exposes their tools."""

import asyncio
import json
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

# Block destructive MCP tools from being exposed to the LLM.
# A tool whose name starts with any of these prefixes (case-insensitive)
# is filtered out during discovery with a warning log.
# NOTE: This is a heuristic safety net, not strict enforcement.
# Tools with destructive verbs in non-prefix position (e.g. "bulk_remove",
# "data_wipe_all") will pass through.  For stricter control, use a
# per-server allowlist in mcp_servers.yaml.
_DESTRUCTIVE_PREFIXES = (
    "delete",
    "remove",
    "drop",
    "destroy",
    "purge",
    "erase",
    "wipe",
    "truncate",
)


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
        """Load and parse the YAML config file.

        Servers with ``enabled: "false"`` (or env-var expansion resolving to
        a falsy value) are filtered out.  Default is ``"true"`` so existing
        entries without an ``enabled`` key keep working.
        """
        if not self._config_path.exists():
            logger.info("MCP config not found at %s, no servers to start", self._config_path)
            return {}

        with open(self._config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        servers = data.get("servers", {}) or {}

        active: dict = {}
        for name, config in servers.items():
            enabled = config.pop("enabled", "true")
            if isinstance(enabled, str):
                enabled = _expand_env(enabled)
            if str(enabled).lower() not in ("true", "1", "yes"):
                logger.info("MCP server '%s' disabled via config", name)
                continue
            active[name] = config

        return active

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

        # Expand environment variables in env config.
        # Merge with current process env so subprocess inherits PYTHONPATH etc.
        if env_config:
            env = {
                **os.environ,
                **{k: _expand_env(str(v)) for k, v in env_config.items()},
            }
        else:
            env = None

        params = StdioServerParameters(command=command, args=args, env=env)

        async with asyncio.timeout(_STARTUP_TIMEOUT):
            # Enter the stdio_client context via the exit stack
            read_stream, write_stream = await self._exit_stack.enter_async_context(stdio_client(params))

            session = await self._exit_stack.enter_async_context(ClientSession(read_stream, write_stream))

            await session.initialize()
            self._sessions[name] = session

            # Discover tools
            result = await session.list_tools()

        registered = 0
        for tool in result.tools:
            if not _VALID_TOOL_NAME.match(tool.name):
                logger.warning("Skipping tool with invalid name: %s", tool.name)
                continue
            if tool.name.lower().startswith(_DESTRUCTIVE_PREFIXES):
                logger.warning(
                    "Blocking destructive MCP tool: %s/%s",
                    name,
                    tool.name,
                )
                continue
            prefixed = f"mcp{_SEP}{name}{_SEP}{tool.name}"
            self._tool_map[prefixed] = (name, tool.name)
            self._openai_tools.append(_mcp_tool_to_openai(prefixed, tool))
            registered += 1

        logger.info(
            "MCP server '%s' started (%d/%d tools registered)",
            name,
            registered,
            len(result.tools),
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

        arguments = _coerce_arguments(arguments)
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


def _coerce_arguments(arguments: dict) -> dict:
    """Fix argument types that local LLMs get wrong.

    Small models sometimes deliver values as strings instead of the correct
    type (e.g. ``"10"`` instead of ``10``, or ``"['a', 'b']"`` instead of
    ``["a", "b"]``).  This function attempts to recover the intended type.
    """
    result = {}
    for key, value in arguments.items():
        if not isinstance(value, str):
            result[key] = value
            continue
        # Try to parse stringified JSON (lists, objects, numbers, booleans, null)
        try:
            parsed = json.loads(value)
            # Only accept container types and None — plain strings that happen
            # to be valid JSON (e.g. "true", "null") are converted too.
            if isinstance(parsed, (list, dict, int, float, bool)) or parsed is None:
                result[key] = parsed
                continue
        except (json.JSONDecodeError, ValueError):
            pass
        # Python-style list literal: "['general', 'history']" → try with
        # double quotes so json.loads can handle it.
        if value.startswith("[") and value.endswith("]"):
            try:
                result[key] = json.loads(value.replace("'", '"'))
                continue
            except (json.JSONDecodeError, ValueError):
                pass
        result[key] = value
    return result


def _simplify_schema(schema: dict) -> dict:
    """Simplify a JSON Schema for better compatibility with local LLMs.

    Small models (e.g. llama3.1:8b) struggle with advanced JSON Schema
    features like ``anyOf`` nullable patterns and ``exclusiveMinimum``.
    This function flattens them into simple types that Ollama handles
    reliably.
    """
    if not isinstance(schema, dict):
        return schema

    result = {}
    for key, value in schema.items():
        if key == "anyOf" and isinstance(value, list):
            # anyOf: [{type: "string"}, {type: "null"}] → {type: "string"}
            non_null = [v for v in value if v.get("type") != "null"]
            if len(non_null) == 1:
                result.update(_simplify_schema(non_null[0]))
            else:
                result[key] = [_simplify_schema(v) for v in value]
        elif key == "exclusiveMinimum":
            # Replace exclusiveMinimum with minimum (broadly supported)
            result["minimum"] = value + 1 if isinstance(value, int) else value
        elif key == "properties" and isinstance(value, dict):
            result[key] = {k: _simplify_schema(v) for k, v in value.items()}
        elif isinstance(value, dict):
            result[key] = _simplify_schema(value)
        elif isinstance(value, list):
            result[key] = [_simplify_schema(v) if isinstance(v, dict) else v for v in value]
        else:
            result[key] = value
    return result


def _mcp_tool_to_openai(prefixed_name: str, tool: Tool) -> dict:
    """Convert an MCP Tool to OpenAI function-calling format."""
    schema = tool.inputSchema or {"type": "object", "properties": {}}
    return {
        "type": "function",
        "function": {
            "name": prefixed_name,
            "description": tool.description or "",
            "parameters": _simplify_schema(schema),
        },
    }
