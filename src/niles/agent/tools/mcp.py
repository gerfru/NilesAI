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
            return {"error": f"MCP tool error: {e}"}

    # Per-user gws MCP tools (Google Calendar via gws)
    if ctx.user_mcp_pool and ctx.user_mcp_pool.is_gws_tool(name):
        if ctx.user_id is None:
            return {
                "error": "Google nicht verbunden. Bitte in den Einstellungen verbinden."
            }
        try:
            result_text = await ctx.user_mcp_pool.call_tool(ctx.user_id, name, args)
            if len(result_text) > MAX_MCP_RESULT_SIZE:
                result_text = result_text[:MAX_MCP_RESULT_SIZE] + "\n...[truncated]"
            return {"result": result_text}
        except Exception as e:
            logger.error("gws tool call failed [%s] user=%s: %s", name, ctx.user_id, e)
            return {"error": "Google Workspace Fehler. Bitte erneut versuchen."}

    return {"error": f"Unknown tool: {name}"}
