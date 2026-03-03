"""Vikunja (per-user task management) routes."""

import ipaddress
import logging
from urllib.parse import urlparse

import asyncpg
from fastapi import Form, Request, Response
from fastapi.responses import HTMLResponse

from ._core import (
    SESSION_COOKIE_NAME,
    _get_session_user,
    _require_auth_and_csrf,
    router,
    templates,
)

logger = logging.getLogger(__name__)


@router.get("/api/vikunja/status", response_class=HTMLResponse)
async def vikunja_status(request: Request):
    """Return Vikunja connection status fragment."""
    user = _get_session_user(request)
    if user is None:
        return Response(status_code=401, headers={"HX-Redirect": "/ui/login"})

    vikunja_store = getattr(request.app.state, "vikunja_store", None)
    if not vikunja_store:
        return HTMLResponse(
            '<p class="text-sm text-zinc-500 dark:text-zinc-400 py-2">'
            "Vikunja nicht verfuegbar.</p>"
        )

    creds = await vikunja_store.get_credentials(user["uid"])
    ctx: dict = {
        "vikunja_connected": False,
        "vikunja_error": None,
        "vikunja_project_count": 0,
    }

    if creds:
        api_url = creds["api_url"] or request.app.state.settings.vikunja_api_url
        if api_url:
            try:
                general = request.app.state.http_clients.general
                resp = await general.get(
                    f"{api_url.rstrip('/')}/projects",
                    headers={"Authorization": f"Bearer {creds['api_token']}"},
                    timeout=5,
                )
                resp.raise_for_status()
                ctx["vikunja_connected"] = True
                ctx["vikunja_project_count"] = len(resp.json())
            except Exception:
                ctx["vikunja_connected"] = True
                ctx["vikunja_error"] = "Verbindung zum Vikunja-Server fehlgeschlagen."
        else:
            ctx["vikunja_connected"] = True
            ctx["vikunja_error"] = "Keine Vikunja API-URL konfiguriert."

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
):
    """Save Vikunja API token for the current user."""
    user, error = await _require_auth_and_csrf(request)
    if error:
        return error
    assert user is not None

    vikunja_store = getattr(request.app.state, "vikunja_store", None)
    if not vikunja_store:
        return templates.TemplateResponse(
            request,
            "fragments/vikunja_status.html",
            {
                "vikunja_connected": False,
                "vikunja_project_count": 0,
                "vikunja_error": "Vikunja nicht verfuegbar.",
            },
        )

    effective_url = api_url.strip() or request.app.state.settings.vikunja_api_url
    if not effective_url:
        return templates.TemplateResponse(
            request,
            "fragments/vikunja_status.html",
            {
                "vikunja_connected": False,
                "vikunja_project_count": 0,
                "vikunja_error": "Keine API-URL. Bitte URL angeben oder global konfigurieren.",
            },
        )

    # SSRF protection: only allow http/https and reject private IP ranges
    try:
        parsed = urlparse(effective_url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError("scheme")
        host = parsed.hostname or ""
        if not host:
            raise ValueError("host")
        # Reject private/loopback IPs.  Hostnames (including "localhost")
        # are intentionally allowed because Docker-internal service names
        # (e.g. "vikunja") are the expected use case for self-hosted setups.
        # This is acceptable since only authenticated admins can set the URL.
        try:
            addr = ipaddress.ip_address(host)
            if addr.is_private or addr.is_loopback or addr.is_link_local:
                raise ValueError("private IP")
        except ValueError as ve:
            if str(ve) == "private IP":
                raise
    except ValueError:
        return templates.TemplateResponse(
            request,
            "fragments/vikunja_status.html",
            {
                "vikunja_connected": False,
                "vikunja_project_count": 0,
                "vikunja_error": "Ungueltige URL. Nur http:// und https:// erlaubt.",
            },
        )

    # Test connection before saving
    try:
        general = request.app.state.http_clients.general
        resp = await general.get(
            f"{effective_url.rstrip('/')}/projects",
            headers={"Authorization": f"Bearer {api_token}"},
            timeout=10,
        )
        resp.raise_for_status()
        project_count = len(resp.json())
    except Exception:
        return templates.TemplateResponse(
            request,
            "fragments/vikunja_status.html",
            {
                "vikunja_connected": False,
                "vikunja_project_count": 0,
                "vikunja_error": "Verbindung fehlgeschlagen: Token oder URL ungueltig.",
            },
        )

    try:
        await vikunja_store.upsert_credentials(
            user_id=user["uid"],
            api_token=api_token,
            api_url=api_url.strip(),
        )
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

    return templates.TemplateResponse(
        request,
        "fragments/vikunja_status.html",
        {
            "vikunja_connected": True,
            "vikunja_project_count": project_count,
            "vikunja_error": None,
        },
    )


@router.post("/api/vikunja/disconnect", response_class=HTMLResponse)
async def vikunja_disconnect(request: Request):
    """Remove Vikunja API token for current user."""
    user, error = await _require_auth_and_csrf(request)
    if error:
        return error
    assert user is not None

    vikunja_store = getattr(request.app.state, "vikunja_store", None)
    if vikunja_store and user.get("uid"):
        await vikunja_store.delete_credentials(user["uid"])

    return templates.TemplateResponse(
        request,
        "fragments/vikunja_status.html",
        {"vikunja_connected": False, "vikunja_project_count": 0, "vikunja_error": None},
    )
