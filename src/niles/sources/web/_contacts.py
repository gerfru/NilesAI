# SPDX-License-Identifier: AGPL-3.0-only
"""CardDAV contacts routes: status, connect, disconnect, sync."""

import logging

from fastapi import Form, Request, Response
from fastapi.responses import HTMLResponse

from ._core import (
    _get_session_user,
    _require_auth_and_csrf,
    router,
    templates,
)

logger = logging.getLogger(__name__)


async def _contacts_status_ctx(request: Request, user_id: int) -> dict:
    """Build template context for carddav_status.html fragment."""
    manager = request.app.state.carddav_manager
    contacts_action = request.app.state.contacts_action

    # Claim orphan sources on first visit (legacy migration)
    await manager.claim_orphan_sources(user_id)

    sources = await manager.get_sources(user_id=user_id)
    stats = await contacts_action.get_sync_status(user_id=user_id)

    return {
        "sources": sources,
        "contact_count": stats["cnt"],
        "last_sync": stats["last_sync"],
        "carddav_error": None,
    }


@router.get("/api/contacts/status", response_class=HTMLResponse)
async def contacts_status(request: Request):
    """Return CardDAV sync status fragment (sources list or connect form)."""
    user = _get_session_user(request)
    if user is None:
        return Response(status_code=401, headers={"HX-Redirect": "/ui/login"})

    ctx = await _contacts_status_ctx(request, user["uid"])
    return templates.TemplateResponse(
        request,
        "fragments/carddav_status.html",
        ctx,
    )


@router.post("/api/contacts/connect", response_class=HTMLResponse)
async def contacts_connect(
    request: Request,
    url: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
):
    """Test CardDAV connection, then save source and trigger initial sync."""
    user, error = await _require_auth_and_csrf(request)
    if error:
        return error
    assert user is not None

    contacts_action = request.app.state.contacts_action

    try:
        await contacts_action.connect(url, username, password, user_id=user["uid"])
    except (ConnectionError, ValueError) as e:
        ctx = await _contacts_status_ctx(request, user["uid"])
        ctx["carddav_error"] = str(e)
        return templates.TemplateResponse(
            request,
            "fragments/carddav_status.html",
            ctx,
        )
    except Exception:
        logger.exception("Failed to connect CardDAV source")
        ctx = await _contacts_status_ctx(request, user["uid"])
        ctx["carddav_error"] = "Verbindung fehlgeschlagen. Details siehe Logs."
        return templates.TemplateResponse(
            request,
            "fragments/carddav_status.html",
            ctx,
        )

    ctx = await _contacts_status_ctx(request, user["uid"])
    return templates.TemplateResponse(
        request,
        "fragments/carddav_status.html",
        ctx,
    )


@router.post("/api/contacts/{source_id}/disconnect", response_class=HTMLResponse)
async def contacts_disconnect(request: Request, source_id: int):
    """Remove a CardDAV source (contacts are CASCADE-deleted)."""
    user, error = await _require_auth_and_csrf(request)
    if error:
        return error
    assert user is not None

    contacts_action = request.app.state.contacts_action

    try:
        await contacts_action.disconnect(source_id, user_id=user["uid"])
    except Exception:
        logger.exception("Failed to disconnect CardDAV source %d", source_id)

    ctx = await _contacts_status_ctx(request, user["uid"])
    return templates.TemplateResponse(
        request,
        "fragments/carddav_status.html",
        ctx,
    )


@router.post("/api/contacts/{source_id}/sync", response_class=HTMLResponse)
async def contacts_sync(request: Request, source_id: int):
    """Trigger a manual CardDAV contact sync for a specific source."""
    user, error = await _require_auth_and_csrf(request)
    if error:
        return error
    assert user is not None

    manager = request.app.state.carddav_manager

    try:
        await manager.sync_source(source_id, user_id=user["uid"])
    except Exception:
        logger.exception("Manual CardDAV sync failed for source %d", source_id)

    ctx = await _contacts_status_ctx(request, user["uid"])
    return templates.TemplateResponse(
        request,
        "fragments/carddav_status.html",
        ctx,
    )
