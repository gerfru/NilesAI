"""Tests for Notion RAG retriever (actions/notion.py)."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from niles.actions.notion import NotionRetriever


# ---------- Helpers ----------------------------------------------------------


def _retriever(pool=None, threshold=0.3):
    p = pool or AsyncMock()
    return (
        NotionRetriever(
            pool=p,
            ollama_base_url="http://localhost:11434",
            model="nomic-embed-text",
            similarity_threshold=threshold,
        ),
        p,
    )


def _fake_embedding(dim=768):
    return [0.1] * dim


# ---------- search -----------------------------------------------------------


class TestSearch:
    async def test_happy_path(self):
        ret, pool = _retriever()
        pool.fetch.return_value = [
            {
                "chunk_text": "Niles is an AI butler.",
                "page_title": "About Niles",
                "page_url": "https://notion.so/about",
                "similarity": 0.87654321,
            },
        ]

        with patch.object(ret, "_generate_embedding", return_value=_fake_embedding()):
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
        ret, pool = _retriever()

        with patch.object(ret, "_generate_embedding", return_value=None):
            results = await ret.search("test query")

        assert results == []
        pool.fetch.assert_not_called()

    async def test_no_results_returns_empty(self):
        ret, pool = _retriever()
        pool.fetch.return_value = []

        with patch.object(ret, "_generate_embedding", return_value=_fake_embedding()):
            results = await ret.search("obscure query")

        assert results == []

    async def test_max_results_passed_to_sql(self):
        ret, pool = _retriever()
        pool.fetch.return_value = []

        with patch.object(ret, "_generate_embedding", return_value=_fake_embedding()):
            await ret.search("test", max_results=3)

        args = pool.fetch.call_args[0]
        # $3 = max_results
        assert args[3] == 3

    async def test_threshold_passed_to_sql(self):
        ret, pool = _retriever(threshold=0.5)
        pool.fetch.return_value = []

        with patch.object(ret, "_generate_embedding", return_value=_fake_embedding()):
            await ret.search("test")

        args = pool.fetch.call_args[0]
        # $2 = threshold
        assert args[2] == 0.5

    async def test_url_strips_v1_suffix(self):
        ret = NotionRetriever(
            pool=AsyncMock(),
            ollama_base_url="http://localhost:11434/v1",
            model="nomic-embed-text",
        )
        assert ret._ollama_url == "http://localhost:11434"


# ---------- _generate_embedding ----------------------------------------------


class TestGenerateEmbedding:
    async def test_success(self):
        ret, _ = _retriever()
        fake_resp = MagicMock()
        fake_resp.json.return_value = {"embeddings": [_fake_embedding()]}
        fake_resp.raise_for_status = MagicMock()

        with patch("niles.actions.notion.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = fake_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await ret._generate_embedding("test")

        assert result == _fake_embedding()
        call_kwargs = mock_client.post.call_args
        assert "/api/embed" in call_kwargs[0][0]

    async def test_connection_error_returns_none(self):
        ret, _ = _retriever()

        with patch("niles.actions.notion.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.side_effect = httpx.ConnectError("refused")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await ret._generate_embedding("test")

        assert result is None
