"""User management backed by PostgreSQL."""

import logging

import asyncpg

logger = logging.getLogger(__name__)


class UserStore:
    """Manage users in PostgreSQL (created via Google OAuth)."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def initialize(self) -> None:
        """Create users table if it doesn't exist."""
        await self.pool.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                display_name TEXT NOT NULL,
                avatar_url TEXT,
                created_at TIMESTAMP DEFAULT NOW(),
                last_login TIMESTAMP DEFAULT NOW()
            )
        """)
        logger.info("User store initialized")

    async def get_by_email(self, email: str) -> dict | None:
        """Find a user by email. Returns dict or None."""
        row = await self.pool.fetchrow(
            "SELECT id, email, display_name, avatar_url FROM users WHERE email = $1",
            email,
        )
        if row:
            return dict(row)
        return None

    async def create_or_update(
        self, email: str, display_name: str, avatar_url: str | None = None,
    ) -> dict:
        """Create a new user or update last_login + profile for existing user."""
        row = await self.pool.fetchrow(
            """
            INSERT INTO users (email, display_name, avatar_url)
            VALUES ($1, $2, $3)
            ON CONFLICT (email) DO UPDATE
            SET display_name = $2, avatar_url = $3, last_login = NOW()
            RETURNING id, email, display_name, avatar_url
            """,
            email,
            display_name,
            avatar_url,
        )
        return dict(row)

    async def get_by_id(self, user_id: int) -> dict | None:
        """Find a user by ID. Returns dict or None."""
        row = await self.pool.fetchrow(
            "SELECT id, email, display_name, avatar_url FROM users WHERE id = $1",
            user_id,
        )
        if row:
            return dict(row)
        return None
