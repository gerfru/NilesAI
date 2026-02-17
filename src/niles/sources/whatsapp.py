"""WhatsApp webhook handler for Evolution API."""

import logging

from fastapi import APIRouter, Request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook", tags=["webhooks"])


@router.post("/whatsapp")
async def whatsapp_webhook(request: Request):
    """
    Evolution API webhook handler.

    Receives MESSAGES_UPSERT events and forwards them to the agent.
    Always returns 200 to prevent retry-spam from Evolution.
    """
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

        # Send reply
        if response_text:
            whatsapp_action = request.app.state.whatsapp_action
            await whatsapp_action.send_message(to=remote_jid, text=response_text)
    except Exception:
        logger.exception("Failed to process WhatsApp message from %s", sender)

    return {"status": "processed"}
