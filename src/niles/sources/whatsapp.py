"""WhatsApp webhook handler for Evolution API."""

import hmac
import logging

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook", tags=["webhooks"])


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
    expected = settings.evolution_api_key
    if not token or len(token) > 256 or not hmac.compare_digest(token, expected):
        logger.warning("Webhook request with invalid or missing token")
        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})

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

    # Ignore own messages
    if key.get("fromMe", False):
        return {"status": "ignored", "reason": "own message"}

    remote_jid = key.get("remoteJid", "")
    message = data.get("message", {})

    # Extract text from different message types
    text = (
        message.get("conversation")
        or message.get("extendedTextMessage", {}).get("text")
    )

    if not text:
        return {"status": "ignored", "reason": "no text content"}

    # Extract phone number from JID (e.g. "436601234567@s.whatsapp.net")
    sender = remote_jid.split("@")[0] if "@" in remote_jid else remote_jid

    logger.info("WhatsApp message from %s: %s", sender, text[:100])

    # Determine per-user chat ID from Evolution instance name
    instance_name = payload.get("instance")
    wa_store = getattr(request.app.state, "wa_store", None)
    chat_id = None
    instance_for_reply = None

    if wa_store and instance_name:
        session = await wa_store.get_by_instance(instance_name)
        if session:
            chat_id = f"web-user-{session['user_id']}"
            instance_for_reply = instance_name

    # Fallback: use sender phone as chat ID (legacy global instance)
    if not chat_id:
        chat_id = f"wa-{sender}"

    # Process via agent
    agent = request.app.state.agent
    event = {
        "type": "whatsapp",
        "from": chat_id,
        "content": text,
        "metadata": {"jid": remote_jid, "sender": sender},
    }

    try:
        response_text = await agent.process_event(event)

        # Send reply only if auto-reply is enabled
        settings = request.app.state.settings
        if response_text and settings.feature_whatsapp_auto_reply:
            whatsapp_action = request.app.state.whatsapp_action
            await whatsapp_action.send_message(
                to=remote_jid, text=response_text, instance=instance_for_reply,
            )
        elif response_text:
            logger.info("Auto-reply disabled, suppressed response to %s", sender)
    except Exception:
        logger.exception("Failed to process WhatsApp message from %s", sender)

    return {"status": "processed"}
