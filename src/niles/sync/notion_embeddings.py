"""Notion embedding pipeline — chunks pages and generates embeddings."""

import logging

import asyncpg
import httpx

logger = logging.getLogger(__name__)

# Ollama embedding endpoint timeout
_EMBED_TIMEOUT = 30.0


class NotionEmbeddingPipeline:
    """Chunks Notion pages and generates embeddings via Ollama."""

    def __init__(
        self,
        pool: asyncpg.Pool,
        ollama_base_url: str,
        model: str = "nomic-embed-text",
        chunk_size: int = 600,
        chunk_overlap: int = 100,
    ):
        self._pool = pool
        self._ollama_url = ollama_base_url.rstrip("/").removesuffix("/v1")
        self._model = model
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap

    async def embed_pending(self) -> dict:
        """Process all pages that need (re-)embedding.

        Returns stats dict with pages_embedded, chunks_created, errors.
        """
        stats = {"pages_embedded": 0, "chunks_created": 0, "errors": 0}

        rows = await self._pool.fetch("""
            SELECT id, title, content_text
            FROM notion_pages
            WHERE content_text != ''
              AND (embedded_at IS NULL OR embedded_at < synced_at)
            ORDER BY synced_at DESC
            LIMIT 200
        """)

        for row in rows:
            page_id = row["id"]
            try:
                chunks = self._chunk_text(row["content_text"], row["title"])
                if not chunks:
                    continue

                # Delete old embeddings for this page
                await self._pool.execute(
                    "DELETE FROM notion_embeddings WHERE page_id = $1", page_id
                )

                # Generate embeddings and insert
                for idx, chunk_text in enumerate(chunks):
                    embedding = await self._generate_embedding(chunk_text)
                    if embedding is None:
                        stats["errors"] += 1
                        continue
                    await self._pool.execute(
                        """
                        INSERT INTO notion_embeddings (page_id, chunk_index, chunk_text, embedding)
                        VALUES ($1, $2, $3, $4::vector)
                        ON CONFLICT (page_id, chunk_index) DO UPDATE SET
                            chunk_text = EXCLUDED.chunk_text,
                            embedding = EXCLUDED.embedding,
                            created_at = NOW()
                        """,
                        page_id,
                        idx,
                        chunk_text,
                        str(embedding),
                    )
                    stats["chunks_created"] += 1

                # Mark page as embedded
                await self._pool.execute(
                    "UPDATE notion_pages SET embedded_at = NOW() WHERE id = $1",
                    page_id,
                )
                stats["pages_embedded"] += 1

            except Exception:
                logger.exception("Embedding failed for page %s", page_id)
                stats["errors"] += 1

        logger.info(
            "Embedding complete: %d pages, %d chunks, %d errors",
            stats["pages_embedded"],
            stats["chunks_created"],
            stats["errors"],
        )
        return stats

    def _chunk_text(self, text: str, title: str = "") -> list[str]:
        """Split text into overlapping chunks.

        Each chunk is prefixed with the page title for context.
        Uses character-based splitting with paragraph awareness.
        Chunks that are mostly non-text (ASCII art, box-drawing) are dropped.
        """
        if not text.strip():
            return []

        prefix = f"[{title}] " if title else ""
        paragraphs = text.split("\n")
        chunks: list[str] = []
        current_chunk = ""

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            # If adding this paragraph exceeds chunk_size, save current and start new
            if len(current_chunk) + len(para) + 1 > self._chunk_size:
                if current_chunk:
                    chunks.append(prefix + current_chunk.strip())
                # Overlap: keep the last N characters
                if self._chunk_overlap > 0 and current_chunk:
                    current_chunk = current_chunk[-self._chunk_overlap :] + "\n" + para
                else:
                    current_chunk = para
            else:
                current_chunk = current_chunk + "\n" + para if current_chunk else para

        # Don't forget the last chunk
        if current_chunk.strip():
            chunks.append(prefix + current_chunk.strip())

        return [c for c in chunks if self._is_useful_chunk(c)]

    @staticmethod
    def _is_useful_chunk(chunk: str, min_ratio: float = 0.4) -> bool:
        """Return False for chunks that are mostly diagrams/box-drawing.

        Compares alphanumeric characters against non-whitespace characters
        so that space-padded ASCII art doesn't slip through.
        """
        # Strip title prefix before checking
        text = chunk
        if text.startswith("["):
            end = text.find("] ")
            if end != -1:
                text = text[end + 2 :]
        non_ws = [c for c in text if not c.isspace()]
        if not non_ws:
            return False
        alnum_count = sum(1 for c in non_ws if c.isalnum())
        return (alnum_count / len(non_ws)) >= min_ratio

    async def _generate_embedding(self, text: str) -> list[float] | None:
        """Call Ollama embedding API for a single text."""
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
            logger.exception("Ollama embedding request failed")
            return None
