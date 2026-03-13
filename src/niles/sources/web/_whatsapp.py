"""WhatsApp session management routes."""

import logging

import asyncpg  # FK violation handling requires cookie deletion (web concern)
from fastapi import Request, Response
from fastapi.responses import HTMLResponse

from ._core import (
    SESSION_COOKIE_NAME,
    _get_session_user,
    _require_auth_and_csrf,
    router,
    templates,
)

logger = logging.getLogger(__name__)


@router.get("/api/whatsapp/status", response_class=HTMLResponse)
async def whatsapp_status(request: Request):
    """Return WhatsApp connection status fragment."""
    user = _get_session_user(request)
    if user is None:
        return Response(status_code=401, headers={"HX-Redirect": "/ui/login"})

    wa_setup = getattr(request.app.state, "wa_setup_action", None)
    if not wa_setup:
        return HTMLResponse(
            '<p class="text-sm text-zinc-500 dark:text-zinc-400 py-2">'
            "WhatsApp nicht verfuegbar.</p>"
        )

    ctx = await wa_setup.get_status(user["uid"])
    return templates.TemplateResponse(request, "fragments/whatsapp_status.html", ctx)


@router.post("/api/whatsapp/connect", response_class=HTMLResponse)
async def whatsapp_connect(request: Request):
    """Create an Evolution API instance and return QR code fragment."""
    user, error = await _require_auth_and_csrf(request)
    if error:
        return error
    assert user is not None

    wa_setup = getattr(request.app.state, "wa_setup_action", None)
    if not wa_setup:
        return HTMLResponse(
            '<p class="text-sm text-red-500">WhatsApp nicht verfuegbar.</p>'
        )

    try:
        ctx = await wa_setup.connect(user["uid"])
    except asyncpg.ForeignKeyViolationError:
        logger.warning("FK violation: user_id=%s not in users table", user["uid"])
        response = HTMLResponse(
            '<p class="text-sm text-red-500">'
            "Sitzung ungueltig &ndash; bitte erneut einloggen.</p>",
            status_code=401,
            headers={"HX-Redirect": "/ui/login"},
        )
        response.delete_cookie(SESSION_COOKIE_NAME)
        return response

    return templates.TemplateResponse(request, "fragments/whatsapp_status.html", ctx)


@router.post("/api/whatsapp/disconnect", response_class=HTMLResponse)
async def whatsapp_disconnect(request: Request):
    """Logout and delete the user's Evolution API instance."""
    user, error = await _require_auth_and_csrf(request)
    if error:
        return error
    assert user is not None

    wa_setup = getattr(request.app.state, "wa_setup_action", None)
    if not wa_setup:
        return HTMLResponse(
            '<p class="text-sm text-red-500">WhatsApp nicht verfuegbar.</p>'
        )

    await wa_setup.disconnect(user["uid"])

    return templates.TemplateResponse(
        request,
        "fragments/whatsapp_status.html",
        {"wa_status": "disconnected", "wa_phone": "", "wa_qr": ""},
    )
