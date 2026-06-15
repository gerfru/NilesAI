# SPDX-License-Identifier: AGPL-3.0-only
"""MCP tool dispatch (fallback for tools not in the built-in registry)."""

import logging
import re
from urllib.parse import urlparse

from ...tokens import count_tokens, truncate_to_tokens
from ..prompts import wrap_untrusted
from . import ToolContext

logger = logging.getLogger(__name__)

# Hard byte cap (defensive, before token work) — token cap below is the real limit.
MAX_MCP_RESULT_SIZE = 100_000

# Block RFC1918 / loopback / Docker-internal hosts to prevent SSRF via the fetch tool.
_SSRF_BLOCKED = re.compile(
    r"^(localhost"
    r"|127\.\d+\.\d+\.\d+"
    r"|0\.0\.0\.0"
    r"|10\.\d+\.\d+\.\d+"
    r"|192\.168\.\d+\.\d+"
    r"|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+"
    r"|host\.docker\.internal"
    r"|.*\.local)$",
    re.IGNORECASE,
)


def _is_fetch_safe(url: str) -> bool:
    """Return False if the URL resolves to a private/internal host."""
    try:
        host = urlparse(url).hostname or ""
        return not _SSRF_BLOCKED.match(host)
    except Exception:
        return False


async def handle_mcp_tool(name: str, args: dict, ctx: ToolContext) -> dict:
    """Execute an MCP tool call. Called as fallback when name is not in TOOL_REGISTRY."""
    if name.startswith("mcp__fetch__"):
        url = args.get("url", "")
        if not _is_fetch_safe(url):
            logger.warning("SSRF blocked: fetch tool called with internal URL %r", url)
            return {"error": "URL nicht erreichbar: interne Netzwerkadressen sind nicht erlaubt."}

    # Global MCP tools (weather, searxng, fetch, etc.)
    if ctx.mcp and ctx.mcp.is_mcp_tool(name):
        try:
            result_text = await ctx.mcp.call_tool(name, args)
            # Defensive byte cap, then the real token cap so one big result
            # cannot blow the model's context window.
            if len(result_text) > MAX_MCP_RESULT_SIZE:
                result_text = result_text[:MAX_MCP_RESULT_SIZE]
            max_tokens = ctx.config.mcp_max_result_tokens
            if count_tokens(result_text) > max_tokens:
                result_text = truncate_to_tokens(result_text, max_tokens) + "\n...[truncated]"
            # Web fetch/search return externally-controlled content → isolate as
            # data (indirect injection). Weather/structured tools stay as-is.
            if "fetch" in name or "search" in name:
                return {"result": wrap_untrusted("web", result_text)}
            return {"result": result_text}
        except Exception as e:
            logger.error("MCP tool call failed [%s]: %s", name, e)
            from niles.errors import sanitize_error

            return {"error": f"MCP tool error: {sanitize_error(e)}"}

    return {"error": f"Unknown tool: {name}"}
