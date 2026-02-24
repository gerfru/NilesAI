"""Scheduled briefing jobs."""

import logging

logger = logging.getLogger(__name__)


async def _get_connected_number(whatsapp, instance: str) -> str | None:
    """Return the owner phone number if WhatsApp is connected, else None."""
    try:
        state = await whatsapp.get_connection_state(instance)
    except Exception:
        logger.warning("Briefing: WhatsApp connection state nicht abrufbar")
        return None

    if state != "open":
        logger.info("Briefing: WhatsApp nicht verbunden (state=%s)", state)
        return None

    owner_jid = await whatsapp.get_owner_jid(instance)
    if not owner_jid or "@" not in owner_jid:
        logger.warning("Briefing: ownerJid nicht verfuegbar")
        return None

    return owner_jid.split("@")[0]


async def send_daily_briefing(app_state) -> None:
    """Generate and send the daily briefing via WhatsApp.

    Called by APScheduler. Auto-detects the connected WhatsApp number.
    """
    settings = app_state.settings
    whatsapp = app_state.whatsapp_action

    number = await _get_connected_number(whatsapp, settings.evolution_instance)
    if not number:
        return

    briefing = app_state.briefing_generator

    try:
        message = await briefing.generate_daily()
        await whatsapp.send_message(to=number, text=message)
        logger.info("Daily briefing sent to %s", number)
    except Exception:
        logger.exception("Failed to send daily briefing")


async def send_weekly_briefing(app_state) -> None:
    """Generate and send the weekly briefing via WhatsApp.

    Called by APScheduler on Mondays, before the daily briefing.
    Auto-detects the connected WhatsApp number.
    """
    settings = app_state.settings
    whatsapp = app_state.whatsapp_action

    number = await _get_connected_number(whatsapp, settings.evolution_instance)
    if not number:
        return

    briefing = app_state.briefing_generator

    try:
        message = await briefing.generate_weekly()
        await whatsapp.send_message(to=number, text=message)
        logger.info("Weekly briefing sent to %s", number)
    except Exception:
        logger.exception("Failed to send weekly briefing")
