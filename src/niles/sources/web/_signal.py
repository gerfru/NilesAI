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
    if not settings.signal_api_url:
        return HTMLResponse(
            '<p class="text-sm text-zinc-500 py-2">Signal nicht konfiguriert.</p>'
        )

    signal_action = getattr(request.app.state, "signal_action", None)
    if not signal_action:
        return HTMLResponse(
            '<p class="text-sm text-zinc-500 py-2">Signal nicht konfiguriert.</p>'
        )

    linking = request.query_params.get("linking") == "1"
    ctx = {"signal_status": "disconnected", "signal_phone": ""}

    # Check if user intentionally disconnected (suppress auto-discovery).
    # Cached in app.state to avoid DB query on every 3s HTMX poll.
    signal_disabled = getattr(request.app.state, "signal_disabled", False)

    # Check if already known
    if settings.signal_phone_number:
        ctx["signal_status"] = "connected"
        ctx["signal_phone"] = settings.signal_phone_number
    elif not signal_disabled:
        # Auto-discover: check linked accounts via signal-cli-rest-api.
        # Note: concurrent HTMX polls may both reach this point, but
        # the duplicate DB write is harmless (same value).
        accounts = await signal_action.get_accounts()
        if accounts:
            phone = accounts[0]
            logger.info("Signal phone auto-discovered: %s", phone)
            # Update via apply_overrides for consistency with other settings
            new_settings = apply_overrides(settings, {"signal_phone_number": phone})
            request.app.state.settings = new_settings
            signal_action.phone = phone
            settings_store = getattr(request.app.state, "settings_store", None)
            if settings_store:
                await settings_store.set("signal_phone_number", phone)
            # Start WebSocket listener if not running
            await _ensure_signal_listener(request.app)
            ctx["signal_status"] = "connected"
            ctx["signal_phone"] = phone
        elif linking:
            # QR code displayed, waiting for user to scan
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

    # Clear the disabled flag so auto-discovery works again
    request.app.state.signal_disabled = False
    settings_store = getattr(request.app.state, "settings_store", None)
    if settings_store:
        await settings_store.delete("signal_disabled")

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
    signal_action = getattr(request.app.state, "signal_action", None)

    # Stop WebSocket listener
    sig_task = getattr(request.app.state, "signal_task", None)
    if sig_task and not sig_task.done():
        sig_task.cancel()
        try:
            await sig_task
        except (asyncio.CancelledError, Exception):
            pass
    request.app.state.signal_task = None

    # Unlink device via signal-cli-rest-api
    if signal_action and settings.signal_phone_number:
        await signal_action.unlink(settings.signal_phone_number)

    # Clear phone number and mark as intentionally disabled (runtime + DB)
    new_settings = apply_overrides(settings, {"signal_phone_number": ""})
    request.app.state.settings = new_settings
    if signal_action:
        signal_action.phone = ""
    request.app.state.signal_disabled = True
    settings_store = getattr(request.app.state, "settings_store", None)
    if settings_store:
        await settings_store.delete("signal_phone_number")
        await settings_store.set("signal_disabled", "true")

    logger.info("Signal disconnected")

    return templates.TemplateResponse(
        request,
        "fragments/signal_status.html",
        {"signal_status": "disconnected", "signal_phone": ""},
    )
