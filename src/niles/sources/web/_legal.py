# SPDX-License-Identifier: AGPL-3.0-only
"""Legal notices page — serves docs/LEGAL.md content."""

from pathlib import Path

from fastapi import Request
from fastapi.responses import HTMLResponse

from ._core import router, templates

_LEGAL_PATH = Path(__file__).resolve().parents[4] / "docs" / "LEGAL.md"


@router.get("/legal", response_class=HTMLResponse)
async def legal_page(request: Request):
    """Render docs/LEGAL.md as a simple page (no auth required)."""
    content = ""
    if _LEGAL_PATH.exists():
        content = _LEGAL_PATH.read_text(encoding="utf-8")
    return templates.TemplateResponse(request, "legal.html", {"content": content})
