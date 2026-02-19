"""Conversation history backed by PostgreSQL."""

import logging

import asyncpg

logger = logging.getLogger(__name__)


class ConversationHistory:
    """Per-chat conversation history for context."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def initialize(self) -> None:
        """Create conversations table if it doesn't exist."""
        await self.pool.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id SERIAL PRIMARY KEY,
                chat_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await self.pool.execute("""
            CREATE INDEX IF NOT EXISTS idx_conversations_chat
            ON conversations (chat_id, created_at)
        """)
        logger.info("Conversation history initialized")

    async def add_message(self, chat_id: str, role: str, content: str) -> None:
        """Add a message to the conversation history."""
        await self.pool.execute(
            """
            INSERT INTO conversations (chat_id, role, content)
            VALUES ($1, $2, $3)
            """,
            chat_id,
            role,
            content,
        )

    async def get_recent(
        self, chat_id: str, limit: int = 20, offset: int = 0,
    ) -> list[dict]:
        """Get the most recent messages for a chat (with optional offset for pagination)."""
        rows = await self.pool.fetch(
            """
            SELECT role, content, created_at FROM conversations
            WHERE chat_id = $1
            ORDER BY created_at DESC
            LIMIT $2 OFFSET $3
            """,
            chat_id,
            limit,
            offset,
        )
        # Reverse to get chronological order
        return [
            {
                "role": row["role"],
                "content": row["content"],
                "timestamp": row["created_at"].strftime("%d.%m. %H:%M")
                if row["created_at"] else "",
            }
            for row in reversed(rows)
        ]

    async def clear(self, chat_id: str) -> int:
        """Clear all history for a chat. Returns number of deleted messages."""
        result = await self.pool.execute(
            "DELETE FROM conversations WHERE chat_id = $1", chat_id
        )
        # Result is like "DELETE 5"
        count = int(result.split()[-1])
        return count
