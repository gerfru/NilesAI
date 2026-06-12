# SPDX-License-Identifier: AGPL-3.0-only
"""Entry point for ``python -m niles.mcp.search``."""

from .server import mcp

mcp.run(transport="stdio")
