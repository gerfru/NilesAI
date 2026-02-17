"""Key-value memory store backed by PostgreSQL."""

import json
import logging

import asyncpg

logger = logging.getLogger(__name__)


class MemoryStore:
    """Persistent key-value store for agent facts and knowledge."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def initialize(self) -> None:
        """Create memory table if it doesn't exist."""
        await self.pool.execute("""
            CREATE TABLE IF NOT EXISTS memory (
                key TEXT PRIMARY KEY,
                value JSONB NOT NULL,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)
        logger.info("Memory store initialized")

    async def get(self, key: str) -> dict | None:
        """Get a value by key. Returns None if not found."""
        row = await self.pool.fetchrow(
            "SELECT value FROM memory WHERE key = $1", key
        )
        if row is None:
            return None
        return json.loads(row["value"])

    async def set(self, key: str, value) -> None:
        """Set a value (UPSERT). Value can be any JSON-serializable object."""
        await self.pool.execute(
            """
            INSERT INTO memory (key, value, created_at, updated_at)
            VALUES ($1, $2::jsonb, NOW(), NOW())
            ON CONFLICT (key) DO UPDATE
            SET value = $2::jsonb, updated_at = NOW()
            """,
            key,
            json.dumps(value, ensure_ascii=False),
        )

    async def delete(self, key: str) -> bool:
        """Delete a key. Returns True if the key existed."""
        result = await self.pool.execute(
            "DELETE FROM memory WHERE key = $1", key
        )
        return result == "DELETE 1"

    async def search(self, prefix: str) -> list[dict]:
        """Search for keys matching a prefix."""
        rows = await self.pool.fetch(
            "SELECT key, value FROM memory WHERE key LIKE $1 || '%' ORDER BY key",
            prefix,
        )
        return [{"key": row["key"], "value": json.loads(row["value"])} for row in rows]

    async def list_all(self) -> list[dict]:
        """List all memory entries (for system prompt context)."""
        rows = await self.pool.fetch(
            "SELECT key, value FROM memory ORDER BY updated_at DESC"
        )
        return [{"key": row["key"], "value": json.loads(row["value"])} for row in rows]
