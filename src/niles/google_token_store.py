"""Per-user Google OAuth token management backed by PostgreSQL."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

import asyncpg

if TYPE_CHECKING:
    from .crypto import FieldEncryptor

logger = logging.getLogger(__name__)


class GoogleTokenStore:
    """Manage per-user Google OAuth tokens for gws MCP server instances."""

    def __init__(self, pool: asyncpg.Pool, *, encryptor: FieldEncryptor | None = None):
        self.pool = pool
        self._enc = encryptor

    async def get_tokens(self, user_id: int) -> dict | None:
        """Get Google tokens for a user (decrypted)."""
        row = await self.pool.fetchrow(
            "SELECT user_id, refresh_token, access_token, token_expiry, scopes "
            "FROM user_google_tokens WHERE user_id = $1",
            user_id,
        )
        if row:
            d = dict(row)
            if self._enc:
                d["refresh_token"] = self._enc.decrypt(d["refresh_token"])
                d["access_token"] = self._enc.decrypt(d["access_token"])
            return d
        return None

    async def has_tokens(self, user_id: int) -> bool:
        """Check if a user has stored Google tokens."""
        row = await self.pool.fetchval(
            "SELECT 1 FROM user_google_tokens WHERE user_id = $1",
            user_id,
        )
        return row is not None

    async def upsert_tokens(
        self,
        user_id: int,
        refresh_token: str,
        access_token: str = "",
        token_expiry: datetime | None = None,
        scopes: str = "",
    ) -> None:
        """Create or update Google tokens for a user (encrypted if key set)."""
        enc_refresh = self._enc.encrypt(refresh_token) if self._enc else refresh_token
        enc_access = self._enc.encrypt(access_token) if self._enc else access_token
        await self.pool.execute(
            """
            INSERT INTO user_google_tokens
                (user_id, refresh_token, access_token, token_expiry, scopes)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (user_id) DO UPDATE
            SET refresh_token = $2, access_token = $3,
                token_expiry = $4, scopes = $5, updated_at = NOW()
            """,
            user_id,
            enc_refresh,
            enc_access,
            token_expiry,
            scopes,
        )

    async def delete_tokens(self, user_id: int) -> None:
        """Remove Google tokens for a user (disconnect)."""
        await self.pool.execute(
            "DELETE FROM user_google_tokens WHERE user_id = $1",
            user_id,
        )
