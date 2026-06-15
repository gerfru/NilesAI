# SPDX-License-Identifier: AGPL-3.0-only
"""WhatsApp webhook handler for Evolution API."""

import hmac
import logging

import structlog
from fastapi import APIRouter, Query, Request

from ..errors import error_response
from ..redaction import redact_phone

from .echo_guard import EchoGuard
from .triggers import is_niles_trigger, strip_trigger

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook", tags=["webhooks"])

# Echo-loop guard: Evolution API echoes outbound messages back as
# MESSAGES_UPSERT with fromMe=True. Keyed by message ID.
_echo_guard = EchoGuard(ttl=10.0)


async def _handle_self_chat(text: str, remote_jid: str, payload: dict, request: Request) -> dict:
    """Process a self-chat trigger message (fromMe=True with Niles trigger)."""
    if not is_niles_trigger(text):
        return {"status": "ignored", "reason": "own message without trigger"}

    clean_text = strip_trigger(text) or "Hallo!"
    sender = remote_jid.split("@")[0] if "@" in remote_jid else remote_jid
    logger.info("Self-chat trigger from %s (%d chars)", redact_phone(sender), len(clean_text))

    chat_id = f"wa-self-{sender}"
    structlog.contextvars.bind_contextvars(chat_id=chat_id, source="whatsapp")

    instance_for_reply = payload.get("instance")
    agent = request.app.state.agent
    event = {
        "type": "whatsapp",
        "from": chat_id,
        "content": clean_text,
        "metadata": {
            "jid": remote_jid,
            "sender": sender,
            "self_chat": True,
        },
    }

    try:
        response_text = await agent.process_event(event)
        if response_text:
            whatsapp_action = request.app.state.whatsapp_action
            result = await whatsapp_action.send_message(
                to=remote_jid,
                text=response_text,
                instance=instance_for_reply,
            )
            sent_id = result.get("key", {}).get("id") if isinstance(result, dict) else None
            if sent_id:
                _echo_guard.record(sent_id)
                logger.info("Self-chat reply sent to %s", redact_phone(remote_jid))
            else:
                logger.warning("No message ID in send_message response — echo guard not armed")
    except Exception:
        logger.exception("Failed to process self-chat message")

    return {"status": "processed", "trigger": "self-chat"}


@router.post("/whatsapp")
async def whatsapp_webhook(request: Request, token: str = Query(default="")):
    """
    Evolution API webhook handler.

    Receives MESSAGES_UPSERT events and forwards them to the agent.
    Requires a valid token query parameter for authentication.
    Returns 401 for auth failures, 200 for all other cases to prevent
    retry-spam from Evolution.
    """
    settings = request.app.state.settings
    expected = settings.webhook_token
    if not token or len(token) > 256 or not hmac.compare_digest(token, expected):
        logger.warning("Webhook request with invalid or missing token")
        return error_response(401, "Unauthorized")

    try:
        payload = await request.json()
    except Exception:
        logger.warning("Invalid JSON in webhook payload")
        return {"status": "ignored"}

    event_type = payload.get("event")
    if event_type != "messages.upsert":
        return {"status": "ignored", "reason": f"event type: {event_type}"}

    data = payload.get("data", {})
    key = data.get("key", {})
    is_from_me = key.get("fromMe", False)
    remote_jid = key.get("remoteJid", "")
    # WhatsApp LID addressing: prefer phone-based JID over opaque LID
    if remote_jid.endswith("@lid"):
        remote_jid = key.get("remoteJidAlt", remote_jid)
    msg_id = key.get("id", "")
    message = data.get("message", {})

    # Skip echoed messages that the agent itself sent (prevents reply loops)
    if is_from_me and msg_id and _echo_guard.is_echo(msg_id):
        return {"status": "ignored", "reason": "echo of own reply"}

    # Extract text from different message types
    # fmt: off
    text = (
        message.get("conversation")
        or message.get("extendedTextMessage", {}).get("text")
    )
    # fmt: on

    if not text:
        return {"status": "ignored", "reason": "no text content"}

    # --- Self-Chat Trigger Logic ---
    if is_from_me:
        return await _handle_self_chat(text, remote_jid, payload, request)

    # --- Group messages: ignore (not supported yet) ---
    if remote_jid.endswith("@g.us"):
        return {"status": "ignored", "reason": "group message"}

    # --- Incoming messages from other people ---
    # Evolution API stores messages internally — no local DB needed.
    # Agent queries them via get_whatsapp_messages → Evolution API findMessages.
    sender = remote_jid.split("@")[0] if "@" in remote_jid else remote_jid
    logger.info("WhatsApp message from %s (stored by Evolution API)", redact_phone(sender))
    return {"status": "received", "sender": sender}
