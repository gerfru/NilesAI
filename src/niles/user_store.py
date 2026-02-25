"""User management backed by PostgreSQL."""

import logging

import asyncpg

logger = logging.getLogger(__name__)


class UserStore:
    """Manage users in PostgreSQL (Google OAuth + password auth)."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def initialize(self) -> None:
        """Create users table and run migrations."""
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
        # Migration: add password_hash, auth_method, is_admin columns
        await self.pool.execute("""
            ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash TEXT
        """)
        await self.pool.execute("""
            ALTER TABLE users ADD COLUMN IF NOT EXISTS auth_method TEXT
                NOT NULL DEFAULT 'google'
        """)
        await self.pool.execute("""
            ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN
                NOT NULL DEFAULT FALSE
        """)
        # Auto-promote: if exactly one user exists and no admin, make them admin
        admin_count = await self.pool.fetchval(
            "SELECT COUNT(*) FROM users WHERE is_admin = TRUE"
        )
        if admin_count == 0:
            total = await self.pool.fetchval("SELECT COUNT(*) FROM users")
            if total == 1:
                await self.pool.execute(
                    "UPDATE users SET is_admin = TRUE WHERE id = "
                    "(SELECT id FROM users LIMIT 1)"
                )
                logger.info("Auto-promoted single existing user to admin")
        logger.info("User store initialized")

    async def get_by_email(self, email: str) -> dict | None:
        """Find a user by email. Returns dict or None."""
        row = await self.pool.fetchrow(
            "SELECT id, email, display_name, avatar_url, is_admin"
            " FROM users WHERE email = $1",
            email,
        )
        if row:
            return dict(row)
        return None

    async def get_with_hash(self, email: str) -> dict | None:
        """Find a user by email, including password_hash and auth_method."""
        row = await self.pool.fetchrow(
            "SELECT id, email, display_name, avatar_url, password_hash,"
            " auth_method, is_admin FROM users WHERE email = $1",
            email,
        )
        if row:
            return dict(row)
        return None

    async def create_or_update(
        self,
        email: str,
        display_name: str,
        avatar_url: str | None = None,
    ) -> dict:
        """Create a new user or update last_login + profile for existing user.

        Used by Google OAuth flow. Sets auth_method='google'.
        First user is automatically promoted to admin.
        """
        is_first = await self.pool.fetchval("SELECT COUNT(*) FROM users") == 0
        row = await self.pool.fetchrow(
            """
            INSERT INTO users (email, display_name, avatar_url, auth_method, is_admin)
            VALUES ($1, $2, $3, 'google', $4)
            ON CONFLICT (email) DO UPDATE
            SET display_name = $2, avatar_url = $3, last_login = NOW()
            RETURNING id, email, display_name, avatar_url, is_admin
            """,
            email,
            display_name,
            avatar_url,
            is_first,
        )
        return dict(row)

    async def create_password_user(
        self,
        email: str,
        display_name: str,
        password_hash: str,
    ) -> dict:
        """Create a user with password authentication.

        First user is automatically promoted to admin.
        """
        is_first = await self.pool.fetchval("SELECT COUNT(*) FROM users") == 0
        row = await self.pool.fetchrow(
            """
            INSERT INTO users (email, display_name, password_hash, auth_method, is_admin)
            VALUES ($1, $2, $3, 'password', $4)
            RETURNING id, email, display_name, avatar_url, is_admin
            """,
            email,
            display_name,
            password_hash,
            is_first,
        )
        return dict(row)

    async def get_by_id(self, user_id: int) -> dict | None:
        """Find a user by ID. Returns dict or None."""
        row = await self.pool.fetchrow(
            "SELECT id, email, display_name, avatar_url, is_admin"
            " FROM users WHERE id = $1",
            user_id,
        )
        if row:
            return dict(row)
        return None

    async def update_password(self, user_id: int, password_hash: str) -> bool:
        """Update password hash for a user. Returns True if updated."""
        result = await self.pool.execute(
            "UPDATE users SET password_hash = $1 WHERE id = $2",
            password_hash,
            user_id,
        )
        return result == "UPDATE 1"

    async def list_all(self) -> list[dict]:
        """List all users (for admin page)."""
        rows = await self.pool.fetch(
            "SELECT id, email, display_name, auth_method, is_admin,"
            " created_at, last_login FROM users ORDER BY id"
        )
        return [dict(r) for r in rows]

    async def delete_user(self, user_id: int) -> bool:
        """Delete a user by ID. Returns True if deleted."""
        result = await self.pool.execute("DELETE FROM users WHERE id = $1", user_id)
        return result == "DELETE 1"

    async def has_password_users(self) -> bool:
        """Check if any password-auth users exist (for login page display)."""
        count = await self.pool.fetchval(
            "SELECT COUNT(*) FROM users WHERE auth_method = 'password'"
        )
        return count > 0
