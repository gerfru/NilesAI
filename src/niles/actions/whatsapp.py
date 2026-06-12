"""WhatsApp message sending and instance management via Evolution API."""

import logging
import time
from datetime import datetime, timezone

import httpx

from ..actions.contacts import normalize_phone
from ..config import Settings
from ..errors import sanitize_error

logger = logging.getLogger(__name__)

# Media type → placeholder text for messages without caption
_MEDIA_PLACEHOLDERS = {
    "imageMessage": "[Bild]",
    "videoMessage": "[Video]",
    "audioMessage": "[Sprachnachricht]",
    "pttMessage": "[Sprachnachricht]",
    "stickerMessage": "[Sticker]",
    "documentMessage": "[Dokument]",
    "contactMessage": "[Kontakt]",
    "locationMessage": "[Standort]",
}


def _filter_and_parse_messages(records: list, cutoff: int) -> list[dict]:
    """Filter records by cutoff timestamp, extract text, return sorted list."""
    messages = []
    for rec in records:
        try:
            ts = int(rec.get("messageTimestamp", 0))
        except ValueError, TypeError:
            continue
        if ts < cutoff:
            continue
        msg = rec.get("message", {})
        text = (
            msg.get("conversation")
            or msg.get("extendedTextMessage", {}).get("text")
            or msg.get("imageMessage", {}).get("caption")
            or msg.get("videoMessage", {}).get("caption")
            or msg.get("documentMessage", {}).get("caption")
        )
        if not text:
            text = next((v for k, v in _MEDIA_PLACEHOLDERS.items() if k in msg), None)
            if not text:
                continue
        messages.append(
            {
                "from_me": rec.get("key", {}).get("fromMe", False),
                "text": text,
                "timestamp": ts,
                "push_name": rec.get("pushName", ""),
            }
        )
    messages.sort(key=lambda m: m["timestamp"])
    return messages


class WhatsAppAction:
    """Sends messages and manages instances via Evolution API."""

    def __init__(self, config: Settings, client: httpx.AsyncClient | None = None):
        self.base_url = config.evolution_api_url
        self.instance = config.evolution_instance
        self._phone_country_code = config.phone_country_code
        self._client = client or httpx.AsyncClient(headers={"apikey": config.evolution_api_key}, timeout=30)

    async def send_message(
        self,
        to: str,
        text: str,
        instance: str | None = None,
    ) -> dict:
        """
        Send a WhatsApp message.

        Args:
            to: Phone number (e.g. "436601234567") or JID
               (e.g. "436601234567@s.whatsapp.net" or "120363xxx@g.us")
            text: Message text
            instance: Evolution API instance name (defaults to global instance)
        """
        # Normalize and ensure JID format if plain number
        if "@" not in to:
            to = f"{normalize_phone(to, self._phone_country_code)}@s.whatsapp.net"

        inst = instance or self.instance
        url = f"{self.base_url}/message/sendText/{inst}"
        payload = {"number": to, "text": text}

        try:
            response = await self._client.post(url, json=payload, timeout=30)
            response.raise_for_status()
            result = response.json()
            logger.info("Message sent to %s via %s", to, inst)
            return result
        except (httpx.HTTPError, ValueError) as e:
            logger.error("Failed to send message to %s: %s", to, e)
            return {"error": sanitize_error(e)}

    _MAX_AGE_DAYS = 30

    async def fetch_messages(
        self,
        remote_jid: str,
        instance: str | None = None,
    ) -> list[dict]:
        """Fetch message history from Evolution API (last 30 days).

        Args:
            remote_jid: WhatsApp JID (e.g. "436601234567@s.whatsapp.net")
            instance: Evolution API instance (defaults to global)

        Returns:
            List of message dicts with keys: from_me, text, timestamp, push_name.
            Sorted by timestamp ascending (oldest first). Returns all messages
            within the 30-day window.
        """
        inst = instance or self.instance
        url = f"{self.base_url}/chat/findMessages/{inst}"
        # Evolution API expects ISO date strings for gte/lte, converts to unix internally
        now = datetime.now(timezone.utc)
        cutoff_dt = datetime.fromtimestamp(
            time.time() - (self._MAX_AGE_DAYS * 86400),
            tz=timezone.utc,
        )
        # Both remoteJid AND remoteJidAlt must be set.  Evolution API's
        # Baileys override (PR #2249) combines them with OR so the query
        # matches old-style phone JIDs *and* new LID-addressed messages
        # where the phone number lives in key.remoteJidAlt.
        payload = {
            "where": {
                "key": {
                    "remoteJid": remote_jid,
                    "remoteJidAlt": remote_jid,
                },
                "messageTimestamp": {
                    "gte": cutoff_dt.isoformat(),
                    "lte": now.isoformat(),
                },
            },
        }
        try:
            resp = await self._client.post(
                url,
                json=payload,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            records = data.get("messages", {}).get("records", [])
            if logger.isEnabledFor(logging.DEBUG):
                msgs = data.get("messages")
                keys_info = list(msgs.keys()) if isinstance(msgs, dict) else type(msgs)
                logger.debug(
                    "findMessages %s: %d records (keys: %s)",
                    remote_jid,
                    len(records),
                    keys_info,
                )
        except (httpx.HTTPError, ValueError) as e:
            logger.error("Failed to fetch messages from %s: %s", inst, e)
            return []

        cutoff = int(time.time()) - (self._MAX_AGE_DAYS * 86400)
        messages = _filter_and_parse_messages(records, cutoff)
        return messages

    async def create_instance(
        self,
        instance_name: str,
        webhook_url: str,
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

        try:
            response = await self._client.post(url, json=payload, timeout=30)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as e:
            logger.error("Failed to create instance %s: %s", instance_name, e)
            return {"error": sanitize_error(e)}

    async def get_connection_state(self, instance_name: str) -> str:
        """
        Check instance connection state.

        Returns 'open', 'close', or 'connecting'.
        """
        url = f"{self.base_url}/instance/connectionState/{instance_name}"

        try:
            response = await self._client.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            return data.get("instance", {}).get("state", "close")
        except (httpx.HTTPError, ValueError) as e:
            logger.error(
                "Failed to get connection state for %s: %s",
                instance_name,
                e,
            )
            return "close"

    async def get_qr_code(self, instance_name: str) -> dict:
        """
        Get QR code / pairing code for an instance.

        Returns dict with 'pairingCode', 'code', 'base64' keys, or 'error'.
        """
        url = f"{self.base_url}/instance/connect/{instance_name}"

        try:
            response = await self._client.get(url, timeout=10)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as e:
            logger.error(
                "Failed to get QR code for %s: %s",
                instance_name,
                e,
            )
            return {"error": sanitize_error(e)}

    async def get_owner_jid(self, instance_name: str) -> str | None:
        """Get the ownerJid (phone@s.whatsapp.net) for a connected instance."""
        url = f"{self.base_url}/instance/fetchInstances"
        try:
            response = await self._client.get(
                url,
                params={"instanceName": instance_name},
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            if data and isinstance(data, list):
                return data[0].get("ownerJid")
        except (httpx.HTTPError, IndexError, KeyError, ValueError) as e:
            logger.error(
                "Failed to get ownerJid for %s: %s",
                instance_name,
                e,
            )
        return None

    async def logout_instance(self, instance_name: str) -> dict:
        """Logout a WhatsApp instance (unlink device)."""
        url = f"{self.base_url}/instance/logout/{instance_name}"

        try:
            response = await self._client.delete(url, timeout=15)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as e:
            logger.error(
                "Failed to logout instance %s: %s",
                instance_name,
                e,
            )
            return {"error": sanitize_error(e)}

    async def delete_instance(self, instance_name: str) -> dict:
        """Delete an Evolution API instance."""
        url = f"{self.base_url}/instance/delete/{instance_name}"

        try:
            response = await self._client.delete(url, timeout=15)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as e:
            logger.error(
                "Failed to delete instance %s: %s",
                instance_name,
                e,
            )
            return {"error": sanitize_error(e)}
