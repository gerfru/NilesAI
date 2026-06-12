# SPDX-License-Identifier: AGPL-3.0-only
"""Signal device setup and teardown for the Settings UI."""

import logging

from ..config import Settings
from ..settings_store import SettingsStore
from .signal import SignalAction

logger = logging.getLogger(__name__)


class SignalSetupAction:
    """Manage Signal device linking (connect/disconnect/status).

    Handles signal-cli-rest-api calls + settings persistence.
    Routes manage app.state lifecycle (listener task, disabled flag cache,
    Settings object swap) because those are web-specific runtime concerns.
    """

    def __init__(
        self,
        signal_action: SignalAction,
        *,
        settings_store: SettingsStore,
    ):
        self.signal_action = signal_action
        self.settings_store = settings_store

    async def get_status(
        self,
        current_settings: Settings,
        *,
        signal_disabled: bool = False,
    ) -> dict:
        """Return Signal connection status for template context.

        Returns dict with keys:
            signal_status: "connected" | "disconnected"
            signal_phone: str (phone number or "")
            phone_discovered: str | None (newly discovered phone, or None)

        The ``phone_discovered`` field signals to the route that a phone was
        auto-discovered and app.state needs updating.  This avoids the action
        having to mutate app.state directly.
        """
        ctx: dict = {
            "signal_status": "disconnected",
            "signal_phone": "",
            "phone_discovered": None,
        }

        # Already known
        if current_settings.signal_phone_number:
            ctx["signal_status"] = "connected"
            ctx["signal_phone"] = current_settings.signal_phone_number
            return ctx

        # Intentionally disabled — skip auto-discovery
        if signal_disabled:
            return ctx

        # Auto-discover via signal-cli-rest-api
        accounts = await self.signal_action.get_accounts()
        if accounts:
            phone = accounts[0]
            logger.info("Signal phone auto-discovered: %s", phone)
            await self.settings_store.set("signal_phone_number", phone)
            ctx["signal_status"] = "connected"
            ctx["signal_phone"] = phone
            ctx["phone_discovered"] = phone

        return ctx

    async def enable_linking(self) -> None:
        """Clear the disabled flag in DB so auto-discovery works again.

        Route is responsible for also clearing ``app.state.signal_disabled``.
        """
        await self.settings_store.delete("signal_disabled")

    async def disconnect(self, phone: str) -> None:
        """Unlink device via signal-cli-rest-api and clear settings in DB.

        Route is responsible for:
        - Cancelling the WebSocket listener task
        - Updating ``app.state.settings``
        - Setting ``app.state.signal_disabled = True``
        - Clearing ``signal_action.phone``
        """
        if phone:
            try:
                await self.signal_action.unlink(phone)
            except Exception:
                logger.warning("Signal unlink failed for %s, proceeding with cleanup", phone)

        await self.settings_store.delete("signal_phone_number")
        await self.settings_store.set("signal_disabled", "true")
        logger.info("Signal disconnected (API + DB)")
