"""Notion embedding pipeline — chunks pages and generates embeddings."""

from __future__ import annotations

import logging

import asyncpg

from .notion_summarizer import NotionSummarizer
from .ollama_embedder import OllamaEmbedder

logger = logging.getLogger(__name__)

# Chunk levels for hierarchical RAG
LEVEL_SUMMARY = 0  # One LLM-generated summary per page
LEVEL_DETAIL = 1  # Fine-grained chunks (existing behavior)

# Pages shorter than this skip summary generation (the detail chunk IS the summary)
_MIN_CONTENT_FOR_SUMMARY = 100


class NotionEmbeddingPipeline:
    """Chunks Notion pages and generates embeddings via Ollama.

    Supports hierarchical chunking with two levels:
    - Level 0 (summary): LLM-generated page summary (requires summarizer)
    - Level 1 (detail): Fine-grained character-based chunks (always generated)
    """

    def __init__(
        self,
        pool: asyncpg.Pool,
        embedder: OllamaEmbedder,
        chunk_size: int = 600,
        chunk_overlap: int = 100,
        summarizer: NotionSummarizer | None = None,
    ):
        self._pool = pool
        self._embedder = embedder
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap
        self._summarizer = summarizer

    async def force_reembed(self) -> int:
        """Mark all pages for re-embedding by clearing embedded_at.

        Returns the number of pages marked. Call embed_pending() afterwards
        to actually regenerate the embeddings.
        """
        result = await self._pool.execute(
            "UPDATE notion_pages SET embedded_at = NULL WHERE embedded_at IS NOT NULL"
        )
        count = int(result.split()[-1])  # "UPDATE 378"
        logger.info("Marked %d pages for re-embedding", count)
        return count

    async def embed_pending(self) -> dict:
        """Process all pages that need (re-)embedding.

        Returns stats dict with pages_embedded, chunks_created,
        summaries_created, errors.
        """
        stats = {
            "pages_embedded": 0,
            "chunks_created": 0,
            "summaries_created": 0,
            "summaries_failed": 0,
            "errors": 0,
        }
        logger.info(
            "Embedding with model %s (dim check: query prefix='search_query: ', "
            "doc prefix='search_document: ')",
            self._embedder.model,
        )

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
                content_text = row["content_text"]
                title = row["title"]

                chunks = self._chunk_text(content_text, title)
                if not chunks:
                    continue

                # Delete old embeddings for this page (both levels)
                await self._pool.execute(
                    "DELETE FROM notion_embeddings WHERE page_id = $1", page_id
                )

                detail_errors = 0

                # Level 0: Summary (if summarizer is available and content is long enough)
                if (
                    self._summarizer
                    and len(content_text.strip()) >= _MIN_CONTENT_FOR_SUMMARY
                ):
                    summary = await self._summarizer.summarize(content_text, title)
                    if summary:
                        prefix = f"[{title}] " if title else ""
                        summary_text = prefix + summary
                        embedding = await self._embedder.embed(
                            summary_text, prefix="search_document: "
                        )
                        if embedding is not None:
                            await self._pool.execute(
                                """
                                INSERT INTO notion_embeddings
                                    (page_id, chunk_level, chunk_index,
                                     chunk_text, embedding)
                                VALUES ($1, $2, $3, $4, $5::vector)
                                ON CONFLICT (page_id, chunk_level, chunk_index)
                                DO UPDATE SET
                                    chunk_text = EXCLUDED.chunk_text,
                                    embedding = EXCLUDED.embedding,
                                    created_at = NOW()
                                """,
                                page_id,
                                LEVEL_SUMMARY,
                                0,
                                summary_text,
                                str(embedding),
                            )
                            stats["summaries_created"] += 1
                        else:
                            stats["summaries_failed"] += 1
                    else:
                        stats["summaries_failed"] += 1

                # Level 1: Detail chunks
                for idx, chunk_text in enumerate(chunks):
                    embedding = await self._embedder.embed(
                        chunk_text, prefix="search_document: "
                    )
                    if embedding is None:
                        detail_errors += 1
                        stats["errors"] += 1
                        continue
                    await self._pool.execute(
                        """
                        INSERT INTO notion_embeddings
                            (page_id, chunk_level, chunk_index,
                             chunk_text, embedding)
                        VALUES ($1, $2, $3, $4, $5::vector)
                        ON CONFLICT (page_id, chunk_level, chunk_index)
                        DO UPDATE SET
                            chunk_text = EXCLUDED.chunk_text,
                            embedding = EXCLUDED.embedding,
                            created_at = NOW()
                        """,
                        page_id,
                        LEVEL_DETAIL,
                        idx,
                        chunk_text,
                        str(embedding),
                    )
                    stats["chunks_created"] += 1

                # Mark page as embedded when detail chunks succeeded
                # (summary failures are non-blocking)
                if detail_errors == 0:
                    await self._pool.execute(
                        "UPDATE notion_pages SET embedded_at = NOW() WHERE id = $1",
                        page_id,
                    )
                    stats["pages_embedded"] += 1

            except Exception:
                logger.exception("Embedding failed for page %s", page_id)
                stats["errors"] += 1

        total_pending = await self._pool.fetchval("""
            SELECT COUNT(*) FROM notion_pages
            WHERE content_text != ''
              AND (embedded_at IS NULL OR embedded_at < synced_at)
        """)
        if total_pending:
            logger.info(
                "%d more pages pending embedding (batch limit 200)", total_pending
            )
        logger.info(
            "Embedding complete: %d pages, %d chunks, %d summaries "
            "(%d failed), %d errors",
            stats["pages_embedded"],
            stats["chunks_created"],
            stats["summaries_created"],
            stats["summaries_failed"],
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
                    chunks.append(current_chunk.strip())
                # Overlap: keep the last N characters
                if self._chunk_overlap > 0 and current_chunk:
                    current_chunk = current_chunk[-self._chunk_overlap :] + "\n" + para
                else:
                    current_chunk = para
            else:
                current_chunk = current_chunk + "\n" + para if current_chunk else para

        # Don't forget the last chunk
        if current_chunk.strip():
            chunks.append(current_chunk.strip())

        return [prefix + c for c in chunks if self._is_useful_chunk(c)]

    @staticmethod
    def _is_useful_chunk(chunk: str, min_ratio: float = 0.4) -> bool:
        """Return False for chunks that are mostly diagrams/box-drawing.

        Compares alphanumeric characters against non-whitespace characters
        so that space-padded ASCII art doesn't slip through.
        Expects raw chunk text WITHOUT title prefix.
        """
        non_ws = [c for c in chunk if not c.isspace()]
        if not non_ws:
            return False
        alnum_count = sum(1 for c in non_ws if c.isalnum())
        return (alnum_count / len(non_ws)) >= min_ratio
