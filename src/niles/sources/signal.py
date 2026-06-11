"""Signal WebSocket listener for signal-cli-rest-api."""

import asyncio
import json
import logging
from typing import Any
from urllib.parse import urlparse

import structlog
import websockets

from .echo_guard import EchoGuard
from .triggers import is_niles_trigger, strip_trigger

logger = logging.getLogger(__name__)

# Echo-loop guard: signal-cli echoes outgoing messages back as
# syncMessage.sentMessage. Keyed by text prefix (no message IDs available).
_echo_guard = EchoGuard(ttl=10.0)


async def signal_listener(
    app_state,
    shutdown_event: asyncio.Event,
) -> None:
    """Background task: listen to signal-cli WebSocket for incoming messages.

    Reconnects with exponential backoff on disconnect.
    """
    phone = app_state.settings.signal_phone_number
    api_url = app_state.settings.signal_api_url
    # Build WebSocket URL from HTTP URL (wss:// for https://, ws:// for http://)
    parsed = urlparse(api_url)
    ws_scheme = "wss" if parsed.scheme == "https" else "ws"
    ws_url = f"{ws_scheme}://{parsed.netloc}/v1/receive/{phone}?timeout=3600"

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


async def _handle_envelope(app_state: Any, data: dict) -> None:
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
    # Store only — no auto-reply. The agent reads stored messages via
    # get_signal_messages when the user asks. This matches the design
    # decision that Niles only responds when explicitly triggered
    # (self-chat with "Hey Niles" trigger phrase).
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
    if _echo_guard.is_echo(text[:200]):
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
            _echo_guard.record(response[:200])
            await signal_action.send_message(to=own_phone, text=response)
    except Exception:
        logger.exception("Failed to process Signal self-chat")
