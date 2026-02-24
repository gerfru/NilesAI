"""WhatsApp webhook handler for Evolution API."""

import hmac
import logging
import time

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook", tags=["webhooks"])

TRIGGER_PHRASES = ("hey niles", "hi niles", "hallo niles", "niles")
# Case-insensitive trigger phrases. Checked against the start of the message.

# ---------------------------------------------------------------------------
# Echo-loop guard: cache of message IDs sent by the agent.
# When the agent sends a self-chat reply, Evolution API echoes the outbound
# message back as a MESSAGES_UPSERT with fromMe=True.  If the reply text
# happens to start with a trigger phrase (e.g. "Niles hier: ..."), the
# webhook would fire again — causing an infinite loop.
# NOTE: This cache is per-process.  With multiple uvicorn workers (--workers N)
# each worker maintains its own _sent_ids, so an echo could slip through if a
# different worker handles it.  Single-worker (the default) is fully safe.
# ---------------------------------------------------------------------------
_sent_ids: dict[str, float] = {}  # msg_id → monotonic timestamp
_SENT_TTL = 10.0  # seconds


def _record_sent(msg_id: str) -> None:
    """Record a message ID we just sent (with TTL-based pruning)."""
    now = time.monotonic()
    _sent_ids[msg_id] = now
    expired = [k for k, v in _sent_ids.items() if now - v > _SENT_TTL]
    for k in expired:
        del _sent_ids[k]


def _was_echo(msg_id: str) -> bool:
    """Check if a message ID is one we recently sent."""
    ts = _sent_ids.get(msg_id)
    if ts is None:
        return False
    return (time.monotonic() - ts) <= _SENT_TTL


def _is_niles_trigger(text: str) -> bool:
    """Check if a message starts with a Niles trigger phrase.

    Requires a word boundary after the phrase to avoid false positives
    like "Nilesh" or "nilesarmy".
    """
    lower = text.strip().lower()
    for phrase in TRIGGER_PHRASES:
        if lower.startswith(phrase):
            rest = lower[len(phrase):]
            if not rest or not rest[0].isalpha():
                return True
    return False


def _strip_trigger(text: str) -> str:
    """Remove the trigger phrase from the beginning of the message.

    Returns the remaining text after the trigger, stripped of leading
    whitespace, commas, and colons.

    Examples:
        "Hey Niles, was steht heute an?" → "was steht heute an?"
        "Hey Niles was steht heute an?"  → "was steht heute an?"
        "Niles: Termin morgen?"          → "Termin morgen?"
        "Hey Niles"                      → ""
    """
    lower = text.strip().lower()
    for phrase in TRIGGER_PHRASES:
        if lower.startswith(phrase):
            rest = lower[len(phrase):]
            if not rest or not rest[0].isalpha():
                return text.strip()[len(phrase):].lstrip(" ,:-").strip()
    return text.strip()


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
    is_from_me = key.get("fromMe", False)
    remote_jid = key.get("remoteJid", "")
    msg_id = key.get("id", "")
    message = data.get("message", {})

    # Skip echoed messages that the agent itself sent (prevents reply loops)
    if is_from_me and msg_id and _was_echo(msg_id):
        return {"status": "ignored", "reason": "echo of own reply"}

    # Extract text from different message types
    text = (
        message.get("conversation")
        or message.get("extendedTextMessage", {}).get("text")
    )

    if not text:
        return {"status": "ignored", "reason": "no text content"}

    # --- Self-Chat Trigger Logic ---
    if is_from_me:
        if not _is_niles_trigger(text):
            return {"status": "ignored", "reason": "own message without trigger"}

        # Trigger recognised — strip trigger phrase
        clean_text = _strip_trigger(text)
        if not clean_text:
            # Just "Hey Niles" without content → greeting
            clean_text = "Hallo!"

        sender = remote_jid.split("@")[0] if "@" in remote_jid else remote_jid
        logger.info("Self-chat trigger from %s: %s", sender, clean_text[:100])

        # Self-Chat uses its own chat_id for separate history
        chat_id = f"wa-self-{sender}"

        # Resolve per-user instance (for multi-user setups)
        instance_name = payload.get("instance")
        instance_for_reply = instance_name

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
                # Record sent message ID so the echoed webhook is skipped
                sent_id = result.get("key", {}).get("id") if isinstance(result, dict) else None
                if sent_id:
                    _record_sent(sent_id)
                    logger.info("Self-chat reply sent to %s", remote_jid)
                else:
                    logger.warning(
                        "No message ID in send_message response — echo guard not armed"
                    )
        except Exception:
            logger.exception("Failed to process self-chat message")

        return {"status": "processed", "trigger": "self-chat"}

    # --- Incoming messages from other people ---
    # Store in whatsapp_inbox (no LLM call, no auto-reply, no Web-Chat).
    sender = remote_jid.split("@")[0] if "@" in remote_jid else remote_jid

    # Resolve per-user instance
    instance_name = payload.get("instance")
    wa_store = request.app.state.wa_store
    session = await wa_store.get_by_instance(instance_name) if instance_name else None
    user_id = session["user_id"] if session else None

    # Resolve contact name from CardDAV contacts
    contacts = request.app.state.contacts
    contact_name = await contacts.find_by_phone(sender)

    # Store in whatsapp_inbox
    inbox = request.app.state.whatsapp_inbox
    await inbox.store_message(
        wa_message_id=msg_id,
        sender_phone=sender,
        contact_name=contact_name,
        instance_name=instance_name,
        user_id=user_id,
        content=text,
    )

    logger.info(
        "WhatsApp message from %s (%s) stored in inbox (user_id=%s)",
        sender, contact_name or "unknown", user_id,
    )

    return {"status": "stored", "sender": sender}
