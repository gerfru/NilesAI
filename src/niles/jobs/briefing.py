# SPDX-License-Identifier: AGPL-3.0-only
"""Scheduled briefing jobs."""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from niles.actions.briefing import BriefingGenerator
    from niles.config import Settings
    from niles.types import AppState

logger = logging.getLogger(__name__)


async def _get_connected_session(
    app_state: "AppState",
) -> tuple[str | None, str | None, int | None]:
    """Return (phone_number, instance_name, user_id) from a connected WhatsApp session.

    Queries the whatsapp_sessions table for any session with status='connected'.
    Returns (None, None, None) if no connected session exists.
    """
    pool = app_state.pool
    try:
        row = await pool.fetchrow(
            "SELECT phone_number, instance_name, user_id FROM whatsapp_sessions "
            "WHERE status = 'connected' AND phone_number IS NOT NULL "
            "LIMIT 1"
        )
    except Exception:
        logger.warning("Briefing: whatsapp_sessions nicht abrufbar")
        return None, None, None

    if not row or not row["phone_number"]:
        logger.info("Briefing: Keine verbundene WhatsApp-Session gefunden")
        return None, None, None

    return row["phone_number"], row["instance_name"], row["user_id"]


async def _send_via_whatsapp(app_state: "AppState", message: str, number: str, instance: str | None) -> bool:
    """Send briefing message via WhatsApp using pre-resolved session. Returns True on success."""
    try:
        await app_state.whatsapp_action.send_message(to=number, text=message, instance=instance)
        logger.info("Briefing sent via WhatsApp to %s", number)
        return True
    except Exception:
        logger.exception("Failed to send briefing via WhatsApp")
        return False


async def _send_via_signal(app_state: "AppState", message: str) -> bool:
    """Send briefing message via Signal. Returns True on success."""
    signal_action = getattr(app_state, "signal_action", None)
    if not signal_action or not app_state.settings.signal_phone_number:
        logger.info("Briefing: Signal nicht konfiguriert")
        return False
    try:
        await signal_action.send_message(to=app_state.settings.signal_phone_number, text=message)
        logger.info("Briefing sent via Signal")
        return True
    except Exception:
        logger.exception("Failed to send briefing via Signal")
        return False


async def _send_briefing(app_state: "AppState", message: str, wa_number: str | None, wa_instance: str | None) -> bool:
    """Send a briefing message via the configured channel(s).

    Respects settings.briefing_channel: whatsapp | signal | both.
    Returns True if at least one channel succeeded.
    """
    channel = getattr(app_state.settings, "briefing_channel", "whatsapp")
    sent_any = False

    if channel in ("whatsapp", "both") and wa_number:
        if await _send_via_whatsapp(app_state, message, wa_number, wa_instance):
            sent_any = True

    if channel in ("signal", "both"):
        if await _send_via_signal(app_state, message):
            sent_any = True

    return sent_any


def _refresh_weather_coords(briefing: "BriefingGenerator", settings: "Settings") -> None:
    """Sync weather coordinates from current settings (may change at runtime)."""
    briefing.weather_latitude = settings.weather_latitude
    briefing.weather_longitude = settings.weather_longitude


async def send_daily_briefing(app_state: "AppState") -> bool:
    """Generate and send the daily briefing.

    Called by APScheduler. Sends via the configured briefing channel.
    Returns True if the briefing was sent, False if no channel was available.
    """
    number, instance, user_id = await _get_connected_session(app_state)

    briefing = app_state.briefing_generator
    _refresh_weather_coords(briefing, app_state.settings)
    try:
        message = await briefing.generate_daily(user_id=user_id)
    except Exception:
        logger.exception("Failed to generate daily briefing")
        return False

    return await _send_briefing(app_state, message, number, instance)


async def send_weekly_briefing(app_state: "AppState") -> bool:
    """Generate and send the weekly briefing.

    Called by APScheduler on Mondays, before the daily briefing.
    Sends via the configured briefing channel.
    Returns True if the briefing was sent, False if no channel was available.
    """
    number, instance, user_id = await _get_connected_session(app_state)

    briefing = app_state.briefing_generator
    _refresh_weather_coords(briefing, app_state.settings)
    try:
        message = await briefing.generate_weekly(user_id=user_id)
    except Exception:
        logger.exception("Failed to generate weekly briefing")
        return False

    return await _send_briefing(app_state, message, number, instance)
