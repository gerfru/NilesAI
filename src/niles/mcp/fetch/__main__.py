"""Entry point for ``python -m niles.mcp.fetch``."""

from .server import mcp

mcp.run(transport="stdio")
