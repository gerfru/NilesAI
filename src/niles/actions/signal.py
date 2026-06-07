"""Signal message sending and status via signal-cli-rest-api."""

import logging

import httpx

from ..config import Settings

logger = logging.getLogger(__name__)


class SignalAction:
    """Sends messages and checks status via signal-cli-rest-api."""

    def __init__(self, config: Settings):
        self.api_url = config.signal_api_url.rstrip("/")
        self.phone = config.signal_phone_number
        self._client = httpx.AsyncClient()

    async def close(self) -> None:
        """Close the shared HTTP client."""
        await self._client.aclose()

    async def send_message(self, to: str, text: str) -> dict:
        """Send a Signal message.

        Args:
            to: Phone number with + prefix (e.g. "+4366012345678")
            text: Message text
        """
        url = f"{self.api_url}/v2/send"
        payload = {
            "message": text,
            "number": self.phone,
            "recipients": [to],
        }
        try:
            response = await self._client.post(url, json=payload, timeout=30)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as e:
            logger.error("Failed to send Signal message to %s: %s", to, e)
            return {"error": str(e)}

    async def get_status(self) -> dict:
        """Check signal-cli registration status via GET /v1/about."""
        url = f"{self.api_url}/v1/about"
        try:
            response = await self._client.get(url, timeout=10)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as e:
            logger.error("Failed to get Signal status: %s", e)
            return {"error": str(e)}

    async def get_accounts(self) -> list[str]:
        """List registered/linked Signal account phone numbers.

        Returns e.g. ["+4366012345678"] or [] if none linked.
        """
        url = f"{self.api_url}/v1/accounts"
        try:
            response = await self._client.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            if isinstance(data, list):
                return data
            return []
        except (httpx.HTTPError, ValueError) as e:
            logger.error("Failed to get Signal accounts: %s", e)
            return []

    async def unlink(self, phone: str = "") -> bool:
        """Unlink this device from Signal.

        Calls DELETE /v1/accounts/{number} on signal-cli-rest-api.
        Returns True on success (including 404, which is expected for
        linked/secondary devices where the endpoint may not apply).
        """
        number = phone or self.phone
        if not number:
            logger.warning("Cannot unlink Signal: no phone number")
            return False
        url = f"{self.api_url}/v1/accounts/{number}"
        try:
            response = await self._client.delete(url, timeout=30)
            if response.status_code == 404:
                logger.info(
                    "Signal account %s: DELETE returned 404 (normal for linked devices)",
                    number,
                )
                return True
            response.raise_for_status()
            logger.info("Signal account %s unlinked", number)
            return True
        except (httpx.HTTPError, ValueError) as e:
            logger.error("Failed to unlink Signal account %s: %s", number, e)
            return False

    async def get_qr_link(self, device_name: str = "niles") -> bytes | None:
        """Get QR code PNG for linking as a new device.

        Returns raw PNG bytes, or None on error.
        """
        url = f"{self.api_url}/v1/qrcodelink"
        params = {"device_name": device_name}
        try:
            response = await self._client.get(url, params=params, timeout=30)
            response.raise_for_status()
            if "image/png" in response.headers.get("content-type", ""):
                return response.content
            return None
        except (httpx.HTTPError, ValueError) as e:
            logger.error("Failed to get Signal QR code: %s", e)
            return None
