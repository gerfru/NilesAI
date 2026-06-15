# SPDX-License-Identifier: AGPL-3.0-only
"""Single owner of the outbound-messaging policy + send, for WhatsApp and Signal.

Previously the "resolve → self-check → feature-flag gate → send" invariant was
implemented three times (signal tool, whatsapp tool, confirmation replay), and
the replay path skipped the gate entirely. This component centralises the
**self-check + feature-flag gate + send** so the security-relevant rule
("don't message third parties unless enabled") lives in one place and is
re-applied at send time — including on confirmation replay.

Recipient *resolution* stays channel-specific in the tools (WhatsApp has a
multi-number disambiguation flow Signal does not).
"""

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..config import Settings

logger = logging.getLogger(__name__)

# Shown when sending to others is disabled by the feature flag.
SEND_OTHERS_DISABLED = (
    "Das Senden an andere Personen ist deaktiviert. Du kannst diese Funktion in den Einstellungen aktivieren."
)


class MessageDispatch:
    """Outbound message policy + send for both channels."""

    def __init__(
        self,
        config: "Settings",
        whatsapp,
        signal,
        *,
        get_own_phone_number: Callable[[str], Awaitable[str | None]],
    ):
        self.config = config
        self.whatsapp = whatsapp
        self.signal = signal
        self._get_own_phone_number = get_own_phone_number

    async def _wa_is_self(self, number: str, chat_id: str) -> bool:
        own = await self._get_own_phone_number(chat_id)
        if not own:
            return False
        normalized = number.replace("+", "").replace(" ", "")
        return normalized == own or (len(own) >= 8 and normalized.endswith(own))

    async def policy(self, channel: str, number: str, chat_id: str) -> tuple[bool, bool]:
        """Return (is_self, allowed) for sending *number* on *channel*.

        Own number is always allowed; others only when the channel's
        feature_*_send_others flag is set.
        """
        if channel == "whatsapp":
            is_self = await self._wa_is_self(number, chat_id)
            allowed = is_self or self.config.feature_whatsapp_send_others
        elif channel == "signal":
            is_self = number == self.config.signal_phone_number
            allowed = is_self or self.config.feature_signal_send_others
        else:
            raise ValueError(f"unknown channel: {channel}")
        return is_self, allowed

    async def send_whatsapp(self, *, to: str, text: str, instance: str | None, chat_id: str) -> dict:
        """Re-check the gate, then send. Returns the raw send result or an error dict."""
        _, allowed = await self.policy("whatsapp", to, chat_id)
        if not allowed:
            logger.info("send_whatsapp to others blocked by feature flag (at send)")
            return {"error": SEND_OTHERS_DISABLED}
        return await self.whatsapp.send_message(to=to, text=text, instance=instance)

    async def send_signal(self, *, to: str, text: str, chat_id: str = "") -> dict:
        """Re-check the gate, then send. Returns the raw send result or an error dict."""
        if self.signal is None:
            return {"error": "Signal ist nicht konfiguriert"}
        _, allowed = await self.policy("signal", to, chat_id)
        if not allowed:
            logger.info("send_signal to others blocked by feature flag (at send)")
            return {"error": SEND_OTHERS_DISABLED}
        return await self.signal.send_message(to=to, text=text)
