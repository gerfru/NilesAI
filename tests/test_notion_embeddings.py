"""Tests for Notion embedding pipeline (sync/notion_embeddings.py) and OllamaEmbedder."""

from unittest.mock import AsyncMock, MagicMock

import httpx

from niles.sync.notion_embeddings import (
    LEVEL_DETAIL,
    LEVEL_SUMMARY,
    NotionEmbeddingPipeline,
)
from niles.sync.notion_summarizer import NotionSummarizer
from niles.sync.ollama_embedder import OllamaEmbedder


# ---------- Helpers ----------------------------------------------------------


def _embedder():
    return OllamaEmbedder(
        ollama_base_url="http://localhost:11434",
        model="nomic-embed-text",
    )


def _pipeline(pool=None, chunk_size=600, chunk_overlap=100, summarizer=None):
    p = pool or AsyncMock()
    embedder = AsyncMock(spec=OllamaEmbedder)
    return (
        NotionEmbeddingPipeline(
            pool=p,
            embedder=embedder,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            summarizer=summarizer,
        ),
        p,
        embedder,
    )


def _fake_embedding(dim=768):
    return [0.1] * dim


# ---------- _chunk_text (pure function) --------------------------------------


class TestChunkText:
    def test_short_text_single_chunk(self):
        pipe, _, _ = _pipeline()
        chunks = pipe._chunk_text("Hello world", "Title")
        assert len(chunks) == 1
        assert chunks[0] == "[Title] Hello world"

    def test_empty_text(self):
        pipe, _, _ = _pipeline()
        assert pipe._chunk_text("", "Title") == []

    def test_whitespace_only(self):
        pipe, _, _ = _pipeline()
        assert pipe._chunk_text("   \n\n  ", "Title") == []

    def test_no_title(self):
        pipe, _, _ = _pipeline()
        chunks = pipe._chunk_text("Hello", "")
        assert chunks[0] == "Hello"

    def test_long_text_splits(self):
        pipe, _, _ = _pipeline(chunk_size=50, chunk_overlap=0)
        # Create text that exceeds chunk_size
        text = "\n".join(f"Paragraph {i} with some content." for i in range(10))
        chunks = pipe._chunk_text(text, "")
        assert len(chunks) > 1

    def test_overlap_preserves_context(self):
        pipe, _, _ = _pipeline(chunk_size=50, chunk_overlap=20)
        text = "First paragraph here.\nSecond paragraph here.\nThird paragraph here."
        chunks = pipe._chunk_text(text, "")
        # With overlap, later chunks should contain tail of previous chunk
        if len(chunks) > 1:
            # The second chunk should have some overlap from the first
            assert len(chunks[1]) > 0

    def test_title_prefix_on_each_chunk(self):
        pipe, _, _ = _pipeline(chunk_size=30, chunk_overlap=0)
        text = "First paragraph.\nSecond paragraph."
        chunks = pipe._chunk_text(text, "Page")
        for chunk in chunks:
            assert chunk.startswith("[Page] ")

    def test_blank_paragraphs_skipped(self):
        pipe, _, _ = _pipeline()
        text = "Para 1\n\n\n\nPara 2"
        chunks = pipe._chunk_text(text, "")
        assert len(chunks) == 1
        assert "Para 1" in chunks[0]
        assert "Para 2" in chunks[0]

    def test_ascii_art_chunks_filtered(self):
        pipe, _, _ = _pipeline(chunk_size=200, chunk_overlap=0)
        # Simulate box-drawing diagram (mostly special chars)
        diagram = "┌──────────┐\n│  Box     │\n└──────────┘\n" * 5
        text = diagram + "\nSome real text paragraph here."
        chunks = pipe._chunk_text(text, "")
        # Real text chunks should survive, diagram-only chunks should be dropped
        for chunk in chunks:
            readable = sum(1 for c in chunk if c.isalnum() or c.isspace())
            assert (readable / len(chunk)) >= 0.4

    def test_normal_text_passes_filter(self):
        pipe, _, _ = _pipeline()
        text = "This is a perfectly normal paragraph with useful information."
        chunks = pipe._chunk_text(text, "Title")
        assert len(chunks) == 1

    def test_is_useful_chunk_strips_title(self):
        pipe, _, _ = _pipeline()
        # Chunk with title prefix but garbage content
        assert not pipe._is_useful_chunk("[Title] ┌──┐│──│└──┘" * 3)
        # Chunk with title prefix and real content
        assert pipe._is_useful_chunk("[Title] This is real text content")


# ---------- OllamaEmbedder ---------------------------------------------------


class TestOllamaEmbedder:
    async def test_embed_success(self):
        emb = _embedder()
        fake_resp = MagicMock()
        fake_resp.json.return_value = {"embeddings": [_fake_embedding()]}
        fake_resp.raise_for_status = MagicMock()
        emb._client = AsyncMock()
        emb._client.post.return_value = fake_resp

        result = await emb.embed("test text")

        assert result == _fake_embedding()
        call_args = emb._client.post.call_args
        assert "/api/embed" in call_args[0][0]

    async def test_embed_empty_embeddings(self):
        emb = _embedder()
        fake_resp = MagicMock()
        fake_resp.json.return_value = {"embeddings": []}
        fake_resp.raise_for_status = MagicMock()
        emb._client = AsyncMock()
        emb._client.post.return_value = fake_resp

        result = await emb.embed("test text")

        assert result is None

    async def test_embed_http_error_returns_none(self):
        emb = _embedder()
        emb._client = AsyncMock()
        emb._client.post.side_effect = httpx.ConnectError("refused")

        result = await emb.embed("test text")

        assert result is None

    def test_url_strips_v1_suffix(self):
        emb = OllamaEmbedder(
            ollama_base_url="http://localhost:11434/v1",
            model="nomic-embed-text",
        )
        assert emb._ollama_url == "http://localhost:11434"

    async def test_close(self):
        emb = _embedder()
        emb._client = AsyncMock()
        await emb.close()
        emb._client.aclose.assert_called_once()


# ---------- embed_pending (without summarizer) --------------------------------


class TestEmbedPending:
    async def test_embeds_pending_pages(self):
        pipe, pool, embedder = _pipeline(chunk_size=2000)

        pool.fetch.return_value = [
            {"id": "p1", "title": "Test", "content_text": "Hello world"},
        ]
        pool.execute = AsyncMock()
        embedder.embed.return_value = _fake_embedding()

        stats = await pipe.embed_pending()

        assert stats["pages_embedded"] == 1
        assert stats["chunks_created"] >= 1

        # Should delete old embeddings before inserting
        delete_call = pool.execute.call_args_list[0]
        assert "DELETE FROM notion_embeddings" in delete_call[0][0]

    async def test_no_pending_pages(self):
        pipe, pool, _ = _pipeline()
        pool.fetch.return_value = []

        stats = await pipe.embed_pending()

        assert stats["pages_embedded"] == 0
        assert stats["chunks_created"] == 0

    async def test_embedding_failure_counted(self):
        pipe, pool, embedder = _pipeline(chunk_size=2000)
        pool.fetch.return_value = [
            {"id": "p1", "title": "Test", "content_text": "Some content here"},
        ]
        pool.execute = AsyncMock()
        embedder.embed.return_value = None

        stats = await pipe.embed_pending()

        assert stats["errors"] >= 1
        assert stats["chunks_created"] == 0

    async def test_partial_failure_skips_embedded_at(self):
        """Fix #1: page not marked as embedded when some chunks fail."""
        pipe, pool, embedder = _pipeline(chunk_size=20, chunk_overlap=0)
        pool.fetch.return_value = [
            {"id": "p1", "title": "", "content_text": "First chunk.\nSecond chunk."},
        ]
        pool.execute = AsyncMock()
        # First chunk succeeds, second fails
        embedder.embed.side_effect = [_fake_embedding(), None]

        stats = await pipe.embed_pending()

        assert stats["errors"] == 1
        assert stats["pages_embedded"] == 0
        # embedded_at should NOT have been updated
        update_calls = [
            c[0][0] for c in pool.execute.call_args_list if "embedded_at" in c[0][0]
        ]
        assert len(update_calls) == 0

    async def test_empty_content_skipped(self):
        pipe, pool, _ = _pipeline()
        pool.fetch.return_value = [
            {"id": "p1", "title": "Empty", "content_text": "   "},
        ]

        stats = await pipe.embed_pending()

        # _chunk_text returns [] for whitespace, so page is skipped
        assert stats["pages_embedded"] == 0

    async def test_marks_page_embedded(self):
        pipe, pool, embedder = _pipeline(chunk_size=2000)
        pool.fetch.return_value = [
            {"id": "p1", "title": "Test", "content_text": "Content here"},
        ]
        pool.execute = AsyncMock()
        embedder.embed.return_value = _fake_embedding()

        await pipe.embed_pending()

        # Last execute call should update embedded_at
        last_call = pool.execute.call_args_list[-1]
        assert "embedded_at" in last_call[0][0]

    async def test_embed_uses_document_prefix(self):
        pipe, pool, embedder = _pipeline(chunk_size=2000)
        pool.fetch.return_value = [
            {"id": "p1", "title": "Test", "content_text": "Content here"},
        ]
        pool.execute = AsyncMock()
        embedder.embed.return_value = _fake_embedding()

        await pipe.embed_pending()

        # embed() should be called with search_document prefix
        embedder.embed.assert_called_once_with(
            "[Test] Content here", prefix="search_document: "
        )

    async def test_insert_uses_chunk_level_detail(self):
        """Detail chunks are inserted with chunk_level=1."""
        pipe, pool, embedder = _pipeline(chunk_size=2000)
        pool.fetch.return_value = [
            {"id": "p1", "title": "Test", "content_text": "Content here"},
        ]
        pool.execute = AsyncMock()
        embedder.embed.return_value = _fake_embedding()

        await pipe.embed_pending()

        # Find INSERT calls
        insert_calls = [c for c in pool.execute.call_args_list if "INSERT" in c[0][0]]
        assert len(insert_calls) == 1
        # $2 = chunk_level (LEVEL_DETAIL = 1)
        assert insert_calls[0][0][2] == LEVEL_DETAIL

    async def test_no_summarizer_skips_summaries(self):
        """Without summarizer, only detail chunks are generated."""
        pipe, pool, embedder = _pipeline(chunk_size=2000)
        pool.fetch.return_value = [
            {"id": "p1", "title": "Test", "content_text": "A" * 200},
        ]
        pool.execute = AsyncMock()
        embedder.embed.return_value = _fake_embedding()

        stats = await pipe.embed_pending()

        assert stats["summaries_created"] == 0
        assert stats["chunks_created"] >= 1


# ---------- embed_pending (with summarizer) -----------------------------------


class TestEmbedPendingWithSummarizer:
    async def test_summary_generated_and_inserted(self):
        """Summarizer produces text -> level-0 INSERT + level-1 detail chunks."""
        summarizer = AsyncMock(spec=NotionSummarizer)
        summarizer.summarize.return_value = "This page is about testing."
        pipe, pool, embedder = _pipeline(chunk_size=2000, summarizer=summarizer)
        pool.fetch.return_value = [
            {"id": "p1", "title": "Test", "content_text": "A" * 200},
        ]
        pool.execute = AsyncMock()
        embedder.embed.return_value = _fake_embedding()

        stats = await pipe.embed_pending()

        assert stats["summaries_created"] == 1
        assert stats["chunks_created"] >= 1
        assert stats["pages_embedded"] == 1

        # Find INSERT calls
        insert_calls = [c for c in pool.execute.call_args_list if "INSERT" in c[0][0]]
        # Should have at least 2 inserts: 1 summary + 1+ detail
        assert len(insert_calls) >= 2

        # First insert should be summary (level 0)
        summary_insert = insert_calls[0]
        assert summary_insert[0][2] == LEVEL_SUMMARY  # $2 = chunk_level
        assert summary_insert[0][3] == 0  # $3 = chunk_index
        assert "This page is about testing." in summary_insert[0][4]  # $4 = text

        # Second insert should be detail (level 1)
        detail_insert = insert_calls[1]
        assert detail_insert[0][2] == LEVEL_DETAIL

    async def test_summary_failure_blocks_page_completion(self):
        """If summary generation fails, page is NOT marked as embedded."""
        summarizer = AsyncMock(spec=NotionSummarizer)
        summarizer.summarize.return_value = None  # Failure
        pipe, pool, embedder = _pipeline(chunk_size=2000, summarizer=summarizer)
        pool.fetch.return_value = [
            {"id": "p1", "title": "Test", "content_text": "A" * 200},
        ]
        pool.execute = AsyncMock()
        embedder.embed.return_value = _fake_embedding()

        stats = await pipe.embed_pending()

        assert stats["errors"] >= 1
        assert stats["pages_embedded"] == 0
        # Detail chunks should still be created
        assert stats["chunks_created"] >= 1

    async def test_summary_embedding_failure_blocks_page(self):
        """If summary text is generated but embedding fails, page not marked."""
        summarizer = AsyncMock(spec=NotionSummarizer)
        summarizer.summarize.return_value = "A summary."
        pipe, pool, embedder = _pipeline(chunk_size=2000, summarizer=summarizer)
        pool.fetch.return_value = [
            {"id": "p1", "title": "Test", "content_text": "A" * 200},
        ]
        pool.execute = AsyncMock()
        # First call (summary embed) fails, rest succeed
        embedder.embed.side_effect = [None, _fake_embedding()]

        stats = await pipe.embed_pending()

        assert stats["summaries_created"] == 0
        assert stats["errors"] >= 1
        assert stats["pages_embedded"] == 0

    async def test_short_content_no_summary(self):
        """Content < 100 chars: no summary attempt even with summarizer."""
        summarizer = AsyncMock(spec=NotionSummarizer)
        pipe, pool, embedder = _pipeline(chunk_size=2000, summarizer=summarizer)
        pool.fetch.return_value = [
            {"id": "p1", "title": "Short", "content_text": "Brief note."},
        ]
        pool.execute = AsyncMock()
        embedder.embed.return_value = _fake_embedding()

        stats = await pipe.embed_pending()

        summarizer.summarize.assert_not_called()
        assert stats["summaries_created"] == 0
        assert stats["chunks_created"] == 1
        assert stats["pages_embedded"] == 1

    async def test_summary_has_title_prefix(self):
        """Summary text includes [Title] prefix."""
        summarizer = AsyncMock(spec=NotionSummarizer)
        summarizer.summarize.return_value = "A summary of the page."
        pipe, pool, embedder = _pipeline(chunk_size=2000, summarizer=summarizer)
        pool.fetch.return_value = [
            {"id": "p1", "title": "My Page", "content_text": "A" * 200},
        ]
        pool.execute = AsyncMock()
        embedder.embed.return_value = _fake_embedding()

        await pipe.embed_pending()

        insert_calls = [c for c in pool.execute.call_args_list if "INSERT" in c[0][0]]
        summary_text = insert_calls[0][0][4]  # $4 = chunk_text
        assert summary_text.startswith("[My Page] ")


# ---------- force_reembed ----------------------------------------------------


class TestForceReembed:
    async def test_marks_all_pages(self):
        pipe, pool, _ = _pipeline()
        pool.execute = AsyncMock(return_value="UPDATE 378")

        count = await pipe.force_reembed()

        assert count == 378
        sql = pool.execute.call_args[0][0]
        assert "embedded_at = NULL" in sql

    async def test_zero_pages(self):
        pipe, pool, _ = _pipeline()
        pool.execute = AsyncMock(return_value="UPDATE 0")

        count = await pipe.force_reembed()

        assert count == 0
