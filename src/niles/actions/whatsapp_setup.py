# SPDX-License-Identifier: AGPL-3.0-only
"""WhatsApp instance setup and teardown for the Settings UI."""

import logging

from ..whatsapp_store import WhatsAppSessionStore
from .whatsapp import WhatsAppAction

logger = logging.getLogger(__name__)


class WhatsAppSetupAction:
    """Manage per-user WhatsApp instances (connect/disconnect/status).

    Orchestrates Evolution API calls + session store persistence.
    Routes handle HTTP concerns (CSRF, auth, templates, FK violations).
    """

    def __init__(
        self,
        wa_store: WhatsAppSessionStore,
        whatsapp_action: WhatsAppAction,
        *,
        webhook_base_url: str = "",
        webhook_token: str = "",
    ):
        self.wa_store = wa_store
        self.whatsapp_action = whatsapp_action
        self.webhook_base_url = webhook_base_url
        self.webhook_token = webhook_token

    async def get_status(self, user_id: int) -> dict:
        """Return WhatsApp connection status for template context.

        Returns dict with keys: wa_status, wa_phone, wa_qr.
        wa_status is one of: "disconnected", "connected", "connecting".

        Side effect: updates session status/phone in DB if connection
        state changed since last check (e.g. QR code was scanned).
        """
        ctx: dict = {"wa_status": "disconnected", "wa_phone": "", "wa_qr": ""}

        session = await self.wa_store.get_session(user_id)
        if not session:
            return ctx

        state = await self.whatsapp_action.get_connection_state(session["instance_name"])

        if state == "open":
            phone = session.get("phone_number")
            if not phone or session["status"] != "connected":
                owner_jid = await self.whatsapp_action.get_owner_jid(
                    session["instance_name"],
                )
                if owner_jid and "@" in owner_jid:
                    phone = owner_jid.split("@")[0]
                await self.wa_store.update_status(user_id, "connected", phone_number=phone)
            ctx["wa_status"] = "connected"
            ctx["wa_phone"] = phone or ""
        elif session["status"] == "connecting":
            ctx["wa_status"] = "connecting"
            qr_data = await self.whatsapp_action.get_qr_code(session["instance_name"])
            ctx["wa_qr"] = qr_data.get("base64", "")
        else:
            ctx["wa_status"] = "disconnected"

        return ctx

    async def connect(self, user_id: int) -> dict:
        """Create Evolution API instance and persist session.

        Generates instance name, constructs webhook URL, creates instance
        via Evolution API, upserts session in DB.

        Returns dict with keys: wa_status, wa_qr, wa_phone.
        Raises asyncpg.ForeignKeyViolationError if user_id is invalid
        (route handles this with cookie deletion + redirect).
        """
        instance_name = f"niles-wa-{user_id}"
        # Evolution API requires the token as a query parameter for webhook
        # authentication — header-based auth is not supported. We therefore use
        # a dedicated webhook_token (not the Evolution admin key) so a query-string
        # log leak cannot escalate to admin control.
        webhook_url = f"{self.webhook_base_url.rstrip('/')}/webhook/whatsapp?token={self.webhook_token}"

        result = await self.whatsapp_action.create_instance(instance_name, webhook_url)

        if "error" in result:
            # Instance may already exist — try to get QR code directly
            qr_data = await self.whatsapp_action.get_qr_code(instance_name)
            qr_base64 = qr_data.get("base64", "")
        else:
            qr_base64 = result.get("qrcode", {}).get("base64", "")

        # May raise asyncpg.ForeignKeyViolationError — caller handles it
        await self.wa_store.upsert_session(user_id, instance_name, status="connecting")

        return {"wa_status": "connecting", "wa_qr": qr_base64, "wa_phone": ""}

    async def disconnect(self, user_id: int) -> None:
        """Logout and delete Evolution API instance, remove DB session.

        Orchestrates: logout_instance -> delete_instance -> delete_session.
        No-op if no session exists for this user.
        """
        session = await self.wa_store.get_session(user_id)
        if not session:
            return

        instance_name = session["instance_name"]
        await self.whatsapp_action.logout_instance(instance_name)
        await self.whatsapp_action.delete_instance(instance_name)
        await self.wa_store.delete_session(user_id)
