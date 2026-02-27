"""Auto-provision Vikunja accounts for Niles users.

On first login, registers a Vikunja user, obtains a JWT,
creates a persistent API token, and stores it in vikunja_credentials.
"""

import base64
import hashlib
import hmac
import logging
from datetime import datetime, timedelta, timezone

import httpx

from .vikunja_store import VikunjaCredentialStore

logger = logging.getLogger(__name__)

_TIMEOUT = 10
_TOKEN_TITLE = "Niles Auto-Provisioned"
_TOKEN_PERMISSIONS = {
    "tasks": ["read_all", "create", "update"],
    "projects": ["read_all"],
}


class VikunjaProvisioner:
    """Create Vikunja accounts and API tokens for Niles users."""

    def __init__(
        self,
        api_url: str,
        session_secret: str,
        store: VikunjaCredentialStore,
    ):
        self.api_url = api_url.rstrip("/")
        self._secret = session_secret.encode()
        self.store = store

    async def ensure_provisioned(self, user_id: int, email: str) -> bool:
        """Ensure the user has a Vikunja account and API token.

        Returns True if credentials exist (new or existing).
        Returns False if provisioning failed (Vikunja unreachable, etc.).
        Never raises — all errors are logged and swallowed.
        """
        creds = await self.store.get_credentials(user_id)
        if creds and creds["api_token"]:
            return True

        logger.info("Provisioning Vikunja account for user_id=%d (%s)", user_id, email)

        password = self._derive_password(user_id, email)
        username = self._derive_username(user_id, email)

        # Step 1: Register (ignore 400 = user exists)
        await self._register(username, email, password)

        # Step 2: Login to get JWT
        jwt = await self._login(username, password)
        if not jwt:
            logger.warning("Vikunja login failed for user_id=%d", user_id)
            return False

        # Step 3: Create persistent API token
        api_token = await self._create_api_token(jwt)
        if not api_token:
            logger.warning("Vikunja token creation failed for user_id=%d", user_id)
            return False

        # Step 4: Store in DB
        await self.store.upsert_credentials(user_id, api_token, self.api_url)
        logger.info("Vikunja user provisioned for user_id=%d", user_id)
        return True

    def _derive_password(self, user_id: int, email: str) -> str:
        """Deterministic password via HMAC-SHA256. Never stored."""
        msg = f"vikunja:{user_id}:{email}".encode()
        digest = hmac.new(self._secret, msg, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(digest).decode()[:24]

    @staticmethod
    def _derive_username(user_id: int, email: str) -> str:
        """Vikunja username: email prefix + _user_id for uniqueness."""
        prefix = email.split("@")[0].replace(".", "").replace("+", "")[:20]
        return f"{prefix}_{user_id}"

    async def _register(self, username: str, email: str, password: str) -> None:
        """POST /register. Logs result; 400 (user exists) is expected and tolerated."""
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{self.api_url}/register",
                    json={
                        "username": username,
                        "email": email,
                        "password": password,
                    },
                    timeout=_TIMEOUT,
                )
                if resp.status_code == 200:
                    logger.info("Vikunja user registered: %s", username)
                elif resp.status_code == 400:
                    logger.debug("Vikunja user already exists: %s", username)
                else:
                    logger.warning(
                        "Vikunja register unexpected status %d: %s",
                        resp.status_code,
                        resp.text[:200],
                    )
        except Exception:
            logger.exception("Vikunja register failed for %s", username)

    async def _login(self, username: str, password: str) -> str | None:
        """POST /login → JWT token string, or None on failure."""
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{self.api_url}/login",
                    json={
                        "username": username,
                        "password": password,
                        "long_token": True,
                    },
                    timeout=_TIMEOUT,
                )
                if resp.status_code == 200:
                    return resp.json().get("token")
                logger.warning(
                    "Vikunja login status %d: %s",
                    resp.status_code,
                    resp.text[:200],
                )
                return None
        except Exception:
            logger.exception("Vikunja login failed for %s", username)
            return None

    async def _create_api_token(self, jwt: str) -> str | None:
        """PUT /tokens with JWT auth → persistent tk_... token, or None."""
        expires = (datetime.now(tz=timezone.utc) + timedelta(days=3650)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.put(
                    f"{self.api_url}/tokens",
                    headers={"Authorization": f"Bearer {jwt}"},
                    json={
                        "title": _TOKEN_TITLE,
                        "permissions": _TOKEN_PERMISSIONS,
                        "expires_at": expires,
                    },
                    timeout=_TIMEOUT,
                )
                if resp.status_code == 200:
                    token = resp.json().get("token")
                    if token:
                        return token
                    logger.warning("Vikunja token response missing 'token' field")
                    return None
                logger.warning(
                    "Vikunja create token status %d: %s",
                    resp.status_code,
                    resp.text[:200],
                )
                return None
        except Exception:
            logger.exception("Vikunja create token failed")
            return None
