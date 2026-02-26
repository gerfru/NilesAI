"""Entry point for ``python -m niles.mcp.weather``."""

from .server import mcp

mcp.run(transport="stdio")
