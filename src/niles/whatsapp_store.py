"""WhatsApp session management backed by PostgreSQL."""

import logging

import asyncpg

logger = logging.getLogger(__name__)


class WhatsAppSessionStore:
    """Manage per-user WhatsApp sessions (Evolution API instances)."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def initialize(self) -> None:
        """Create whatsapp_sessions table if it doesn't exist."""
        await self.pool.execute("""
            CREATE TABLE IF NOT EXISTS whatsapp_sessions (
                user_id INTEGER PRIMARY KEY REFERENCES users(id),
                instance_name TEXT UNIQUE NOT NULL,
                phone_number TEXT,
                status TEXT NOT NULL DEFAULT 'disconnected'
                    CHECK (status IN ('disconnected', 'connecting', 'connected')),
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)
        await self.pool.execute("""
            CREATE INDEX IF NOT EXISTS whatsapp_sessions_phone_idx
            ON whatsapp_sessions (phone_number)
        """)
        logger.info("WhatsApp session store initialized")

    async def get_session(self, user_id: int) -> dict | None:
        """Get WhatsApp session for a user."""
        row = await self.pool.fetchrow(
            "SELECT user_id, instance_name, phone_number, status "
            "FROM whatsapp_sessions WHERE user_id = $1",
            user_id,
        )
        if row:
            return dict(row)
        return None

    async def get_by_instance(self, instance_name: str) -> dict | None:
        """Look up session by Evolution API instance name (for webhook routing)."""
        row = await self.pool.fetchrow(
            "SELECT user_id, instance_name, phone_number, status "
            "FROM whatsapp_sessions WHERE instance_name = $1",
            instance_name,
        )
        if row:
            return dict(row)
        return None

    async def get_by_phone(self, phone_number: str) -> dict | None:
        """Look up session by phone number (for self-chat user resolution)."""
        row = await self.pool.fetchrow(
            "SELECT user_id, instance_name, phone_number, status "
            "FROM whatsapp_sessions WHERE phone_number = $1",
            phone_number,
        )
        if row:
            return dict(row)
        return None

    async def upsert_session(
        self,
        user_id: int,
        instance_name: str,
        status: str,
        phone_number: str | None = None,
    ) -> None:
        """Create or update a WhatsApp session."""
        await self.pool.execute(
            """
            INSERT INTO whatsapp_sessions (user_id, instance_name, phone_number, status)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (user_id) DO UPDATE
            SET instance_name = $2, phone_number = $3, status = $4, updated_at = NOW()
            """,
            user_id,
            instance_name,
            phone_number,
            status,
        )

    async def update_status(
        self, user_id: int, status: str, phone_number: str | None = None,
    ) -> None:
        """Update session status (and optionally phone number)."""
        if phone_number is not None:
            await self.pool.execute(
                "UPDATE whatsapp_sessions SET status = $2, phone_number = $3, "
                "updated_at = NOW() WHERE user_id = $1",
                user_id, status, phone_number,
            )
        else:
            await self.pool.execute(
                "UPDATE whatsapp_sessions SET status = $2, "
                "updated_at = NOW() WHERE user_id = $1",
                user_id, status,
            )

    async def delete_session(self, user_id: int) -> None:
        """Remove a WhatsApp session."""
        await self.pool.execute(
            "DELETE FROM whatsapp_sessions WHERE user_id = $1", user_id
        )
