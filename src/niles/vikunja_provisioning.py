# SPDX-License-Identifier: AGPL-3.0-only
"""Auto-provision Vikunja accounts for Niles users.

On first login, registers a Vikunja user, obtains a JWT,
creates a persistent API token, and stores it in vikunja_credentials.
"""

import asyncio
import base64
import hashlib
import hmac
import logging
from datetime import datetime, timedelta, timezone

import httpx

from .vikunja_store import VikunjaCredentialStore

logger = logging.getLogger(__name__)

_TIMEOUT = 10
_TOKEN_TITLE = "Niles Auto-Provisioned"  # noqa: S105
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
        self._in_flight: set[int] = set()
        self._lock = asyncio.Lock()

    async def ensure_provisioned(self, user_id: int, email: str) -> bool:
        """Ensure the user has a Vikunja account and API token.

        Returns True if credentials exist (new or existing).
        Returns False if provisioning failed (Vikunja unreachable, etc.).
        Never raises — all errors are logged and swallowed.
        """
        creds = await self.store.get_credentials(user_id)
        if creds and creds["api_token"]:
            return True

        async with self._lock:
            if user_id in self._in_flight:
                return False
            self._in_flight.add(user_id)

        try:
            return await self._provision(user_id, email)
        finally:
            async with self._lock:
                self._in_flight.discard(user_id)

    async def _provision(self, user_id: int, email: str) -> bool:
        """Run the full provisioning flow with a shared HTTP client."""
        logger.info("Provisioning Vikunja account for user_id=%d (%s)", user_id, email)

        password = self._derive_password(user_id, email)
        username = self._derive_username(user_id, email)

        async with httpx.AsyncClient(base_url=self.api_url, timeout=_TIMEOUT) as client:
            # Step 1: Register (ignore 400 = user exists)
            await self._register(client, username, email, password)

            # Step 2: Login to get JWT
            jwt = await self._login(client, username, password)
            if not jwt:
                logger.warning("Vikunja login failed for user_id=%d", user_id)
                return False

            # Step 3: Create persistent API token
            api_token = await self._create_api_token(client, jwt)
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

    async def _register(self, client: httpx.AsyncClient, username: str, email: str, password: str) -> None:
        """POST /register. Logs result; 400 (user exists) is expected and tolerated."""
        try:
            resp = await client.post(
                "/register",
                json={
                    "username": username,
                    "email": email,
                    "password": password,
                },
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
        except httpx.HTTPError, OSError:
            logger.exception("Vikunja register failed for %s", username)

    async def _login(self, client: httpx.AsyncClient, username: str, password: str) -> str | None:
        """POST /login → JWT token string, or None on failure."""
        try:
            resp = await client.post(
                "/login",
                json={
                    "username": username,
                    "password": password,
                    "long_token": True,
                },
            )
            if resp.status_code == 200:
                return resp.json().get("token")
            logger.warning(
                "Vikunja login status %d: %s",
                resp.status_code,
                resp.text[:200],
            )
            return None
        except httpx.HTTPError, OSError:
            logger.exception("Vikunja login failed for %s", username)
            return None

    async def sync_password(self, user_id: int, email: str, plaintext_password: str) -> bool:
        """Sync the user's Niles password to their Vikunja account.

        - No credentials yet → provision with HMAC, then change to plaintext
        - Credentials exist, already synced → no-op
        - Credentials exist, not synced → HMAC login, change to plaintext

        Returns True on success. Never raises.
        """
        async with self._lock:
            if user_id in self._in_flight:
                return False
            self._in_flight.add(user_id)

        try:
            return await self._sync_password(user_id, email, plaintext_password)
        except Exception:
            logger.exception("Vikunja password sync failed for user_id=%d", user_id)
            return False
        finally:
            async with self._lock:
                self._in_flight.discard(user_id)

    async def _sync_password(self, user_id: int, email: str, plaintext_password: str) -> bool:
        """Internal password sync logic."""
        creds = await self.store.get_credentials(user_id)
        username = self._derive_username(user_id, email)
        hmac_password = self._derive_password(user_id, email)

        if not creds or not creds.get("api_token"):
            # Not yet provisioned: register with HMAC, get token, then change pw
            provisioned = await self._provision(user_id, email)
            if not provisioned:
                return False
            # Now change from HMAC to user's password
            async with httpx.AsyncClient(base_url=self.api_url, timeout=_TIMEOUT) as client:
                jwt = await self._login(client, username, hmac_password)
                if jwt and await self._change_password(client, jwt, hmac_password, plaintext_password):
                    await self.store.set_password_synced(user_id, True)
                    return True
            # Provisioning worked but password change failed — still usable
            return False

        if creds.get("password_synced"):
            # Already synced, nothing to do
            return True

        # Credentials exist but password not synced: change HMAC → plaintext
        async with httpx.AsyncClient(base_url=self.api_url, timeout=_TIMEOUT) as client:
            jwt = await self._login(client, username, hmac_password)
            if not jwt:
                # HMAC login failed — maybe already synced from a previous attempt?
                jwt = await self._login(client, username, plaintext_password)
                if jwt:
                    await self.store.set_password_synced(user_id, True)
                    return True
                logger.warning("Vikunja password sync: cannot login for user_id=%d", user_id)
                return False

            if await self._change_password(client, jwt, hmac_password, plaintext_password):
                await self.store.set_password_synced(user_id, True)
                return True

        return False

    async def _change_password(
        self,
        client: httpx.AsyncClient,
        jwt: str,
        old_password: str,
        new_password: str,
    ) -> bool:
        """POST /user/password to change the Vikunja password."""
        try:
            resp = await client.post(
                "/user/password",
                headers={"Authorization": f"Bearer {jwt}"},
                json={
                    "old_password": old_password,
                    "new_password": new_password,
                },
            )
            if resp.status_code == 200:
                logger.info("Vikunja password synced successfully")
                return True
            logger.warning(  # nosemgrep: python-logger-credential-disclosure
                "Vikunja password change status %d: %s",
                resp.status_code,
                resp.text[:200],
            )
            return False
        except httpx.HTTPError, OSError:
            logger.exception("Vikunja password change request failed")
            return False

    async def _create_api_token(self, client: httpx.AsyncClient, jwt: str) -> str | None:
        """PUT /tokens with JWT auth → persistent tk_... token, or None."""
        expires = (datetime.now(tz=timezone.utc) + timedelta(days=3650)).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            resp = await client.put(
                "/tokens",
                headers={"Authorization": f"Bearer {jwt}"},
                json={
                    "title": _TOKEN_TITLE,
                    "permissions": _TOKEN_PERMISSIONS,
                    "expires_at": expires,
                },
            )
            if resp.status_code in (200, 201):
                token = resp.json().get("token")
                if token:
                    return token
                logger.warning("Vikunja token response missing 'token' field")
                return None
            logger.warning(  # nosemgrep: python-logger-credential-disclosure
                "Vikunja create token status %d: %s",
                resp.status_code,
                resp.text[:200],
            )
            return None
        except httpx.HTTPError, OSError:
            logger.exception("Vikunja create token failed")
            return None
