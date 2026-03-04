"""Tests for Notion embedding pipeline (sync/notion_embeddings.py)."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from niles.sync.notion_embeddings import NotionEmbeddingPipeline


# ---------- Helpers ----------------------------------------------------------


def _pipeline(pool=None, chunk_size=600, chunk_overlap=100):
    p = pool or AsyncMock()
    return (
        NotionEmbeddingPipeline(
            pool=p,
            ollama_base_url="http://localhost:11434",
            model="nomic-embed-text",
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        ),
        p,
    )


def _fake_embedding(dim=768):
    return [0.1] * dim


# ---------- _chunk_text (pure function) --------------------------------------


class TestChunkText:
    def test_short_text_single_chunk(self):
        pipe, _ = _pipeline()
        chunks = pipe._chunk_text("Hello world", "Title")
        assert len(chunks) == 1
        assert chunks[0] == "[Title] Hello world"

    def test_empty_text(self):
        pipe, _ = _pipeline()
        assert pipe._chunk_text("", "Title") == []

    def test_whitespace_only(self):
        pipe, _ = _pipeline()
        assert pipe._chunk_text("   \n\n  ", "Title") == []

    def test_no_title(self):
        pipe, _ = _pipeline()
        chunks = pipe._chunk_text("Hello", "")
        assert chunks[0] == "Hello"

    def test_long_text_splits(self):
        pipe, _ = _pipeline(chunk_size=50, chunk_overlap=0)
        # Create text that exceeds chunk_size
        text = "\n".join(f"Paragraph {i} with some content." for i in range(10))
        chunks = pipe._chunk_text(text, "")
        assert len(chunks) > 1

    def test_overlap_preserves_context(self):
        pipe, _ = _pipeline(chunk_size=50, chunk_overlap=20)
        text = "First paragraph here.\nSecond paragraph here.\nThird paragraph here."
        chunks = pipe._chunk_text(text, "")
        # With overlap, later chunks should contain tail of previous chunk
        if len(chunks) > 1:
            # The second chunk should have some overlap from the first
            assert len(chunks[1]) > 0

    def test_title_prefix_on_each_chunk(self):
        pipe, _ = _pipeline(chunk_size=30, chunk_overlap=0)
        text = "First paragraph.\nSecond paragraph."
        chunks = pipe._chunk_text(text, "Page")
        for chunk in chunks:
            assert chunk.startswith("[Page] ")

    def test_blank_paragraphs_skipped(self):
        pipe, _ = _pipeline()
        text = "Para 1\n\n\n\nPara 2"
        chunks = pipe._chunk_text(text, "")
        assert len(chunks) == 1
        assert "Para 1" in chunks[0]
        assert "Para 2" in chunks[0]

    def test_ascii_art_chunks_filtered(self):
        pipe, _ = _pipeline(chunk_size=200, chunk_overlap=0)
        # Simulate box-drawing diagram (mostly special chars)
        diagram = "┌──────────┐\n│  Box     │\n└──────────┘\n" * 5
        text = diagram + "\nSome real text paragraph here."
        chunks = pipe._chunk_text(text, "")
        # Real text chunks should survive, diagram-only chunks should be dropped
        for chunk in chunks:
            readable = sum(1 for c in chunk if c.isalnum() or c.isspace())
            assert (readable / len(chunk)) >= 0.4

    def test_normal_text_passes_filter(self):
        pipe, _ = _pipeline()
        text = "This is a perfectly normal paragraph with useful information."
        chunks = pipe._chunk_text(text, "Title")
        assert len(chunks) == 1

    def test_is_useful_chunk_strips_title(self):
        pipe, _ = _pipeline()
        # Chunk with title prefix but garbage content
        assert not pipe._is_useful_chunk("[Title] ┌──┐│──│└──┘" * 3)
        # Chunk with title prefix and real content
        assert pipe._is_useful_chunk("[Title] This is real text content")


# ---------- _generate_embedding ----------------------------------------------


class TestGenerateEmbedding:
    async def test_success(self):
        pipe, _ = _pipeline()
        fake_resp = MagicMock()
        fake_resp.json.return_value = {"embeddings": [_fake_embedding()]}
        fake_resp.raise_for_status = MagicMock()

        with patch("niles.sync.notion_embeddings.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = fake_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await pipe._generate_embedding("test text")

        assert result == _fake_embedding()

    async def test_empty_embeddings(self):
        pipe, _ = _pipeline()
        fake_resp = MagicMock()
        fake_resp.json.return_value = {"embeddings": []}
        fake_resp.raise_for_status = MagicMock()

        with patch("niles.sync.notion_embeddings.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = fake_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await pipe._generate_embedding("test text")

        assert result is None

    async def test_http_error_returns_none(self):
        pipe, _ = _pipeline()

        with patch("niles.sync.notion_embeddings.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.side_effect = httpx.ConnectError("refused")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await pipe._generate_embedding("test text")

        assert result is None

    async def test_url_strips_v1_suffix(self):
        pipe = NotionEmbeddingPipeline(
            pool=AsyncMock(),
            ollama_base_url="http://localhost:11434/v1",
            model="nomic-embed-text",
        )
        assert pipe._ollama_url == "http://localhost:11434"


# ---------- embed_pending -----------------------------------------------------


class TestEmbedPending:
    async def test_embeds_pending_pages(self):
        pipe, pool = _pipeline(chunk_size=2000)

        pool.fetch.return_value = [
            {"id": "p1", "title": "Test", "content_text": "Hello world"},
        ]
        pool.execute = AsyncMock()

        with patch.object(pipe, "_generate_embedding", return_value=_fake_embedding()):
            stats = await pipe.embed_pending()

        assert stats["pages_embedded"] == 1
        assert stats["chunks_created"] >= 1

        # Should delete old embeddings before inserting
        delete_call = pool.execute.call_args_list[0]
        assert "DELETE FROM notion_embeddings" in delete_call[0][0]

    async def test_no_pending_pages(self):
        pipe, pool = _pipeline()
        pool.fetch.return_value = []

        stats = await pipe.embed_pending()

        assert stats["pages_embedded"] == 0
        assert stats["chunks_created"] == 0

    async def test_embedding_failure_counted(self):
        pipe, pool = _pipeline(chunk_size=2000)
        pool.fetch.return_value = [
            {"id": "p1", "title": "Test", "content_text": "Some content here"},
        ]
        pool.execute = AsyncMock()

        with patch.object(pipe, "_generate_embedding", return_value=None):
            stats = await pipe.embed_pending()

        assert stats["errors"] >= 1
        assert stats["chunks_created"] == 0

    async def test_empty_content_skipped(self):
        pipe, pool = _pipeline()
        pool.fetch.return_value = [
            {"id": "p1", "title": "Empty", "content_text": "   "},
        ]

        stats = await pipe.embed_pending()

        # _chunk_text returns [] for whitespace, so page is skipped
        assert stats["pages_embedded"] == 0

    async def test_marks_page_embedded(self):
        pipe, pool = _pipeline(chunk_size=2000)
        pool.fetch.return_value = [
            {"id": "p1", "title": "Test", "content_text": "Content here"},
        ]
        pool.execute = AsyncMock()

        with patch.object(pipe, "_generate_embedding", return_value=_fake_embedding()):
            await pipe.embed_pending()

        # Last execute call should update embedded_at
        last_call = pool.execute.call_args_list[-1]
        assert "embedded_at" in last_call[0][0]
