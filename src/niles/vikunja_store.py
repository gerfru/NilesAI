"""Per-user Vikunja credential management backed by PostgreSQL."""

import logging

import asyncpg

logger = logging.getLogger(__name__)


class VikunjCredentialStore:
    """Manage per-user Vikunja API credentials."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def initialize(self) -> None:
        """Create vikunja_credentials table if it doesn't exist."""
        await self.pool.execute("""
            CREATE TABLE IF NOT EXISTS vikunja_credentials (
                user_id INTEGER PRIMARY KEY REFERENCES users(id),
                api_token TEXT NOT NULL,
                api_url TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)
        logger.info("Vikunja credential store initialized")

    async def get_credentials(self, user_id: int) -> dict | None:
        """Get Vikunja credentials for a user."""
        row = await self.pool.fetchrow(
            "SELECT user_id, api_token, api_url "
            "FROM vikunja_credentials WHERE user_id = $1",
            user_id,
        )
        if row:
            return dict(row)
        return None

    async def upsert_credentials(
        self, user_id: int, api_token: str, api_url: str = "",
    ) -> None:
        """Create or update Vikunja credentials for a user."""
        await self.pool.execute(
            """
            INSERT INTO vikunja_credentials (user_id, api_token, api_url)
            VALUES ($1, $2, $3)
            ON CONFLICT (user_id) DO UPDATE
            SET api_token = $2, api_url = $3, updated_at = NOW()
            """,
            user_id,
            api_token,
            api_url,
        )

    async def delete_credentials(self, user_id: int) -> None:
        """Remove Vikunja credentials for a user."""
        await self.pool.execute(
            "DELETE FROM vikunja_credentials WHERE user_id = $1", user_id,
        )
