"""Key-value memory store backed by PostgreSQL."""

import json
import logging
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)


class MemoryStore:
    """Persistent key-value store for agent facts and knowledge."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def get(self, key: str) -> Any | None:
        """Get a value by key. Returns None if not found."""
        row = await self.pool.fetchrow("SELECT value FROM memory WHERE key = $1", key)
        if row is None:
            return None
        try:
            return json.loads(row["value"])
        except (json.JSONDecodeError, TypeError):
            logger.warning("Corrupted memory value for key: %s", key)
            return None

    async def set(self, key: str, value: Any) -> None:
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
        result = await self.pool.execute("DELETE FROM memory WHERE key = $1", key)
        return result == "DELETE 1"

    async def search(self, prefix: str) -> list[dict]:
        """Search for keys matching a prefix. Uses parameterized LIKE."""
        rows = await self.pool.fetch(
            "SELECT key, value FROM memory WHERE key LIKE $1 ORDER BY key",
            prefix + "%",
        )
        results = []
        for row in rows:
            try:
                results.append({"key": row["key"], "value": json.loads(row["value"])})
            except (json.JSONDecodeError, TypeError):
                logger.warning("Corrupted memory value for key: %s", row["key"])
        return results

    async def list_all(self, *, limit: int = 200, offset: int = 0) -> list[dict]:
        """List all memory entries (for system prompt context), with pagination."""
        rows = await self.pool.fetch(
            "SELECT key, value FROM memory ORDER BY updated_at DESC LIMIT $1 OFFSET $2",
            limit,
            offset,
        )
        results = []
        for row in rows:
            try:
                results.append({"key": row["key"], "value": json.loads(row["value"])})
            except (json.JSONDecodeError, TypeError):
                logger.warning("Corrupted memory value for key: %s", row["key"])
        return results
