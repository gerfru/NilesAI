"""WhatsApp inbox for incoming messages from other contacts.

Stores messages in a separate table (whatsapp_inbox), completely isolated
from the conversations table used by Web-Chat and Self-Chat.
Messages are never displayed in the Web GUI and never auto-processed by the LLM.
The agent can query them via the get_whatsapp_messages tool.
"""

import logging

import asyncpg

logger = logging.getLogger(__name__)


class WhatsAppInbox:
    """Store and query incoming WhatsApp messages from other people."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def initialize(self) -> None:
        """Create whatsapp_inbox table if it doesn't exist."""
        await self.pool.execute("""
            CREATE TABLE IF NOT EXISTS whatsapp_inbox (
                id SERIAL PRIMARY KEY,
                wa_message_id TEXT UNIQUE,
                sender_phone TEXT NOT NULL,
                contact_name TEXT,
                instance_name TEXT,
                user_id INTEGER,
                content TEXT NOT NULL,
                received_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await self.pool.execute("""
            CREATE INDEX IF NOT EXISTS idx_whatsapp_inbox_sender
            ON whatsapp_inbox (sender_phone, received_at)
        """)
        await self.pool.execute("""
            CREATE INDEX IF NOT EXISTS idx_whatsapp_inbox_user
            ON whatsapp_inbox (user_id, received_at)
        """)
        logger.info("WhatsApp inbox initialized")

    async def store_message(
        self,
        wa_message_id: str,
        sender_phone: str,
        contact_name: str | None,
        instance_name: str | None,
        user_id: int | None,
        content: str,
    ) -> None:
        """Store an incoming message. Duplicates (same wa_message_id) are silently ignored."""
        await self.pool.execute(
            """
            INSERT INTO whatsapp_inbox
                (wa_message_id, sender_phone, contact_name, instance_name, user_id, content)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (wa_message_id) DO NOTHING
            """,
            wa_message_id,
            sender_phone,
            contact_name,
            instance_name,
            user_id,
            content,
        )

    async def get_messages(
        self,
        contact: str | None = None,
        phone: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """Query inbox messages by contact name or phone number.

        Args:
            contact: Contact name (ILIKE partial match).
            phone: Sender phone number (exact match).
            limit: Maximum number of messages to return (capped at 50).

        Returns:
            List of message dicts, newest first.
        """
        limit = min(limit, 50)

        if phone:
            rows = await self.pool.fetch(
                """
                SELECT sender_phone, contact_name, content, received_at
                FROM whatsapp_inbox
                WHERE sender_phone = $1
                ORDER BY received_at DESC
                LIMIT $2
                """,
                phone,
                limit,
            )
        elif contact:
            rows = await self.pool.fetch(
                """
                SELECT sender_phone, contact_name, content, received_at
                FROM whatsapp_inbox
                WHERE contact_name ILIKE '%' || $1 || '%'
                ORDER BY received_at DESC
                LIMIT $2
                """,
                contact,
                limit,
            )
        else:
            rows = await self.pool.fetch(
                """
                SELECT sender_phone, contact_name, content, received_at
                FROM whatsapp_inbox
                ORDER BY received_at DESC
                LIMIT $1
                """,
                limit,
            )

        return [
            {
                "sender_phone": row["sender_phone"],
                "contact_name": row["contact_name"],
                "content": row["content"],
                "received_at": row["received_at"].isoformat()
                if row["received_at"] else "",
            }
            for row in rows
        ]
