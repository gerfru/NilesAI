"""WhatsApp session management routes."""

import logging

import asyncpg
from fastapi import Request, Response
from fastapi.responses import HTMLResponse

from ._core import (
    SESSION_COOKIE_NAME,
    _get_session_user,
    _require_auth_and_csrf,
    router,
    templates,
)

logger = logging.getLogger(__name__)


@router.get("/api/whatsapp/status", response_class=HTMLResponse)
async def whatsapp_status(request: Request):
    """Return WhatsApp connection status fragment."""
    user = _get_session_user(request)
    if user is None:
        return Response(status_code=401, headers={"HX-Redirect": "/ui/login"})

    wa_store = getattr(request.app.state, "wa_store", None)
    if not wa_store:
        return HTMLResponse(
            '<p class="text-sm text-zinc-500 dark:text-zinc-400 py-2">'
            "WhatsApp nicht verfuegbar.</p>"
        )

    session = await wa_store.get_session(user["uid"])
    ctx: dict = {"wa_status": "disconnected", "wa_phone": "", "wa_qr": ""}

    if session:
        whatsapp_action = request.app.state.whatsapp_action
        state = await whatsapp_action.get_connection_state(session["instance_name"])

        if state == "open":
            phone = session.get("phone_number")
            if not phone or session["status"] != "connected":
                # Fetch phone from Evolution API (ownerJid)
                owner_jid = await whatsapp_action.get_owner_jid(
                    session["instance_name"],
                )
                if owner_jid and "@" in owner_jid:
                    phone = owner_jid.split("@")[0]
                await wa_store.update_status(
                    user["uid"],
                    "connected",
                    phone_number=phone,
                )
            ctx["wa_status"] = "connected"
            ctx["wa_phone"] = phone or ""
        elif session["status"] == "connecting":
            ctx["wa_status"] = "connecting"
            # Fetch fresh QR code
            qr_data = await whatsapp_action.get_qr_code(session["instance_name"])
            ctx["wa_qr"] = qr_data.get("base64", "")
        else:
            # Instance exists in DB but Evolution says closed — stale row
            # will be overwritten on next reconnect via upsert_session
            ctx["wa_status"] = "disconnected"

    return templates.TemplateResponse(request, "fragments/whatsapp_status.html", ctx)


@router.post("/api/whatsapp/connect", response_class=HTMLResponse)
async def whatsapp_connect(request: Request):
    """Create an Evolution API instance and return QR code fragment."""
    user, error = await _require_auth_and_csrf(request)
    if error:
        return error
    assert user is not None

    wa_store = getattr(request.app.state, "wa_store", None)
    whatsapp_action = request.app.state.whatsapp_action
    if not wa_store:
        return HTMLResponse(
            '<p class="text-sm text-red-500">WhatsApp nicht verfuegbar.</p>'
        )

    instance_name = f"niles-wa-{user['uid']}"
    # Use internal Docker address — Evolution API and Niles Core are on the
    # same Docker network, so no TLS needed (avoids self-signed cert errors).
    # Configurable via WEBHOOK_BASE_URL for non-standard Docker setups.
    settings = request.app.state.settings
    webhook_url = (
        f"{settings.webhook_base_url.rstrip('/')}/webhook/whatsapp"
        f"?token={settings.evolution_api_key}"
    )

    result = await whatsapp_action.create_instance(instance_name, webhook_url)

    if "error" in result:
        # Instance may already exist — try to get QR code directly
        qr_data = await whatsapp_action.get_qr_code(instance_name)
        qr_base64 = qr_data.get("base64", "")
    else:
        qr_base64 = result.get("qrcode", {}).get("base64", "")

    try:
        await wa_store.upsert_session(user["uid"], instance_name, status="connecting")
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
        "fragments/whatsapp_status.html",
        {
            "wa_status": "connecting",
            "wa_qr": qr_base64,
            "wa_phone": "",
        },
    )


@router.post("/api/whatsapp/disconnect", response_class=HTMLResponse)
async def whatsapp_disconnect(request: Request):
    """Logout and delete the user's Evolution API instance."""
    user, error = await _require_auth_and_csrf(request)
    if error:
        return error
    assert user is not None

    wa_store = getattr(request.app.state, "wa_store", None)
    whatsapp_action = request.app.state.whatsapp_action
    if not wa_store:
        return HTMLResponse(
            '<p class="text-sm text-red-500">WhatsApp nicht verfuegbar.</p>'
        )

    session = await wa_store.get_session(user["uid"])
    if session:
        instance_name = session["instance_name"]
        await whatsapp_action.logout_instance(instance_name)
        await whatsapp_action.delete_instance(instance_name)
        await wa_store.delete_session(user["uid"])

    return templates.TemplateResponse(
        request,
        "fragments/whatsapp_status.html",
        {
            "wa_status": "disconnected",
            "wa_phone": "",
            "wa_qr": "",
        },
    )
