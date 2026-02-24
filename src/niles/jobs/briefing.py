"""Scheduled briefing jobs."""

import logging

logger = logging.getLogger(__name__)


async def _get_connected_number(app_state) -> tuple[str | None, str | None]:
    """Return (phone_number, instance_name) from a connected WhatsApp session.

    Queries the whatsapp_sessions table for any session with status='connected'.
    Returns (None, None) if no connected session exists.
    """
    pool = app_state.pool
    try:
        row = await pool.fetchrow(
            "SELECT phone_number, instance_name FROM whatsapp_sessions "
            "WHERE status = 'connected' AND phone_number IS NOT NULL "
            "LIMIT 1"
        )
    except Exception:
        logger.warning("Briefing: whatsapp_sessions nicht abrufbar")
        return None, None

    if not row or not row["phone_number"]:
        logger.info("Briefing: Keine verbundene WhatsApp-Session gefunden")
        return None, None

    return row["phone_number"], row["instance_name"]


async def send_daily_briefing(app_state) -> bool:
    """Generate and send the daily briefing via WhatsApp.

    Called by APScheduler. Uses the connected WhatsApp session from DB.
    Returns True if the briefing was sent, False if no session was available.
    """
    number, instance = await _get_connected_number(app_state)
    if not number:
        return False

    briefing = app_state.briefing_generator
    whatsapp = app_state.whatsapp_action

    try:
        message = await briefing.generate_daily()
        await whatsapp.send_message(to=number, text=message, instance=instance)
        logger.info("Daily briefing sent to %s", number)
        return True
    except Exception:
        logger.exception("Failed to send daily briefing")
        return False


async def send_weekly_briefing(app_state) -> bool:
    """Generate and send the weekly briefing via WhatsApp.

    Called by APScheduler on Mondays, before the daily briefing.
    Uses the connected WhatsApp session from DB.
    Returns True if the briefing was sent, False if no session was available.
    """
    number, instance = await _get_connected_number(app_state)
    if not number:
        return False

    briefing = app_state.briefing_generator
    whatsapp = app_state.whatsapp_action

    try:
        message = await briefing.generate_weekly()
        await whatsapp.send_message(to=number, text=message, instance=instance)
        logger.info("Weekly briefing sent to %s", number)
        return True
    except Exception:
        logger.exception("Failed to send weekly briefing")
        return False
