"""Notion RAG retrieval — semantic search over embedded Notion content.

Supports hierarchical chunking with auto-merge:
- Level 0: Summary embeddings (one per page)
- Level 1: Detail embeddings (fine-grained chunks)

When multiple detail chunks from the same page match, the retriever
boosts their scores and deduplicates to prevent one page from dominating.
"""

from __future__ import annotations

import logging
import re as _re
from collections import defaultdict

import asyncpg

from ..sync.ollama_embedder import OllamaEmbedder

logger = logging.getLogger(__name__)

# Auto-merge boost values (small enough to nudge, not overwhelm raw similarity)
_MULTI_HIT_BOOST = 0.05  # Applied when 2+ detail chunks from same page
_SUMMARY_BOOST = 0.03  # Applied to summary chunks with detail hits

# Keyword boost: applied when query keywords match structured metadata
_TITLE_KEYWORD_BOOST = 0.15  # Strong boost for page title match
_HEADING_KEYWORD_BOOST = 0.08  # Moderate boost for heading context match

# Per-page limits to prevent one page from dominating results
_MAX_SUMMARIES_PER_PAGE = 1
_MAX_DETAILS_PER_PAGE = 2

# German + English stop words for keyword extraction
_STOP_WORDS = frozenset(
    {
        # German articles / pronouns / prepositions
        "der",
        "die",
        "das",
        "den",
        "dem",
        "des",
        "ein",
        "eine",
        "einen",
        "einem",
        "eines",
        "einer",
        "ich",
        "du",
        "er",
        "sie",
        "es",
        "wir",
        "ihr",
        "mich",
        "mir",
        "dich",
        "dir",
        "sich",
        "uns",
        "euch",
        "mein",
        "meine",
        "meiner",
        "meinem",
        "meinen",
        "dein",
        "deine",
        "deiner",
        "deinem",
        "deinen",
        # German conjunctions / particles
        "und",
        "oder",
        "aber",
        "doch",
        "sondern",
        "auch",
        "noch",
        "schon",
        "nur",
        "wenn",
        "als",
        "dass",
        "ob",
        "weil",
        "da",
        "so",
        "dann",
        "dort",
        "hier",
        # German prepositions
        "in",
        "im",
        "an",
        "am",
        "auf",
        "aus",
        "bei",
        "mit",
        "nach",
        "von",
        "vom",
        "vor",
        "zu",
        "zum",
        "zur",
        "ueber",
        "unter",
        # German verbs (common)
        "ist",
        "sind",
        "war",
        "hat",
        "haben",
        "wird",
        "werden",
        "kann",
        "muss",
        "soll",
        "darf",
        "steht",
        # German question words
        "was",
        "wer",
        "wie",
        "wo",
        "wann",
        "warum",
        "welche",
        "welcher",
        "welches",
        # German negation
        "nicht",
        "kein",
        "keine",
        "keinen",
        "keinem",
        "keiner",
        # English basics
        "the",
        "is",
        "are",
        "was",
        "were",
        "of",
        "in",
        "to",
        "for",
        "with",
        "on",
        "at",
        "by",
        "what",
        "how",
        "where",
        "when",
        "which",
        "who",
        # Domain-specific
        "wissensdatenbank",
        "notion",
    }
)


def _extract_keywords(query: str) -> list[str]:
    """Extract meaningful keywords from a search query.

    Strips stop words, punctuation, and short tokens.
    Returns lowercased keywords for case-insensitive matching.
    """
    tokens = _re.findall(
        r"[\w\u00e4\u00f6\u00fc\u00c4\u00d6\u00dc\u00df]+", query.lower()
    )
    return [t for t in tokens if t not in _STOP_WORDS and len(t) >= 2]


class NotionRetriever:
    """Retrieves relevant Notion chunks via pgvector similarity search.

    Uses auto-merge scoring: when multiple detail chunks from the same page
    appear in results, their scores are boosted and deduplicated.
    """

    def __init__(
        self,
        pool: asyncpg.Pool,
        embedder: OllamaEmbedder,
        similarity_threshold: float = 0.3,
    ):
        self._pool = pool
        self._embedder = embedder
        self._threshold = similarity_threshold

    async def search(self, query: str, max_results: int = 5) -> list[dict]:
        """Semantic search over Notion embeddings with auto-merge.

        Returns list of dicts with keys:
            chunk_text, page_title, page_url, similarity
        """
        # 1. Embed the query
        embedding = await self._embedder.embed(query, prefix="search_query: ")
        if embedding is None:
            return []

        # 2. Fetch more candidates than needed for auto-merge scoring
        internal_limit = max_results * 3
        rows = await self._pool.fetch(
            """
            SELECT
                e.chunk_text,
                e.chunk_index,
                e.chunk_level,
                e.page_id,
                e.page_title AS meta_title,
                e.heading_context,
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
            internal_limit,
        )

        if not rows:
            logger.info(
                "Notion search for '%s': 0 results (threshold %.2f)",
                query[:50],
                self._threshold,
            )
            return []

        # 3. Group by page_id for auto-merge scoring
        page_detail_counts: dict[str, int] = defaultdict(int)
        for row in rows:
            if row["chunk_level"] == 1:
                page_detail_counts[row["page_id"]] += 1

        # 4. Score and build candidates (with keyword boost)
        keywords = _extract_keywords(query)
        candidates = []
        for row in rows:
            pid = row["page_id"]
            base_sim = float(row["similarity"])
            boost = 0.0

            # Multi-hit boost: 2+ detail chunks from same page
            if page_detail_counts[pid] >= 2:
                boost += _MULTI_HIT_BOOST

            # Summary boost: summary chunk has detail hits from same page
            if row["chunk_level"] == 0 and page_detail_counts[pid] >= 1:
                boost += _SUMMARY_BOOST

            # Keyword boost: query keywords in page title or heading
            if keywords:
                meta_lower = (row["meta_title"] or "").lower()
                heading_lower = (row["heading_context"] or "").lower()
                if any(kw in meta_lower for kw in keywords):
                    boost += _TITLE_KEYWORD_BOOST
                if any(kw in heading_lower for kw in keywords):
                    boost += _HEADING_KEYWORD_BOOST

            candidates.append(
                {
                    "chunk_text": row["chunk_text"],
                    "page_title": row["page_title"],
                    "page_url": row["page_url"],
                    "similarity": round(min(base_sim + boost, 1.0), 4),
                    "_chunk_level": row["chunk_level"],
                    "_page_id": pid,
                }
            )

        # 5. Sort by adjusted similarity
        candidates.sort(key=lambda r: r["similarity"], reverse=True)

        # 6. Deduplicate: max summaries + details per page
        seen: dict[str, dict[int, int]] = {}
        results = []
        for c in candidates:
            pid = c["_page_id"]
            level = c["_chunk_level"]
            if pid not in seen:
                seen[pid] = {0: 0, 1: 0}

            max_per_level = (
                _MAX_SUMMARIES_PER_PAGE if level == 0 else _MAX_DETAILS_PER_PAGE
            )
            if seen[pid][level] >= max_per_level:
                continue
            seen[pid][level] += 1

            # Strip internal fields before returning
            results.append(
                {
                    "chunk_text": c["chunk_text"],
                    "page_title": c["page_title"],
                    "page_url": c["page_url"],
                    "similarity": c["similarity"],
                }
            )
            if len(results) >= max_results:
                break

        logger.info(
            "Notion search for '%s': %d results (threshold %.2f, candidates %d)",
            query[:50],
            len(results),
            self._threshold,
            len(rows),
        )
        return results
