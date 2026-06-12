"""MCP tool dispatch (fallback for tools not in the built-in registry)."""

import logging

from . import ToolContext

logger = logging.getLogger(__name__)

MAX_MCP_RESULT_SIZE = 100_000  # 100 KB limit for MCP tool results


async def handle_mcp_tool(name: str, args: dict, ctx: ToolContext) -> dict:
    """Execute an MCP tool call. Called as fallback when name is not in TOOL_REGISTRY."""
    # Global MCP tools (weather, searxng, fetch, etc.)
    if ctx.mcp and ctx.mcp.is_mcp_tool(name):
        try:
            result_text = await ctx.mcp.call_tool(name, args)
            if len(result_text) > MAX_MCP_RESULT_SIZE:
                result_text = result_text[:MAX_MCP_RESULT_SIZE] + "\n...[truncated]"
            return {"result": result_text}
        except Exception as e:
            logger.error("MCP tool call failed [%s]: %s", name, e)
            from niles.errors import sanitize_error

            return {"error": f"MCP tool error: {sanitize_error(e)}"}

    return {"error": f"Unknown tool: {name}"}
