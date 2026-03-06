"""Per-user Google OAuth token management backed by PostgreSQL."""

import logging
from datetime import datetime

import asyncpg

logger = logging.getLogger(__name__)


class GoogleTokenStore:
    """Manage per-user Google OAuth tokens for gws MCP server instances."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def get_tokens(self, user_id: int) -> dict | None:
        """Get Google tokens for a user."""
        row = await self.pool.fetchrow(
            "SELECT user_id, refresh_token, access_token, token_expiry, scopes "
            "FROM user_google_tokens WHERE user_id = $1",
            user_id,
        )
        if row:
            return dict(row)
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
        """Create or update Google tokens for a user."""
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
            refresh_token,
            access_token,
            token_expiry,
            scopes,
        )

    async def delete_tokens(self, user_id: int) -> None:
        """Remove Google tokens for a user (disconnect)."""
        await self.pool.execute(
            "DELETE FROM user_google_tokens WHERE user_id = $1",
            user_id,
        )
