"""Notion pages and embeddings data access."""

import logging

import asyncpg

logger = logging.getLogger(__name__)


class NotionStore:
    """Read/clear operations for notion_pages and notion_embeddings tables."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def get_page_stats(self) -> dict:
        """Return page count and last sync timestamp."""
        row = await self.pool.fetchrow(
            "SELECT COUNT(*) AS cnt, MAX(synced_at) AS last_sync FROM notion_pages"
        )
        return dict(row) if row else {"cnt": 0, "last_sync": None}

    async def get_embedding_stats(self) -> list[dict]:
        """Return per-chunk-level counts."""
        rows = await self.pool.fetch(
            "SELECT chunk_level, COUNT(*) AS cnt"
            " FROM notion_embeddings GROUP BY chunk_level"
        )
        return [dict(r) for r in rows]

    async def clear_all(self) -> None:
        """Remove all Notion pages and embeddings (disconnect cleanup)."""
        await self.pool.execute("DELETE FROM notion_embeddings")
        await self.pool.execute("DELETE FROM notion_pages")
        logger.info("Notion data cleared")
