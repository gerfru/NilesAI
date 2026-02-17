"""WhatsApp message sending via Evolution API."""

import logging

import httpx

from ..config import Settings

logger = logging.getLogger(__name__)


class WhatsAppAction:
    """Sends messages via Evolution API."""

    def __init__(self, config: Settings):
        self.base_url = config.evolution_api_url
        self.api_key = config.evolution_api_key
        self.instance = config.evolution_instance

    async def send_message(self, to: str, text: str) -> dict:
        """
        Send a WhatsApp message.

        Args:
            to: Phone number (e.g. "4366012345678") or JID
               (e.g. "4366012345678@s.whatsapp.net" or "120363xxx@g.us")
            text: Message text
        """
        # Ensure JID format if plain number
        if "@" not in to:
            to = f"{to}@s.whatsapp.net"

        url = f"{self.base_url}/message/sendText/{self.instance}"
        headers = {"apikey": self.api_key}
        payload = {"number": to, "text": text}

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    url, json=payload, headers=headers, timeout=30
                )
                response.raise_for_status()
                result = response.json()
                logger.info("Message sent to %s", to)
                return result
            except httpx.HTTPError as e:
                logger.error("Failed to send message to %s: %s", to, e)
                return {"error": str(e)}
