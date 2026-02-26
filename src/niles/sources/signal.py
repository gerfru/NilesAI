"""Signal WebSocket listener for signal-cli-rest-api."""

import asyncio
import json
import logging
import time

import structlog
import websockets

from .triggers import is_niles_trigger, strip_trigger

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Echo-loop guard: cache of recently sent message texts.
# signal-cli-rest-api echoes outgoing messages back as syncMessage.sentMessage.
# Unlike Evolution API, there is no unique message ID in the send response,
# so we track the text content (truncated) with a TTL.
# ---------------------------------------------------------------------------
_sent_texts: dict[str, float] = {}  # text_hash → monotonic timestamp
_SENT_TTL = 10.0  # seconds


def _record_sent(text: str) -> None:
    """Record text we just sent (with TTL-based pruning)."""
    now = time.monotonic()
    key = text[:200]
    _sent_texts[key] = now
    expired = [k for k, v in _sent_texts.items() if now - v > _SENT_TTL]
    for k in expired:
        del _sent_texts[k]


def _was_echo(text: str) -> bool:
    """Check if text matches something we recently sent."""
    key = text[:200]
    ts = _sent_texts.get(key)
    if ts is None:
        return False
    return (time.monotonic() - ts) <= _SENT_TTL


async def signal_listener(
    app_state,
    shutdown_event: asyncio.Event,
) -> None:
    """Background task: listen to signal-cli WebSocket for incoming messages.

    Reconnects with exponential backoff on disconnect.
    """
    phone = app_state.settings.signal_phone_number
    api_url = app_state.settings.signal_api_url
    # Build ws:// URL from http:// URL
    ws_host = api_url.replace("http://", "").replace("https://", "").rstrip("/")
    ws_url = f"ws://{ws_host}/v1/receive/{phone}?timeout=3600"

    backoff = 5
    max_backoff = 60

    while not shutdown_event.is_set():
        try:
            async with websockets.connect(ws_url) as ws:
                logger.info("Signal WebSocket connected: %s", ws_url)
                backoff = 5  # reset on success
                async for raw in ws:
                    if shutdown_event.is_set():
                        break
                    try:
                        envelope = json.loads(raw)
                        logger.debug("Signal envelope: %s", raw[:500])
                        await _handle_envelope(app_state, envelope)
                    except Exception:
                        logger.exception("Error handling Signal message")
        except asyncio.CancelledError:
            logger.info("Signal listener cancelled")
            return
        except Exception as exc:
            logger.warning(
                "Signal WebSocket disconnected: %s (reconnect in %ds)",
                exc,
                backoff,
            )
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=backoff)
                return  # shutdown signaled during backoff
            except asyncio.TimeoutError:
                pass
            backoff = min(backoff * 2, max_backoff)


async def _handle_envelope(app_state, data: dict) -> None:
    """Process a single Signal WebSocket envelope."""
    # signal-cli sends exceptions for Note-to-Self messages (linked device bug)
    if "exception" in data:
        logger.debug(
            "Signal envelope exception (ignored): %s",
            data["exception"].get("message", ""),
        )
        return

    envelope = data.get("envelope", {})
    source = envelope.get("source", "")  # sender phone ("+43660...")
    data_msg = envelope.get("dataMessage")
    sync_msg = envelope.get("syncMessage")

    signal_store = app_state.signal_store
    own_phone = app_state.settings.signal_phone_number

    # --- Incoming message from someone else ---
    if data_msg and data_msg.get("message"):
        text = data_msg["message"]
        await signal_store.store(phone=source, text=text, from_me=False)
        logger.info("Signal message from %s stored", source)
        return

    # --- Self-chat (Note to Self) via syncMessage.sentMessage ---
    if not sync_msg:
        return

    sent = sync_msg.get("sentMessage")
    if not sent:
        return
    text = sent.get("message", "")
    if not text:
        return

    # Store outgoing message
    dest = sent.get("destination", own_phone)
    logger.info("Signal self-chat message: dest=%s text=%s", dest, text[:80])
    await signal_store.store(phone=dest, text=text, from_me=True)

    # Echo-loop guard: skip if we just sent this via the agent
    if _was_echo(text):
        return

    # Trigger check — only process self-chat with trigger phrase
    if not is_niles_trigger(text):
        return

    clean_text = strip_trigger(text)
    if not clean_text:
        clean_text = "Hallo!"

    phone_digits = own_phone.lstrip("+")
    chat_id = f"signal-self-{phone_digits}"
    structlog.contextvars.bind_contextvars(chat_id=chat_id, source="signal")

    event = {
        "type": "signal",
        "from": chat_id,
        "content": clean_text,
        "metadata": {"source": own_phone, "self_chat": True},
    }

    try:
        signal_action = app_state.signal_action
        agent = app_state.agent
        response = await agent.process_event(event)
        if response:
            _record_sent(response)
            await signal_action.send_message(to=own_phone, text=response)
    except Exception:
        logger.exception("Failed to process Signal self-chat")
