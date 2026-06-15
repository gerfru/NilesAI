# SPDX-License-Identifier: AGPL-3.0-only
"""Vikunja (per-user task management) routes."""

import logging

import asyncpg  # FK violation handling requires cookie deletion (web concern)
from fastapi import Depends, Form, Request, Response
from fastapi.responses import HTMLResponse

from ...actions.vikunja_setup import VikunjaSetupAction
from ._core import (
    SESSION_COOKIE_NAME,
    _get_session_user,
    _require_auth_and_csrf,
    router,
    templates,
)
from ._deps import get_vikunja_setup

logger = logging.getLogger(__name__)


@router.get("/api/vikunja/status", response_class=HTMLResponse)
async def vikunja_status(
    request: Request,
    vikunja_setup: VikunjaSetupAction | None = Depends(get_vikunja_setup),
):
    """Return Vikunja connection status fragment."""
    user = _get_session_user(request)
    if user is None:
        return Response(status_code=401, headers={"HX-Redirect": "/ui/login"})

    if not vikunja_setup:
        return HTMLResponse('<p class="text-sm text-zinc-500 dark:text-zinc-400 py-2">Vikunja nicht verfuegbar.</p>')

    ctx = await vikunja_setup.get_status(user["uid"])
    return templates.TemplateResponse(
        request,
        "fragments/vikunja_status.html",
        ctx,
    )


@router.post("/api/vikunja/connect", response_class=HTMLResponse)
async def vikunja_connect(
    request: Request,
    api_token: str = Form(...),
    api_url: str = Form(""),
    vikunja_setup: VikunjaSetupAction | None = Depends(get_vikunja_setup),
):
    """Save Vikunja API token for the current user."""
    user, error = await _require_auth_and_csrf(request)
    if error:
        return error
    assert user is not None

    if not vikunja_setup:
        return templates.TemplateResponse(
            request,
            "fragments/vikunja_status.html",
            {
                "vikunja_connected": False,
                "vikunja_project_count": 0,
                "vikunja_error": "Vikunja nicht verfuegbar.",
            },
        )

    try:
        count = await vikunja_setup.save_credentials(user["uid"], api_token, api_url)
    except (ValueError, ConnectionError) as e:
        return templates.TemplateResponse(
            request,
            "fragments/vikunja_status.html",
            {
                "vikunja_connected": False,
                "vikunja_project_count": 0,
                "vikunja_error": str(e),
            },
        )
    except asyncpg.ForeignKeyViolationError:
        logger.warning("FK violation: user_id=%s not in users table", user["uid"])
        response = HTMLResponse(
            '<p class="text-sm text-red-500">Sitzung ungueltig &ndash; bitte erneut einloggen.</p>',
            status_code=401,
            headers={"HX-Redirect": "/ui/login"},
        )
        response.delete_cookie(SESSION_COOKIE_NAME)
        return response

    return templates.TemplateResponse(
        request,
        "fragments/vikunja_status.html",
        {
            "vikunja_connected": True,
            "vikunja_project_count": count,
            "vikunja_error": None,
        },
    )


@router.post("/api/vikunja/disconnect", response_class=HTMLResponse)
async def vikunja_disconnect(
    request: Request,
    vikunja_setup: VikunjaSetupAction | None = Depends(get_vikunja_setup),
):
    """Remove Vikunja API token for current user."""
    user, error = await _require_auth_and_csrf(request)
    if error:
        return error
    assert user is not None

    if vikunja_setup and user.get("uid"):
        await vikunja_setup.delete_credentials(user["uid"])

    return templates.TemplateResponse(
        request,
        "fragments/vikunja_status.html",
        {"vikunja_connected": False, "vikunja_project_count": 0, "vikunja_error": None},
    )
