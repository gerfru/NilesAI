"""Key-value memory store backed by PostgreSQL."""

import json
import logging
from typing import Any, cast

import asyncpg

from niles.types import MemoryEntry

logger = logging.getLogger(__name__)


class MemoryStore:
    """Persistent key-value store for agent facts and knowledge.

    All operations are scoped to a user_id (composite PK: user_id + key).
    """

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def get(self, user_id: int, key: str) -> Any | None:
        """Get a value by key for a specific user. Returns None if not found."""
        row = await self.pool.fetchrow(
            "SELECT value FROM memory WHERE user_id = $1 AND key = $2",
            user_id,
            key,
        )
        if row is None:
            return None
        try:
            return json.loads(row["value"])
        except json.JSONDecodeError, TypeError:
            logger.warning("Corrupted memory value for key: %s", key)
            return None

    async def set(self, user_id: int, key: str, value: Any) -> None:
        """Set a value (UPSERT). Value can be any JSON-serializable object."""
        await self.pool.execute(
            """
            INSERT INTO memory (user_id, key, value, created_at, updated_at)
            VALUES ($1, $2, $3::jsonb, NOW(), NOW())
            ON CONFLICT (user_id, key) DO UPDATE
            SET value = $3::jsonb, updated_at = NOW()
            """,
            user_id,
            key,
            json.dumps(value, ensure_ascii=False),
        )

    async def delete(self, user_id: int, key: str) -> bool:
        """Delete a key for a specific user. Returns True if the key existed."""
        result = await self.pool.execute(
            "DELETE FROM memory WHERE user_id = $1 AND key = $2",
            user_id,
            key,
        )
        return result == "DELETE 1"

    async def search(self, user_id: int, prefix: str) -> list[MemoryEntry]:
        """Search for keys matching a prefix within a user's memory."""
        rows = await self.pool.fetch(
            "SELECT key, value FROM memory WHERE user_id = $1 AND key LIKE $2 ORDER BY key",
            user_id,
            prefix + "%",
        )
        results: list[MemoryEntry] = []
        for row in rows:
            try:
                results.append(cast(MemoryEntry, {"key": row["key"], "value": json.loads(row["value"])}))
            except json.JSONDecodeError, TypeError:
                logger.warning("Corrupted memory value for key: %s", row["key"])
        return results

    async def list_all(self, user_id: int, *, limit: int = 200, offset: int = 0) -> list[MemoryEntry]:
        """List all memory entries for a user (for system prompt context)."""
        rows = await self.pool.fetch(
            "SELECT key, value FROM memory WHERE user_id = $1 ORDER BY updated_at DESC LIMIT $2 OFFSET $3",
            user_id,
            limit,
            offset,
        )
        results: list[MemoryEntry] = []
        for row in rows:
            try:
                results.append(cast(MemoryEntry, {"key": row["key"], "value": json.loads(row["value"])}))
            except json.JSONDecodeError, TypeError:
                logger.warning("Corrupted memory value for key: %s", row["key"])
        return results
