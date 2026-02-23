"""WhatsApp message sending and instance management via Evolution API."""

import logging

import httpx

from ..actions.contacts import normalize_phone
from ..config import Settings

logger = logging.getLogger(__name__)


class WhatsAppAction:
    """Sends messages and manages instances via Evolution API."""

    def __init__(self, config: Settings):
        self.base_url = config.evolution_api_url
        self.api_key = config.evolution_api_key
        self.instance = config.evolution_instance

    def _headers(self) -> dict:
        return {"apikey": self.api_key}

    async def send_message(
        self, to: str, text: str, instance: str | None = None,
    ) -> dict:
        """
        Send a WhatsApp message.

        Args:
            to: Phone number (e.g. "4366012345678") or JID
               (e.g. "4366012345678@s.whatsapp.net" or "120363xxx@g.us")
            text: Message text
            instance: Evolution API instance name (defaults to global instance)
        """
        # Normalize and ensure JID format if plain number
        if "@" not in to:
            to = f"{normalize_phone(to)}@s.whatsapp.net"

        inst = instance or self.instance
        url = f"{self.base_url}/message/sendText/{inst}"
        payload = {"number": to, "text": text}

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    url, json=payload, headers=self._headers(), timeout=30
                )
                response.raise_for_status()
                result = response.json()
                logger.info("Message sent to %s via %s", to, inst)
                return result
            except httpx.HTTPError as e:
                logger.error("Failed to send message to %s: %s", to, e)
                return {"error": str(e)}

    async def create_instance(
        self, instance_name: str, webhook_url: str,
    ) -> dict:
        """
        Create a new Evolution API instance with QR code.

        Returns dict with 'qrcode' key containing base64 PNG, or 'error'.
        """
        url = f"{self.base_url}/instance/create"
        payload = {
            "instanceName": instance_name,
            "integration": "WHATSAPP-BAILEYS",
            "qrcode": True,
            "webhook": {
                "url": webhook_url,
                "events": [
                    "MESSAGES_UPSERT",
                    "CONNECTION_UPDATE",
                    "QRCODE_UPDATED",
                ],
                "webhookByEvents": False,
                "webhookBase64": False,
            },
        }

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    url, json=payload, headers=self._headers(), timeout=30
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPError as e:
                logger.error("Failed to create instance %s: %s", instance_name, e)
                return {"error": str(e)}

    async def get_connection_state(self, instance_name: str) -> str:
        """
        Check instance connection state.

        Returns 'open', 'close', or 'connecting'.
        """
        url = f"{self.base_url}/instance/connectionState/{instance_name}"

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    url, headers=self._headers(), timeout=10
                )
                response.raise_for_status()
                data = response.json()
                return data.get("instance", {}).get("state", "close")
            except httpx.HTTPError as e:
                logger.error(
                    "Failed to get connection state for %s: %s",
                    instance_name, e,
                )
                return "close"

    async def get_qr_code(self, instance_name: str) -> dict:
        """
        Get QR code / pairing code for an instance.

        Returns dict with 'pairingCode', 'code', 'base64' keys, or 'error'.
        """
        url = f"{self.base_url}/instance/connect/{instance_name}"

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    url, headers=self._headers(), timeout=10
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPError as e:
                logger.error(
                    "Failed to get QR code for %s: %s", instance_name, e,
                )
                return {"error": str(e)}

    async def get_owner_jid(self, instance_name: str) -> str | None:
        """Get the ownerJid (phone@s.whatsapp.net) for a connected instance."""
        url = f"{self.base_url}/instance/fetchInstances"
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    url,
                    headers=self._headers(),
                    params={"instanceName": instance_name},
                    timeout=10,
                )
                response.raise_for_status()
                data = response.json()
                if data and isinstance(data, list):
                    return data[0].get("ownerJid")
            except (httpx.HTTPError, IndexError, KeyError, ValueError) as e:
                logger.error(
                    "Failed to get ownerJid for %s: %s", instance_name, e,
                )
        return None

    async def logout_instance(self, instance_name: str) -> dict:
        """Logout a WhatsApp instance (unlink device)."""
        url = f"{self.base_url}/instance/logout/{instance_name}"

        async with httpx.AsyncClient() as client:
            try:
                response = await client.delete(
                    url, headers=self._headers(), timeout=15
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPError as e:
                logger.error(
                    "Failed to logout instance %s: %s", instance_name, e,
                )
                return {"error": str(e)}

    async def delete_instance(self, instance_name: str) -> dict:
        """Delete an Evolution API instance."""
        url = f"{self.base_url}/instance/delete/{instance_name}"

        async with httpx.AsyncClient() as client:
            try:
                response = await client.delete(
                    url, headers=self._headers(), timeout=15
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPError as e:
                logger.error(
                    "Failed to delete instance %s: %s", instance_name, e,
                )
                return {"error": str(e)}
