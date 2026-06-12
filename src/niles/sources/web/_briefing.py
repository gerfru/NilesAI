# SPDX-License-Identifier: AGPL-3.0-only
"""Briefing test route."""

import logging

from fastapi import Request
from fastapi.responses import HTMLResponse

from ._core import _require_admin, router, templates

logger = logging.getLogger(__name__)


@router.post("/api/briefing/test/{briefing_type}", response_class=HTMLResponse)
async def briefing_test(request: Request, briefing_type: str):
    """Manually trigger a briefing (generate + send via WhatsApp)."""
    _user, error = await _require_admin(request)
    if error:
        return error

    if briefing_type not in ("daily", "weekly"):
        return templates.TemplateResponse(
            request,
            "fragments/toast.html",
            {
                "message": "Unbekannter Briefing-Typ",
                "toast_type": "error",
            },
        )

    from ...jobs.briefing import send_daily_briefing, send_weekly_briefing

    try:
        if briefing_type == "daily":
            sent = await send_daily_briefing(request.app.state)
        else:
            sent = await send_weekly_briefing(request.app.state)
    except Exception:
        logger.exception("Manual briefing test failed")
        return templates.TemplateResponse(
            request,
            "fragments/toast.html",
            {
                "message": "Briefing fehlgeschlagen (siehe Logs)",
                "toast_type": "error",
            },
        )

    if not sent:
        return templates.TemplateResponse(
            request,
            "fragments/toast.html",
            {
                "message": "Kein WhatsApp verbunden",
                "toast_type": "error",
            },
        )

    return templates.TemplateResponse(
        request,
        "fragments/toast.html",
        {
            "message": f"{'Tages' if briefing_type == 'daily' else 'Wochen'}briefing gesendet",
            "toast_type": "success",
        },
    )
