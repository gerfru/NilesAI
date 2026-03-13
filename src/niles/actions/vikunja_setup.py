"""Vikunja credential management and connection testing."""

import ipaddress
import logging
from urllib.parse import urlparse

import httpx

from ..vikunja_store import VikunjaCredentialStore

logger = logging.getLogger(__name__)


class VikunjaSetupAction:
    """Manage per-user Vikunja API credentials (connect/disconnect/status)."""

    def __init__(
        self,
        vikunja_store: VikunjaCredentialStore,
        *,
        http_client: httpx.AsyncClient,
        default_api_url: str = "",
    ):
        self.vikunja_store = vikunja_store
        self.http_client = http_client
        self.default_api_url = default_api_url

    @staticmethod
    def validate_url(url: str) -> None:
        """SSRF protection: reject non-HTTP schemes and private IP literals.

        Raises ValueError for invalid URLs.
        Hostnames (including 'localhost') are intentionally allowed for
        Docker-internal service names in self-hosted setups.
        """
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError("scheme")
        host = parsed.hostname or ""
        if not host:
            raise ValueError("host")
        try:
            addr = ipaddress.ip_address(host)
            if addr.is_private or addr.is_loopback or addr.is_link_local:
                raise ValueError("private IP")
        except ValueError as ve:
            if str(ve) == "private IP":
                raise

    async def test_connection(self, api_url: str, api_token: str) -> int:
        """Test Vikunja API connection.

        Returns project count. Raises httpx.HTTPError on failure.
        """
        resp = await self.http_client.get(
            f"{api_url.rstrip('/')}/projects",
            headers={"Authorization": f"Bearer {api_token}"},
            timeout=10,
        )
        resp.raise_for_status()
        return len(resp.json())

    async def save_credentials(
        self, user_id: int, api_token: str, api_url: str = ""
    ) -> int:
        """Validate URL, test connection, persist credentials.

        Returns project count.
        Raises ValueError for invalid/missing URL, ConnectionError for test failure.
        """
        effective_url = api_url.strip() or self.default_api_url
        if not effective_url:
            raise ValueError(
                "Keine API-URL. Bitte URL angeben oder global konfigurieren."
            )

        self.validate_url(effective_url)

        try:
            count = await self.test_connection(effective_url, api_token)
        except Exception as exc:
            raise ConnectionError(
                "Verbindung fehlgeschlagen: Token oder URL ungueltig."
            ) from exc

        await self.vikunja_store.upsert_credentials(
            user_id=user_id,
            api_token=api_token,
            api_url=api_url.strip(),
        )
        return count

    async def delete_credentials(self, user_id: int) -> None:
        """Remove Vikunja credentials for a user."""
        await self.vikunja_store.delete_credentials(user_id)

    async def get_status(self, user_id: int) -> dict:
        """Return connection status dict for template context.

        Returns dict with keys: vikunja_connected, vikunja_project_count, vikunja_error.
        """
        creds = await self.vikunja_store.get_credentials(user_id)
        result: dict = {
            "vikunja_connected": False,
            "vikunja_project_count": 0,
            "vikunja_error": None,
        }
        if not creds:
            return result

        api_url = creds["api_url"] or self.default_api_url
        if not api_url:
            result["vikunja_connected"] = True
            result["vikunja_error"] = "Keine Vikunja API-URL konfiguriert."
            return result

        try:
            count = await self.test_connection(api_url, creds["api_token"])
            result["vikunja_connected"] = True
            result["vikunja_project_count"] = count
        except Exception:
            result["vikunja_connected"] = True
            result["vikunja_error"] = "Verbindung zum Vikunja-Server fehlgeschlagen."

        return result
