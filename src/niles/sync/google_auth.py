"""Google Calendar OAuth – httpx Auth class with automatic token refresh."""

import logging
import time

import httpx

logger = logging.getLogger(__name__)

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


class GoogleCalendarAuth(httpx.Auth):
    """Bearer token auth with automatic refresh for Google Calendar.

    Holds an in-memory cache of the access token.  Refreshes automatically
    when the token expires.  Each sync operation creates a new instance,
    so the cache lives for the duration of one sync run.
    """

    def __init__(
        self,
        refresh_token: str,
        client_id: str,
        client_secret: str,
        client: httpx.AsyncClient | None = None,
    ):
        self._refresh_token = refresh_token
        self._client_id = client_id
        self._client_secret = client_secret
        self._client = client or httpx.AsyncClient(timeout=30)
        self._access_token: str | None = None
        self._expires_at: float = 0  # monotonic time

    def sync_auth_flow(self, request):
        raise NotImplementedError("Use async_auth_flow with AsyncClient")

    async def async_auth_flow(self, request):
        if not self._access_token or time.monotonic() >= self._expires_at:
            await self._refresh()
        request.headers["Authorization"] = f"Bearer {self._access_token}"
        yield request

    async def _refresh(self) -> None:
        """Exchange refresh_token for a fresh access_token."""
        response = await self._client.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "refresh_token": self._refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=30,
        )
        response.raise_for_status()

        data = response.json()
        self._access_token = data["access_token"]
        # Expire 60 seconds early to avoid edge cases
        expires_in = data.get("expires_in", 3600)
        self._expires_at = time.monotonic() + expires_in - 60
        logger.debug("Google Calendar token refreshed (expires_in=%d)", expires_in)
