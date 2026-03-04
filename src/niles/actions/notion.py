"""Notion RAG retrieval — semantic search over embedded Notion content."""

import logging

import asyncpg
import httpx

logger = logging.getLogger(__name__)

_EMBED_TIMEOUT = 15.0


class NotionRetriever:
    """Retrieves relevant Notion chunks via pgvector similarity search."""

    def __init__(
        self,
        pool: asyncpg.Pool,
        ollama_base_url: str,
        model: str = "nomic-embed-text",
        similarity_threshold: float = 0.3,
    ):
        self._pool = pool
        self._ollama_url = ollama_base_url.rstrip("/").removesuffix("/v1")
        self._model = model
        self._threshold = similarity_threshold

    async def search(self, query: str, max_results: int = 5) -> list[dict]:
        """Semantic search over Notion embeddings.

        Returns list of dicts with keys:
            chunk_text, page_title, page_url, similarity
        """
        # 1. Embed the query
        embedding = await self._generate_embedding(query)
        if embedding is None:
            return []

        # 2. pgvector similarity search
        rows = await self._pool.fetch(
            """
            SELECT
                e.chunk_text,
                e.chunk_index,
                p.title AS page_title,
                p.url AS page_url,
                1 - (e.embedding <=> $1::vector) AS similarity
            FROM notion_embeddings e
            JOIN notion_pages p ON e.page_id = p.id
            WHERE 1 - (e.embedding <=> $1::vector) > $2
            ORDER BY e.embedding <=> $1::vector
            LIMIT $3
            """,
            str(embedding),
            self._threshold,
            max_results,
        )

        results = []
        for row in rows:
            results.append(
                {
                    "chunk_text": row["chunk_text"],
                    "page_title": row["page_title"],
                    "page_url": row["page_url"],
                    "similarity": round(float(row["similarity"]), 4),
                }
            )

        logger.info(
            "Notion search for '%s': %d results (threshold %.2f)",
            query[:50],
            len(results),
            self._threshold,
        )
        return results

    async def _generate_embedding(self, text: str) -> list[float] | None:
        """Call Ollama embedding API for the query text."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self._ollama_url}/api/embed",
                    json={"model": self._model, "input": text},
                    timeout=_EMBED_TIMEOUT,
                )
                response.raise_for_status()
                data = response.json()
                embeddings = data.get("embeddings", [])
                if embeddings:
                    return embeddings[0]
                return None
        except Exception:
            logger.exception("Ollama embedding request failed for query")
            return None
