"""Calendar routes: CalDAV discovery and calendar source management."""

import logging

import asyncpg
from fastapi import Form, Request, Response
from fastapi.responses import HTMLResponse

from ._core import (
    _get_session_user,
    _require_auth_and_csrf,
    router,
    templates,
)

logger = logging.getLogger(__name__)


# --- CalDAV discovery ---


@router.get("/api/caldav/calendars", response_class=HTMLResponse)
async def caldav_calendars(request: Request):
    """Discover available CalDAV calendars, return checkboxes fragment."""
    user = _get_session_user(request)
    if user is None:
        return Response(status_code=401, headers={"HX-Redirect": "/ui/login"})

    caldav = getattr(request.app.state, "caldav", None)
    if not caldav:
        return HTMLResponse("<p>CalDAV nicht konfiguriert.</p>")

    try:
        collections = await caldav.discover_collections()
    except Exception:
        logger.exception("CalDAV collection discovery failed")
        return HTMLResponse("<p>Fehler beim Laden der Kalender.</p>")

    # Determine which are currently selected
    selected = caldav.allowed_collections()

    return templates.TemplateResponse(
        request,
        "fragments/calendars.html",
        {
            "collections": collections,
            "selected": selected,
        },
    )


# --- Calendar source management ---


@router.get("/api/calendar/sources", response_class=HTMLResponse)
async def calendar_sources_list(request: Request):
    """Return htmx fragment listing all calendar sources."""
    user = _get_session_user(request)
    if user is None:
        return Response(status_code=401, headers={"HX-Redirect": "/ui/login"})

    manager = getattr(request.app.state, "calendar_manager", None)
    if not manager:
        return templates.TemplateResponse(request, "fragments/calendar_unavailable.html", {})

    await manager.claim_orphan_sources(user["uid"])
    sources = await manager.get_sources(user_id=user["uid"])
    return templates.TemplateResponse(
        request,
        "fragments/calendar_sources.html",
        {
            "sources": sources,
        },
    )


@router.post("/api/calendar/sources", response_class=HTMLResponse)
async def calendar_source_add(
    request: Request,
    source_type: str = Form(...),
    name: str = Form(""),
    url: str = Form(...),
    auth_user: str = Form(""),
    auth_password: str = Form(""),
):
    """Add a new calendar source and return updated sources list."""
    _user, error = await _require_auth_and_csrf(request)
    if error:
        return error
    if _user is None:
        return Response(status_code=401, headers={"HX-Redirect": "/ui/login"})

    manager = getattr(request.app.state, "calendar_manager", None)
    if not manager:
        return HTMLResponse('<p class="text-sm text-red-500">Kalender-Manager nicht verfuegbar.</p>')

    # Default name from URL if not provided
    if not name.strip():
        name = url.split("//", 1)[-1].split("/")[0][:80]

    writable = source_type == "caldav"

    uid = _user["uid"]

    try:
        await manager.add_source(
            name=name.strip(),
            url=url.strip(),
            source_type=source_type,
            writable=writable,
            auth_user=auth_user.strip() or None,
            auth_password=auth_password or None,
            user_id=uid,
        )
    except asyncpg.UniqueViolationError:
        sources = await manager.get_sources(user_id=uid)
        return templates.TemplateResponse(
            request,
            "fragments/calendar_sources.html",
            {
                "sources": sources,
                "error": "Diese Quelle existiert bereits.",
            },
        )
    except ValueError as exc:
        sources = await manager.get_sources(user_id=uid)
        return templates.TemplateResponse(
            request,
            "fragments/calendar_sources.html",
            {
                "sources": sources,
                "error": str(exc),
            },
        )

    sources = await manager.get_sources(user_id=uid)
    return templates.TemplateResponse(
        request,
        "fragments/calendar_sources.html",
        {
            "sources": sources,
        },
    )


@router.delete("/api/calendar/sources/{source_id}", response_class=HTMLResponse)
async def calendar_source_remove(request: Request, source_id: int):
    """Remove a calendar source (CASCADE deletes events)."""
    _user, error = await _require_auth_and_csrf(request)
    if error:
        return error
    if _user is None:
        return Response(status_code=401, headers={"HX-Redirect": "/ui/login"})

    manager = getattr(request.app.state, "calendar_manager", None)
    if not manager:
        return HTMLResponse('<p class="text-sm text-red-500">Kalender-Manager nicht verfuegbar.</p>')

    uid = _user["uid"]
    removed = await manager.remove_source(source_id, user_id=uid)
    sources = await manager.get_sources(user_id=uid)
    ctx = {"sources": sources}
    if not removed:
        ctx["error"] = "Quelle nicht gefunden."
    return templates.TemplateResponse(request, "fragments/calendar_sources.html", ctx)


@router.post("/api/calendar/sources/{source_id}/sync", response_class=HTMLResponse)
async def calendar_source_sync(request: Request, source_id: int):
    """Sync a single calendar source."""
    _user, error = await _require_auth_and_csrf(request)
    if error:
        return error
    if _user is None:
        return Response(status_code=401, headers={"HX-Redirect": "/ui/login"})

    manager = getattr(request.app.state, "calendar_manager", None)
    if not manager:
        return HTMLResponse('<p class="text-sm text-red-500">Kalender-Manager nicht verfuegbar.</p>')

    uid = _user["uid"]
    ctx: dict = {}
    try:
        count = await manager.sync_source(source_id, user_id=uid)
        if count is None:
            ctx["error"] = "Quelle nicht gefunden oder deaktiviert."
    except Exception:
        logger.exception("Manual sync failed for source %d", source_id)

    sources = await manager.get_sources(user_id=uid)
    ctx["sources"] = sources
    return templates.TemplateResponse(request, "fragments/calendar_sources.html", ctx)
