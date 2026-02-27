"""Scheduled briefing jobs."""

import logging

logger = logging.getLogger(__name__)


async def _get_connected_session(
    app_state,
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


async def _send_via_whatsapp(app_state, message: str) -> bool:
    """Send briefing message via WhatsApp. Returns True on success."""
    number, instance, _user_id = await _get_connected_session(app_state)
    if not number:
        return False
    try:
        await app_state.whatsapp_action.send_message(
            to=number, text=message, instance=instance
        )
        logger.info("Briefing sent via WhatsApp to %s", number)
        return True
    except Exception:
        logger.exception("Failed to send briefing via WhatsApp")
        return False


async def _send_via_signal(app_state, message: str) -> bool:
    """Send briefing message via Signal. Returns True on success."""
    signal_action = getattr(app_state, "signal_action", None)
    if not signal_action or not app_state.settings.signal_phone_number:
        logger.info("Briefing: Signal nicht konfiguriert")
        return False
    try:
        await signal_action.send_message(
            to=app_state.settings.signal_phone_number, text=message
        )
        logger.info("Briefing sent via Signal")
        return True
    except Exception:
        logger.exception("Failed to send briefing via Signal")
        return False


async def _send_briefing(app_state, message: str) -> bool:
    """Send a briefing message via the configured channel(s).

    Respects settings.briefing_channel: whatsapp | signal | both.
    Returns True if at least one channel succeeded.
    """
    channel = getattr(app_state.settings, "briefing_channel", "whatsapp")
    sent_any = False

    if channel in ("whatsapp", "both"):
        if await _send_via_whatsapp(app_state, message):
            sent_any = True

    if channel in ("signal", "both"):
        if await _send_via_signal(app_state, message):
            sent_any = True

    return sent_any


async def _resolve_briefing_user_id(app_state) -> int | None:
    """Get the user_id of the connected WhatsApp session for per-user tasks."""
    _number, _instance, user_id = await _get_connected_session(app_state)
    return user_id


async def send_daily_briefing(app_state) -> bool:
    """Generate and send the daily briefing.

    Called by APScheduler. Sends via the configured briefing channel.
    Returns True if the briefing was sent, False if no channel was available.
    """
    briefing = app_state.briefing_generator
    # Refresh weather coordinates from current settings (may change at runtime)
    settings = app_state.settings
    briefing.weather_latitude = settings.weather_latitude
    briefing.weather_longitude = settings.weather_longitude
    user_id = await _resolve_briefing_user_id(app_state)
    try:
        message = await briefing.generate_daily(user_id=user_id)
    except Exception:
        logger.exception("Failed to generate daily briefing")
        return False

    return await _send_briefing(app_state, message)


async def send_weekly_briefing(app_state) -> bool:
    """Generate and send the weekly briefing.

    Called by APScheduler on Mondays, before the daily briefing.
    Sends via the configured briefing channel.
    Returns True if the briefing was sent, False if no channel was available.
    """
    briefing = app_state.briefing_generator
    # Refresh weather coordinates from current settings (may change at runtime)
    settings = app_state.settings
    briefing.weather_latitude = settings.weather_latitude
    briefing.weather_longitude = settings.weather_longitude
    user_id = await _resolve_briefing_user_id(app_state)
    try:
        message = await briefing.generate_weekly(user_id=user_id)
    except Exception:
        logger.exception("Failed to generate weekly briefing")
        return False

    return await _send_briefing(app_state, message)
