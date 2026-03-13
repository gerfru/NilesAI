"""Signal management routes: status, QR code, link, disconnect."""

import asyncio
import logging

from fastapi import Request, Response
from fastapi.responses import HTMLResponse

from ...config import apply_overrides
from ._core import (
    _require_admin,
    _require_admin_page,
    router,
    templates,
)

logger = logging.getLogger(__name__)


async def _ensure_signal_listener(app) -> None:
    """Start the Signal WebSocket listener if not already running.

    Guards against concurrent callers (e.g. overlapping HTMX polls) by
    setting a sentinel Future before the first await point.
    """
    from ..signal import signal_listener

    signal_task = getattr(app.state, "signal_task", None)
    if signal_task and not signal_task.done():
        return  # already running

    shutdown_event = getattr(app.state, "shutdown_event", None)
    if not shutdown_event:
        return

    # Set sentinel immediately to prevent a second caller from racing past
    # the done() check before create_task completes.
    sentinel = asyncio.get_running_loop().create_future()
    app.state.signal_task = sentinel

    try:
        task = asyncio.create_task(signal_listener(app.state, shutdown_event))
        app.state.signal_task = task
    except Exception:
        app.state.signal_task = None
        raise
    logger.info("Signal WebSocket listener started (auto-discovery)")


@router.get("/api/signal/status", response_class=HTMLResponse)
async def signal_status(request: Request):
    """Return Signal connection status fragment.

    Auto-discovers the phone number after QR-code linking via /v1/accounts
    and starts the WebSocket listener dynamically.

    Query params:
        linking=1  Keep "connecting" state while user scans QR code.
    """
    user, error = await _require_admin_page(request)
    if error:
        return error

    settings = request.app.state.settings
    signal_setup = getattr(request.app.state, "signal_setup_action", None)
    if not settings.signal_api_url or not signal_setup:
        return HTMLResponse(
            '<p class="text-sm text-zinc-500 py-2">Signal nicht konfiguriert.</p>'
        )

    linking = request.query_params.get("linking") == "1"
    signal_disabled = getattr(request.app.state, "signal_disabled", False)

    ctx = await signal_setup.get_status(settings, signal_disabled=signal_disabled)

    # Route handles app.state mutations when phone was auto-discovered
    phone_discovered = ctx.pop("phone_discovered", None)
    if phone_discovered:
        new_settings = apply_overrides(
            settings, {"signal_phone_number": phone_discovered}
        )
        request.app.state.settings = new_settings
        signal_action = getattr(request.app.state, "signal_action", None)
        if signal_action:
            signal_action.phone = phone_discovered
        await _ensure_signal_listener(request.app)
    elif linking and ctx["signal_status"] == "disconnected":
        ctx["signal_status"] = "connecting"

    return templates.TemplateResponse(request, "fragments/signal_status.html", ctx)


@router.get("/api/signal/qrcode")
async def signal_qrcode(request: Request):
    """Proxy QR code PNG from signal-cli-rest-api (admin only)."""
    user, error = await _require_admin_page(request)
    if error:
        return error

    signal_action = getattr(request.app.state, "signal_action", None)
    if not signal_action:
        return Response(status_code=404)

    png_bytes = await signal_action.get_qr_link(device_name="niles")
    if not png_bytes:
        return Response(status_code=502, content=b"QR code not available")

    return Response(content=png_bytes, media_type="image/png")


@router.post("/api/signal/link", response_class=HTMLResponse)
async def signal_link(request: Request):
    """Start linking process (show QR code)."""
    user, error = await _require_admin(request)
    if error:
        return error

    # Action handles DB persistence
    signal_setup = getattr(request.app.state, "signal_setup_action", None)
    if signal_setup:
        await signal_setup.enable_linking()

    # Route manages app.state cache
    request.app.state.signal_disabled = False

    return templates.TemplateResponse(
        request,
        "fragments/signal_status.html",
        {"signal_status": "connecting", "signal_phone": ""},
    )


@router.post("/api/signal/disconnect", response_class=HTMLResponse)
async def signal_disconnect(request: Request):
    """Unlink Signal device, stop listener, clear phone number."""
    _user, error = await _require_admin(request)
    if error:
        return error

    settings = request.app.state.settings

    # Route manages listener lifecycle (web concern)
    sig_task = getattr(request.app.state, "signal_task", None)
    if sig_task and not sig_task.done():
        sig_task.cancel()
        try:
            await sig_task
        except (asyncio.CancelledError, Exception):
            pass
    request.app.state.signal_task = None

    # Action handles API + DB
    signal_setup = getattr(request.app.state, "signal_setup_action", None)
    if signal_setup:
        await signal_setup.disconnect(settings.signal_phone_number)

    # Route manages app.state mutations
    new_settings = apply_overrides(settings, {"signal_phone_number": ""})
    request.app.state.settings = new_settings
    signal_action = getattr(request.app.state, "signal_action", None)
    if signal_action:
        signal_action.phone = ""
    request.app.state.signal_disabled = True

    logger.info("Signal disconnected")

    return templates.TemplateResponse(
        request,
        "fragments/signal_status.html",
        {"signal_status": "disconnected", "signal_phone": ""},
    )
