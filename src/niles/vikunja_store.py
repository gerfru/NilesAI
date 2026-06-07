"""Per-user Vikunja credential management backed by PostgreSQL."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import asyncpg

if TYPE_CHECKING:
    from .crypto import FieldEncryptor

logger = logging.getLogger(__name__)


class VikunjaCredentialStore:
    """Manage per-user Vikunja API credentials."""

    def __init__(self, pool: asyncpg.Pool, *, encryptor: FieldEncryptor | None = None):
        self.pool = pool
        self._enc = encryptor

    async def get_credentials(self, user_id: int) -> dict | None:
        """Get Vikunja credentials for a user (decrypted)."""
        row = await self.pool.fetchrow(
            "SELECT user_id, api_token, api_url, password_synced FROM vikunja_credentials WHERE user_id = $1",
            user_id,
        )
        if row:
            d = dict(row)
            if self._enc:
                d["api_token"] = self._enc.decrypt(d["api_token"])
            return d
        return None

    async def upsert_credentials(
        self,
        user_id: int,
        api_token: str,
        api_url: str = "",
    ) -> None:
        """Create or update Vikunja credentials for a user (encrypted if key set)."""
        enc_token = self._enc.encrypt(api_token) if self._enc else api_token
        await self.pool.execute(
            """
            INSERT INTO vikunja_credentials (user_id, api_token, api_url)
            VALUES ($1, $2, $3)
            ON CONFLICT (user_id) DO UPDATE
            SET api_token = $2, api_url = $3, updated_at = NOW()
            """,
            user_id,
            enc_token,
            api_url,
        )

    async def set_password_synced(self, user_id: int, synced: bool) -> None:
        """Update the password_synced flag for a user."""
        await self.pool.execute(
            "UPDATE vikunja_credentials SET password_synced = $1 WHERE user_id = $2",
            synced,
            user_id,
        )

    async def delete_credentials(self, user_id: int) -> None:
        """Remove Vikunja credentials for a user."""
        await self.pool.execute(
            "DELETE FROM vikunja_credentials WHERE user_id = $1",
            user_id,
        )
