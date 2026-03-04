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


# ---------- search -----------------------------------------------------------


class TestSearch:
    async def test_happy_path(self):
        ret, pool, embedder = _retriever()
        embedder.embed.return_value = _fake_embedding()
        pool.fetch.return_value = [
            {
                "chunk_text": "Niles is an AI butler.",
                "page_title": "About Niles",
                "page_url": "https://notion.so/about",
                "similarity": 0.87654321,
            },
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

    async def test_max_results_passed_to_sql(self):
        ret, pool, embedder = _retriever()
        embedder.embed.return_value = _fake_embedding()
        pool.fetch.return_value = []

        await ret.search("test", max_results=3)

        args = pool.fetch.call_args[0]
        # $3 = max_results
        assert args[3] == 3

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
