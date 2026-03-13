"""Calendar routes: CalDAV discovery, calendar sources, Google OAuth for gws."""

import hmac
import logging
import secrets
import urllib.parse
from datetime import datetime, timedelta, timezone

import asyncpg
import httpx
from fastapi import Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from ...mcp.user_pool import GOOGLE_TOKEN_URL
from ._core import (
    _GOOGLE_AUTH_URL,
    _build_redirect_uri,
    _get_session_user,
    _google_configured,
    _is_secure_context,
    _require_auth_and_csrf,
    router,
    templates,
)

logger = logging.getLogger(__name__)

# --- Google OAuth for gws MCP ---

_GOOGLE_CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar"
_GCAL_OAUTH_COOKIE = "gcal_oauth_state"


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
        return templates.TemplateResponse(
            request, "fragments/calendar_unavailable.html", {}
        )

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
        return HTMLResponse(
            '<p class="text-sm text-red-500">Kalender-Manager nicht verfuegbar.</p>'
        )

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
        return HTMLResponse(
            '<p class="text-sm text-red-500">Kalender-Manager nicht verfuegbar.</p>'
        )

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
        return HTMLResponse(
            '<p class="text-sm text-red-500">Kalender-Manager nicht verfuegbar.</p>'
        )

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


# --- Google Calendar OAuth ---


@router.get("/api/calendar/google/connect")
async def google_calendar_connect(request: Request):
    """Redirect to Google OAuth with Calendar scope."""
    user = _get_session_user(request)
    if user is None:
        return RedirectResponse(url="/ui/login", status_code=303)

    if not _google_configured(request):
        return RedirectResponse(url="/ui/settings", status_code=303)

    settings = request.app.state.settings
    state = secrets.token_urlsafe(32)
    redirect_uri = _build_redirect_uri(request, "/ui/callback/google/calendar")

    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": _GOOGLE_CALENDAR_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    auth_url = f"{_GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}"

    response = RedirectResponse(url=auth_url, status_code=303)
    response.set_cookie(
        _GCAL_OAUTH_COOKIE,
        state,
        max_age=600,
        httponly=True,
        secure=_is_secure_context(request),
        samesite="lax",
    )
    return response


@router.get("/callback/google/calendar")
async def callback_google_calendar(
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
):
    """Handle Google OAuth callback — store tokens for gws MCP server."""
    _fail_url = "/ui/settings?error=calendar_connect_failed"

    user = _get_session_user(request)
    if user is None:
        return RedirectResponse(url="/ui/login", status_code=303)

    # Validate OAuth state
    stored_state = request.cookies.get(_GCAL_OAUTH_COOKIE, "")
    if not state or not stored_state or not hmac.compare_digest(state, stored_state):
        logger.warning("Google Calendar OAuth: invalid state parameter")
        return RedirectResponse(url=_fail_url, status_code=303)

    if error or not code:
        logger.warning("Google Calendar OAuth error: %s", error or "no code")
        return RedirectResponse(url=_fail_url, status_code=303)

    settings = request.app.state.settings
    redirect_uri = _build_redirect_uri(request, "/ui/callback/google/calendar")

    # Exchange authorization code for tokens
    try:
        google_client = request.app.state.http_clients.google_oauth
        token_resp = await google_client.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
    except httpx.HTTPError as e:
        logger.error("Google Calendar token exchange HTTP error: %s", e)
        return RedirectResponse(url=_fail_url, status_code=303)

    if token_resp.status_code != 200:
        logger.error(
            "Google Calendar token exchange failed: %d", token_resp.status_code
        )
        return RedirectResponse(url=_fail_url, status_code=303)

    tokens = token_resp.json()
    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")
    expires_in = tokens.get("expires_in", 3600)

    if not access_token or not refresh_token:
        logger.error(
            "Google Calendar OAuth: missing tokens (refresh_token=%s)",
            "present" if refresh_token else "absent",
        )
        return RedirectResponse(url=_fail_url, status_code=303)

    token_expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    # Store tokens per user for gws MCP server
    token_store = request.app.state.google_token_store
    await token_store.upsert_tokens(
        user_id=user["uid"],
        refresh_token=refresh_token,
        access_token=access_token,
        token_expiry=token_expiry,
        scopes=_GOOGLE_CALENDAR_SCOPE,
    )
    logger.info("Google OAuth: tokens stored for user %d", user["uid"])

    response = RedirectResponse(url="/ui/settings", status_code=303)
    response.delete_cookie(_GCAL_OAUTH_COOKIE)
    return response


@router.post("/api/calendar/google/disconnect")
async def google_calendar_disconnect(request: Request):
    """Remove stored Google tokens and stop the user's gws MCP instance."""
    user, error = await _require_auth_and_csrf(request)
    if error:
        return error
    assert user is not None

    user_mcp_pool = getattr(request.app.state, "user_mcp_pool", None)
    if user_mcp_pool:
        await user_mcp_pool.disconnect_user(user["uid"])
    else:
        token_store = getattr(request.app.state, "google_token_store", None)
        if token_store:
            await token_store.delete_tokens(user["uid"])

    # HX-Redirect triggers full page reload in htmx
    return Response(status_code=200, headers={"HX-Redirect": "/ui/settings"})
