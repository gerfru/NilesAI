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
    Always returns 200 to prevent retry-spam from Evolution.
    """
    settings = request.app.state.settings
    expected = settings.evolution_api_key
    if not token or not hmac.compare_digest(token, expected):
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

    # Extract phone number from JID (e.g. "4366012345678@s.whatsapp.net")
    sender = remote_jid.split("@")[0] if "@" in remote_jid else remote_jid

    logger.info("WhatsApp message from %s: %s", sender, text[:100])

    # Process via agent
    agent = request.app.state.agent
    event = {
        "type": "whatsapp",
        "from": sender,
        "content": text,
        "metadata": {"jid": remote_jid},
    }

    try:
        response_text = await agent.process_event(event)

        # Send reply only if auto-reply is enabled
        settings = request.app.state.settings
        if response_text and settings.feature_whatsapp_auto_reply:
            whatsapp_action = request.app.state.whatsapp_action
            await whatsapp_action.send_message(to=remote_jid, text=response_text)
        elif response_text:
            logger.info("Auto-reply disabled, suppressed response to %s", sender)
    except Exception:
        logger.exception("Failed to process WhatsApp message from %s", sender)

    return {"status": "processed"}
