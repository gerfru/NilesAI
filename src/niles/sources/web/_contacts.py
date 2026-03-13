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


async def _contacts_status_ctx(request: Request) -> dict:
    """Build template context for carddav_status.html fragment."""
    settings = request.app.state.settings
    connected = bool(settings.carddav_url)
    ctx: dict = {"connected": connected, "carddav_error": None}
    if not connected:
        return ctx

    ctx["carddav_url"] = settings.carddav_url
    ctx["carddav_user"] = settings.carddav_user

    contacts_action = request.app.state.contacts_action
    try:
        stats = await contacts_action.get_sync_status()
        ctx["contact_count"] = stats["cnt"]
        ctx["last_sync"] = stats["last_sync"]
    except Exception:
        logger.warning("Failed to fetch contact status")
    return ctx


@router.get("/api/contacts/status", response_class=HTMLResponse)
async def contacts_status(request: Request):
    """Return CardDAV sync status fragment (form or connected card)."""
    user = _get_session_user(request)
    if user is None:
        return Response(status_code=401, headers={"HX-Redirect": "/ui/login"})

    ctx = await _contacts_status_ctx(request)
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
    """Test CardDAV connection, then save credentials and trigger initial sync."""
    _user, error = await _require_auth_and_csrf(request)
    if error:
        return error

    contacts_action = request.app.state.contacts_action
    if not contacts_action.carddav_sync:
        return templates.TemplateResponse(
            request,
            "fragments/carddav_status.html",
            {"connected": False, "carddav_error": "CardDAV Sync nicht verfuegbar."},
        )

    settings = request.app.state.settings

    try:
        new_settings = await contacts_action.connect(url, username, password, settings)
    except ConnectionError as e:
        return templates.TemplateResponse(
            request,
            "fragments/carddav_status.html",
            {"connected": False, "carddav_error": str(e)},
        )
    except Exception:
        logger.exception("Failed to persist CardDAV credentials")
        return templates.TemplateResponse(
            request,
            "fragments/carddav_status.html",
            {
                "connected": False,
                "carddav_error": "Speichern fehlgeschlagen. Details siehe Logs.",
            },
        )

    request.app.state.settings = new_settings

    # Register daily sync job if not already scheduled
    carddav_sync = contacts_action.carddav_sync
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler and not scheduler.get_job("carddav_daily_sync"):
        scheduler.add_job(
            carddav_sync.sync_contacts,
            "cron",
            hour=3,
            minute=0,
            id="carddav_daily_sync",
            max_instances=1,
            misfire_grace_time=300,
        )
        logger.info("CardDAV daily sync job registered via UI")

    # Run initial sync
    try:
        await carddav_sync.sync_contacts()
    except Exception:
        logger.exception("Initial CardDAV sync failed after connect")

    ctx = await _contacts_status_ctx(request)
    return templates.TemplateResponse(
        request,
        "fragments/carddav_status.html",
        ctx,
    )


@router.post("/api/contacts/disconnect", response_class=HTMLResponse)
async def contacts_disconnect(request: Request):
    """Remove CardDAV credentials and delete all synced contacts."""
    _user, error = await _require_auth_and_csrf(request)
    if error:
        return error

    contacts_action = request.app.state.contacts_action
    settings = request.app.state.settings

    try:
        new_settings = await contacts_action.disconnect(settings)
        request.app.state.settings = new_settings
    except Exception:
        logger.exception("Failed to disconnect contacts")

    return templates.TemplateResponse(
        request,
        "fragments/carddav_status.html",
        {"connected": False, "carddav_error": None},
    )


@router.post("/api/contacts/sync", response_class=HTMLResponse)
async def contacts_sync(request: Request):
    """Trigger a manual CardDAV contact sync."""
    _user, error = await _require_auth_and_csrf(request)
    if error:
        return error

    carddav_sync = getattr(request.app.state, "carddav_sync", None)
    if not carddav_sync:
        ctx = await _contacts_status_ctx(request)
        ctx["carddav_error"] = "CardDAV Sync nicht verfuegbar."
        return templates.TemplateResponse(
            request,
            "fragments/carddav_status.html",
            ctx,
        )

    try:
        await carddav_sync.sync_contacts()
    except Exception:
        logger.exception("Manual CardDAV sync failed")

    ctx = await _contacts_status_ctx(request)
    return templates.TemplateResponse(
        request,
        "fragments/carddav_status.html",
        ctx,
    )
