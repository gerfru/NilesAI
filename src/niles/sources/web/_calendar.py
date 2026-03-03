"""Calendar routes: CalDAV discovery, calendar sources, Google Calendar OAuth."""

import asyncio
import hmac
import logging
import secrets
import urllib.parse
from datetime import datetime, timedelta, timezone

import asyncpg
import httpx
from fastapi import Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from ...sync.google_auth import GOOGLE_TOKEN_URL
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

# --- Google Calendar OAuth (Phase B) ---

_GOOGLE_CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar"
_GOOGLE_CALENDAR_LIST_URL = (
    "https://www.googleapis.com/calendar/v3/users/me/calendarList"
)
_GCAL_OAUTH_COOKIE = "gcal_oauth_state"


def _log_task_exception(task: asyncio.Task) -> None:
    """Done-callback for fire-and-forget tasks: log exceptions instead of losing them."""
    if not task.cancelled() and task.exception():
        logger.error("Background task failed: %s", task.exception())


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

    sources = await manager.get_sources()
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

    manager = getattr(request.app.state, "calendar_manager", None)
    if not manager:
        return HTMLResponse(
            '<p class="text-sm text-red-500">Kalender-Manager nicht verfuegbar.</p>'
        )

    # Default name from URL if not provided
    if not name.strip():
        name = url.split("//", 1)[-1].split("/")[0][:80]

    writable = source_type in ("caldav", "google")

    try:
        await manager.add_source(
            name=name.strip(),
            url=url.strip(),
            source_type=source_type,
            writable=writable,
            auth_user=auth_user.strip() or None,
            auth_password=auth_password or None,
        )
    except asyncpg.UniqueViolationError:
        sources = await manager.get_sources()
        return templates.TemplateResponse(
            request,
            "fragments/calendar_sources.html",
            {
                "sources": sources,
                "error": "Diese Quelle existiert bereits.",
            },
        )
    except ValueError as exc:
        sources = await manager.get_sources()
        return templates.TemplateResponse(
            request,
            "fragments/calendar_sources.html",
            {
                "sources": sources,
                "error": str(exc),
            },
        )

    sources = await manager.get_sources()
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

    manager = getattr(request.app.state, "calendar_manager", None)
    if not manager:
        return HTMLResponse(
            '<p class="text-sm text-red-500">Kalender-Manager nicht verfuegbar.</p>'
        )

    removed = await manager.remove_source(source_id)
    sources = await manager.get_sources()
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

    manager = getattr(request.app.state, "calendar_manager", None)
    if not manager:
        return HTMLResponse(
            '<p class="text-sm text-red-500">Kalender-Manager nicht verfuegbar.</p>'
        )

    ctx: dict = {}
    try:
        count = await manager.sync_source(source_id)
        if count is None:
            ctx["error"] = "Quelle nicht gefunden oder deaktiviert."
    except Exception:
        logger.exception("Manual sync failed for source %d", source_id)

    sources = await manager.get_sources()
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
    """Handle Google Calendar OAuth callback.

    Exchanges code for tokens, discovers calendars via Google Calendar API,
    and creates calendar_sources entries for each discovered calendar.
    """
    _fail_url = "/ui/settings?error=calendar_connect_failed"

    # Verify user session (match connect endpoint auth requirement)
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

    # Discover calendars via Google Calendar REST API
    try:
        cal_resp = await google_client.get(
            _GOOGLE_CALENDAR_LIST_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
    except httpx.HTTPError as e:
        logger.error("Google Calendar list HTTP error: %s", e)
        return RedirectResponse(url=_fail_url, status_code=303)

    if cal_resp.status_code != 200:
        logger.error("Google Calendar list failed: %d", cal_resp.status_code)
        return RedirectResponse(url=_fail_url, status_code=303)

    calendars = cal_resp.json().get("items", [])
    manager = getattr(request.app.state, "calendar_manager", None)
    if not manager:
        return RedirectResponse(url=_fail_url, status_code=303)

    added = 0
    for cal in calendars:
        cal_id = cal.get("id", "")
        summary = cal.get("summary", cal_id)
        access_role = cal.get("accessRole", "reader")
        writable = access_role in ("owner", "writer")

        # Build Google CalDAV URL
        encoded_id = urllib.parse.quote(cal_id, safe="")
        caldav_url = (
            f"https://apidata.googleusercontent.com/caldav/v2/{encoded_id}/events/"
        )

        try:
            await manager.add_source(
                name=summary,
                url=caldav_url,
                source_type="google",
                writable=writable,
                google_refresh_token=refresh_token,
                google_token_expiry=token_expiry,
            )
            added += 1
        except asyncpg.UniqueViolationError:
            logger.debug("Skipping calendar %s (already exists)", cal_id)
        except Exception:
            logger.warning("Failed to add calendar %s", cal_id, exc_info=True)

    logger.info("Google Calendar OAuth: added %d calendar(s)", added)

    # Trigger initial sync in background (store reference to prevent GC)
    if added > 0:
        task = asyncio.create_task(manager.sync_all())
        task.add_done_callback(_log_task_exception)

    response = RedirectResponse(url="/ui/settings", status_code=303)
    response.delete_cookie(_GCAL_OAUTH_COOKIE)
    return response
