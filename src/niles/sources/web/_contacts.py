"""CardDAV contacts routes: status, connect, disconnect, sync."""

import logging

from fastapi import Form, Request, Response
from fastapi.responses import HTMLResponse

from ...config import apply_overrides
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

    pool = request.app.state.pool
    try:
        row = await pool.fetchrow(
            "SELECT COUNT(*) AS cnt, MAX(updated_at) AS last_sync FROM contacts"
        )
        if row:
            ctx["contact_count"] = row["cnt"]
            ctx["last_sync"] = row["last_sync"]
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

    carddav_sync = getattr(request.app.state, "carddav_sync", None)
    if not carddav_sync:
        return templates.TemplateResponse(
            request,
            "fragments/carddav_status.html",
            {"connected": False, "carddav_error": "CardDAV Sync nicht verfuegbar."},
        )

    settings = request.app.state.settings

    # Apply overrides temporarily for connection test (not persisted yet)
    new_settings = apply_overrides(
        settings,
        {
            "carddav_url": url.strip(),
            "carddav_user": username.strip(),
            "carddav_password": password,
        },
    )
    carddav_sync.update_config(new_settings)

    # Test connection BEFORE saving to DB
    ok, message = await carddav_sync.test_connection()
    if not ok:
        # Revert to previous config
        carddav_sync.update_config(settings)
        return templates.TemplateResponse(
            request,
            "fragments/carddav_status.html",
            {"connected": False, "carddav_error": message},
        )

    # Connection successful — persist credentials (plaintext in DB,
    # acceptable for self-hosted; same pattern as CalDAV credentials).
    settings_store = request.app.state.settings_store
    try:
        await settings_store.set("carddav_url", url.strip())
        await settings_store.set("carddav_user", username.strip())
        await settings_store.set("carddav_password", password)
    except Exception:
        logger.exception("Failed to persist CardDAV credentials")
        carddav_sync.update_config(settings)
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

    settings_store = request.app.state.settings_store

    # Delete credentials from settings store
    for key in ("carddav_url", "carddav_user", "carddav_password"):
        await settings_store.delete(key)

    # Apply overrides (empty strings revert to env/defaults)
    new_settings = apply_overrides(
        request.app.state.settings,
        {
            "carddav_url": "",
            "carddav_user": "",
            "carddav_password": "",
        },
    )
    request.app.state.settings = new_settings

    carddav_sync = getattr(request.app.state, "carddav_sync", None)
    if carddav_sync:
        carddav_sync.update_config(new_settings)

    # Delete all contacts
    pool = request.app.state.pool
    try:
        await pool.execute("DELETE FROM contacts")
        logger.info("All contacts deleted (CardDAV disconnected)")
    except Exception:
        logger.exception("Failed to delete contacts on disconnect")

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
