"""Tests for Notion RAG retriever (actions/notion.py)."""

from unittest.mock import AsyncMock

from niles.actions.notion import NotionRetriever
from niles.sync.ollama_embedder import OllamaEmbedder


# ---------- Helpers ----------------------------------------------------------


def _retriever(pool=None, threshold=0.3):
    p = pool or AsyncMock()
    embedder = AsyncMock(spec=OllamaEmbedder)
    return (
        NotionRetriever(
            pool=p,
            embedder=embedder,
            similarity_threshold=threshold,
        ),
        p,
        embedder,
    )


def _fake_embedding(dim=768):
    return [0.1] * dim


def _make_row(
    chunk_text="text",
    page_title="Title",
    page_url="https://notion.so/page",
    similarity=0.8,
    chunk_level=1,
    chunk_index=0,
    page_id="page1",
):
    """Create a mock DB row with all required fields."""
    return {
        "chunk_text": chunk_text,
        "chunk_index": chunk_index,
        "chunk_level": chunk_level,
        "page_id": page_id,
        "page_title": page_title,
        "page_url": page_url,
        "similarity": similarity,
    }


# ---------- search -----------------------------------------------------------


class TestSearch:
    async def test_happy_path(self):
        ret, pool, embedder = _retriever()
        embedder.embed.return_value = _fake_embedding()
        pool.fetch.return_value = [
            _make_row(
                chunk_text="Niles is an AI butler.",
                page_title="About Niles",
                page_url="https://notion.so/about",
                similarity=0.87654321,
                chunk_level=1,
                page_id="p1",
            ),
        ]

        results = await ret.search("What is Niles?")

        assert len(results) == 1
        assert results[0]["page_title"] == "About Niles"
        assert results[0]["similarity"] == 0.8765  # Rounded to 4 decimals

        # Verify SQL
        pool.fetch.assert_called_once()
        sql = pool.fetch.call_args[0][0]
        assert "notion_embeddings" in sql
        assert "<=> $1::vector" in sql

    async def test_embedding_failure_returns_empty(self):
        ret, pool, embedder = _retriever()
        embedder.embed.return_value = None

        results = await ret.search("test query")

        assert results == []
        pool.fetch.assert_not_called()

    async def test_no_results_returns_empty(self):
        ret, pool, embedder = _retriever()
        embedder.embed.return_value = _fake_embedding()
        pool.fetch.return_value = []

        results = await ret.search("obscure query")

        assert results == []

    async def test_internal_limit_is_multiplied(self):
        """Internal limit = max_results * 3 for auto-merge candidate pool."""
        ret, pool, embedder = _retriever()
        embedder.embed.return_value = _fake_embedding()
        pool.fetch.return_value = []

        await ret.search("test", max_results=3)

        args = pool.fetch.call_args[0]
        # $3 = internal_limit = 3 * 3 = 9
        assert args[3] == 9

    async def test_threshold_passed_to_sql(self):
        ret, pool, embedder = _retriever(threshold=0.5)
        embedder.embed.return_value = _fake_embedding()
        pool.fetch.return_value = []

        await ret.search("test")

        args = pool.fetch.call_args[0]
        # $2 = threshold
        assert args[2] == 0.5

    async def test_search_uses_query_prefix(self):
        ret, pool, embedder = _retriever()
        embedder.embed.return_value = _fake_embedding()
        pool.fetch.return_value = []

        await ret.search("test query")

        embedder.embed.assert_called_once_with("test query", prefix="search_query: ")


# ---------- auto-merge scoring -----------------------------------------------


class TestAutoMerge:
    async def test_multi_hit_boost(self):
        """2+ detail chunks from same page get boosted similarity."""
        ret, pool, embedder = _retriever()
        embedder.embed.return_value = _fake_embedding()
        pool.fetch.return_value = [
            _make_row(
                chunk_text="Chunk A",
                similarity=0.7,
                page_id="p1",
                chunk_level=1,
                chunk_index=0,
            ),
            _make_row(
                chunk_text="Chunk B",
                similarity=0.65,
                page_id="p1",
                chunk_level=1,
                chunk_index=1,
            ),
            _make_row(
                chunk_text="Other page",
                similarity=0.72,
                page_id="p2",
                chunk_level=1,
                chunk_index=0,
            ),
        ]

        results = await ret.search("test", max_results=5)

        # p1 chunks should be boosted (0.7 + 0.05 = 0.75, 0.65 + 0.05 = 0.70)
        # p2 stays at 0.72
        # After sort: p1/A (0.75), p2 (0.72), p1/B (0.70)
        assert results[0]["chunk_text"] == "Chunk A"
        assert results[0]["similarity"] == 0.75

    async def test_summary_boost_with_detail(self):
        """Summary chunk boosted when same page has detail hits."""
        ret, pool, embedder = _retriever()
        embedder.embed.return_value = _fake_embedding()
        pool.fetch.return_value = [
            _make_row(
                chunk_text="Summary of page",
                similarity=0.6,
                page_id="p1",
                chunk_level=0,
                chunk_index=0,
            ),
            _make_row(
                chunk_text="Detail chunk",
                similarity=0.65,
                page_id="p1",
                chunk_level=1,
                chunk_index=0,
            ),
        ]

        results = await ret.search("test", max_results=5)

        # Summary gets _SUMMARY_BOOST (0.03): 0.6 + 0.03 = 0.63
        # Detail has no multi-hit boost (only 1 detail): 0.65
        summary_result = [r for r in results if "Summary" in r["chunk_text"]]
        assert len(summary_result) == 1
        assert summary_result[0]["similarity"] == 0.63

    async def test_per_page_deduplication(self):
        """Max 1 summary + 2 details per page."""
        ret, pool, embedder = _retriever()
        embedder.embed.return_value = _fake_embedding()
        pool.fetch.return_value = [
            _make_row(
                chunk_text="Detail 1",
                similarity=0.9,
                page_id="p1",
                chunk_level=1,
                chunk_index=0,
            ),
            _make_row(
                chunk_text="Detail 2",
                similarity=0.85,
                page_id="p1",
                chunk_level=1,
                chunk_index=1,
            ),
            _make_row(
                chunk_text="Detail 3",
                similarity=0.8,
                page_id="p1",
                chunk_level=1,
                chunk_index=2,
            ),
        ]

        results = await ret.search("test", max_results=5)

        # Only 2 details from p1 should be in results
        p1_results = [r for r in results if r["page_url"] == "https://notion.so/page"]
        assert len(p1_results) == 2

    async def test_chunk_level_not_in_output(self):
        """Internal fields (_chunk_level, _page_id) must not leak to output."""
        ret, pool, embedder = _retriever()
        embedder.embed.return_value = _fake_embedding()
        pool.fetch.return_value = [
            _make_row(chunk_text="test", similarity=0.8),
        ]

        results = await ret.search("test", max_results=5)

        assert len(results) == 1
        assert "_chunk_level" not in results[0]
        assert "_page_id" not in results[0]
        assert "chunk_level" not in results[0]
        assert "page_id" not in results[0]

    async def test_similarity_capped_at_1(self):
        """Boosted similarity should never exceed 1.0."""
        ret, pool, embedder = _retriever()
        embedder.embed.return_value = _fake_embedding()
        pool.fetch.return_value = [
            _make_row(similarity=0.98, page_id="p1", chunk_level=1, chunk_index=0),
            _make_row(similarity=0.97, page_id="p1", chunk_level=1, chunk_index=1),
        ]

        results = await ret.search("test", max_results=5)

        # 0.98 + 0.05 = 1.03 -> capped at 1.0
        assert results[0]["similarity"] <= 1.0

    async def test_max_results_respected(self):
        """Final results list respects max_results."""
        ret, pool, embedder = _retriever()
        embedder.embed.return_value = _fake_embedding()
        pool.fetch.return_value = [
            _make_row(
                chunk_text=f"Chunk {i}",
                similarity=0.9 - i * 0.05,
                page_id=f"p{i}",
            )
            for i in range(10)
        ]

        results = await ret.search("test", max_results=3)

        assert len(results) == 3
