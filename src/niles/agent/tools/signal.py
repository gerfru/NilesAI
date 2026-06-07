"""Signal tools: send_signal and get_signal_messages."""

import logging
import time

from . import ToolContext, register_tool
from .formatting import format_message_transcript

logger = logging.getLogger(__name__)


@register_tool("send_signal")
async def handle_send_signal(args: dict, chat_id: str, ctx: ToolContext) -> dict:
    to = args["to"]
    text = args["text"]

    # 1. Contact resolution (if name instead of number)
    phone, err = await ctx.resolve_contact_phone(to)
    if err:
        return err
    resolved_number = f"+{phone}"

    # 2. Self-check: own number is always allowed
    own_phone = ctx.config.signal_phone_number
    is_self = resolved_number == own_phone

    # 3. Sending to others: only if feature flag is active
    if not is_self and not ctx.config.feature_signal_send_others:
        logger.info("send_signal to others disabled via feature flag")
        return {
            "error": "Das Senden an andere Personen ist deaktiviert. "
            "Du kannst diese Funktion in den Einstellungen aktivieren."
        }

    # 4. Confirmation before sending (skip for self-messages)
    if not ctx.signal:
        return {"error": "Signal ist nicht konfiguriert"}

    if is_self:
        result = await ctx.signal.send_message(to=resolved_number, text=text)
        return {"status": "sent", "to": resolved_number} if "error" not in result else result

    # Store pending confirmation and ask user
    display_to = to if to != resolved_number else resolved_number
    ctx.pending_confirmations[chat_id] = {
        "action": "send_signal",
        "params": {"to": resolved_number, "text": text},
        "display": f"Signal an {display_to}: {text[:100]}",
        "expires_at": time.monotonic() + 300,
    }
    preview = text[:200] + ("..." if len(text) > 200 else "")
    return {
        "confirm": (
            f"Soll ich diese Signal-Nachricht senden?\nAn: {display_to}\nText: {preview}\n\nAntworte mit ja oder nein."
        )
    }


@register_tool("get_signal_messages")
async def handle_get_signal_messages(args: dict, chat_id: str, ctx: ToolContext) -> dict:
    contact_arg = args.get("contact", "").strip()
    if not contact_arg:
        return {"error": "Bitte Kontaktname oder Telefonnummer angeben"}

    phone, err = await ctx.resolve_contact_phone(contact_arg)
    if err:
        return err
    phone = f"+{phone}"

    if not ctx.signal_store:
        return {"error": "Signal ist nicht konfiguriert"}
    messages = await ctx.signal_store.get_messages(phone=phone)
    if not messages:
        return {
            "error": "Keine Signal-Nachrichten gefunden",
            "hint": "Es werden nur Nachrichten der letzten 30 Tage angezeigt.",
        }

    # Determine display name for the contact
    contact_name = contact_arg if not contact_arg.replace("+", "").replace(" ", "").isdigit() else phone

    return format_message_transcript(
        messages=messages,
        contact_name=contact_name,
        timezone_str=ctx.config.timezone,
    )
