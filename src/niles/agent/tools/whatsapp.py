"""WhatsApp tools: send_whatsapp and get_whatsapp_messages."""

import logging
import time

from . import ToolContext, register_tool
from .formatting import format_message_transcript

logger = logging.getLogger(__name__)


@register_tool("send_whatsapp")
async def handle_send_whatsapp(args: dict, chat_id: str, ctx: ToolContext) -> dict:
    to = args["to"]
    text = args["text"]
    resolved_number: str

    # 1. Contact resolution (if name instead of number)
    if not to.replace("+", "").replace(" ", "").isdigit():
        contact = await ctx.contacts.find_by_name(to, user_id=ctx.user_id)
        if not contact:
            return {"error": f"Kontakt '{args['to']}' nicht gefunden"}
        phones = contact.get("phones", [])
        if len(phones) > 1:
            # Multiple numbers — store state and ask user to choose
            ctx.pending_phone_choices[chat_id] = {
                "phones": phones,
                "text": text,
                "contact_name": contact["full_name"],
                "expires_at": time.monotonic() + 300,
            }
            lines = [f"Es gibt mehrere Nummern für {contact['full_name']}:"]
            for i, p in enumerate(phones, 1):
                lines.append(f"{i}. 00{p['number']} ({p['type']})")
            return {"choose_phone": "\n".join(lines)}
        resolved_phone = contact.get("phone")
        if not resolved_phone:
            return {"error": f"Kontakt '{args['to']}' hat keine Telefonnummer"}
        resolved_number = resolved_phone
    else:
        resolved_number = to

    # 2. Self-check: own number is always allowed
    is_self = False
    own_number = await ctx.get_own_phone_number(chat_id)
    if own_number:
        normalized = resolved_number.replace("+", "").replace(" ", "")
        is_self = normalized == own_number or (len(own_number) >= 8 and normalized.endswith(own_number))

    # 3. Sending to others: only if feature flag is active
    if not is_self and not ctx.config.feature_whatsapp_send_others:
        logger.info("send_whatsapp to others disabled via feature flag")
        return {
            "error": "Das Senden an andere Personen ist deaktiviert. "
            "Du kannst diese Funktion in den Einstellungen aktivieren."
        }

    # 4. Confirmation before sending (skip for self-messages)
    instance = await ctx.resolve_wa_instance(chat_id)

    if is_self:
        result = await ctx.whatsapp.send_message(
            to=resolved_number,
            text=text,
            instance=instance,
        )
        return {"status": "sent", "to": resolved_number} if "error" not in result else result

    # Store pending confirmation and ask user
    display_to = to if to != resolved_number else resolved_number
    ctx.pending_confirmations[chat_id] = {
        "action": "send_whatsapp",
        "params": {"to": resolved_number, "text": text, "instance": instance},
        "display": f"WhatsApp an {display_to}: {text[:100]}",
        "expires_at": time.monotonic() + 300,
    }
    preview = text[:200] + ("..." if len(text) > 200 else "")
    return {
        "confirm": (
            f"Soll ich diese Nachricht senden?\nAn: {display_to}\nText: {preview}\n\nAntworte mit ja oder nein."
        )
    }


@register_tool("get_whatsapp_messages")
async def handle_get_whatsapp_messages(args: dict, chat_id: str, ctx: ToolContext) -> dict:
    contact_arg = args.get("contact", "").strip()
    if not contact_arg:
        return {"error": "Bitte Kontaktname oder Telefonnummer angeben"}

    phone, err = await ctx.resolve_contact_phone(contact_arg, user_id=ctx.user_id)
    if err:
        return err

    # Build JID and resolve per-user instance
    jid = f"{phone}@s.whatsapp.net"
    instance = await ctx.resolve_wa_instance(chat_id)

    messages = await ctx.whatsapp.fetch_messages(
        remote_jid=jid,
        instance=instance,
    )
    if not messages:
        return {
            "error": "Keine WhatsApp-Nachrichten gefunden",
            "hint": "Es werden nur Nachrichten der letzten 30 Tage angezeigt.",
        }

    # Determine display name for the contact
    contact_name: str = (
        contact_arg
        if not contact_arg.replace("+", "").replace(" ", "").isdigit()
        else (messages[0].get("push_name") or phone or "Unbekannt")
    )

    return format_message_transcript(
        messages=messages,
        contact_name=contact_name,
        timezone_str=ctx.config.timezone,
    )
