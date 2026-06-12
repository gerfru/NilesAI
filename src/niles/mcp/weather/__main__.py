# SPDX-License-Identifier: AGPL-3.0-only
"""Entry point for ``python -m niles.mcp.weather``."""

from .server import mcp

mcp.run(transport="stdio")
