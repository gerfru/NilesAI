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


def _setup_embed_pending(pool, pending_rows, breadcrumb_rows=None):
    """Set up pool.fetch side_effect for embed_pending.

    embed_pending calls pool.fetch twice:
    1. _build_breadcrumbs(): SELECT id, title, parent_id
    2. Main query: SELECT id, title, content_text
    """
    if breadcrumb_rows is None:
        # Auto-generate breadcrumb rows from pending rows
        breadcrumb_rows = [
            {"id": r["id"], "title": r["title"], "parent_id": None}
            for r in pending_rows
        ]
    pool.fetch.side_effect = [breadcrumb_rows, pending_rows]


# ---------- _chunk_text (pure function) --------------------------------------


class TestChunkText:
    def test_short_text_single_chunk(self):
        pipe, _, _ = _pipeline()
        chunks = pipe._chunk_text("Hello world", "Title")
        assert len(chunks) == 1
        assert chunks[0].text == "[Title] Hello world"
        assert chunks[0].page_title == "Title"
        assert chunks[0].heading_context == ""

    def test_empty_text(self):
        pipe, _, _ = _pipeline()
        assert pipe._chunk_text("", "Title") == []

    def test_whitespace_only(self):
        pipe, _, _ = _pipeline()
        assert pipe._chunk_text("   \n\n  ", "Title") == []

    def test_no_title(self):
        pipe, _, _ = _pipeline()
        chunks = pipe._chunk_text("Hello", "")
        assert chunks[0].text == "Hello"

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
            assert len(chunks[1].text) > 0

    def test_title_prefix_on_each_chunk(self):
        pipe, _, _ = _pipeline(chunk_size=30, chunk_overlap=0)
        text = "First paragraph.\nSecond paragraph."
        chunks = pipe._chunk_text(text, "Page")
        for chunk in chunks:
            assert chunk.text.startswith("[Page")

    def test_blank_paragraphs_skipped(self):
        pipe, _, _ = _pipeline()
        text = "Para 1\n\n\n\nPara 2"
        chunks = pipe._chunk_text(text, "")
        assert len(chunks) == 1
        assert "Para 1" in chunks[0].text
        assert "Para 2" in chunks[0].text

    def test_ascii_art_chunks_filtered(self):
        pipe, _, _ = _pipeline(chunk_size=200, chunk_overlap=0)
        # Simulate box-drawing diagram (mostly special chars)
        diagram = "┌──────────┐\n│  Box     │\n└──────────┘\n" * 5
        text = diagram + "\nSome real text paragraph here."
        chunks = pipe._chunk_text(text, "")
        # Real text chunks should survive, diagram-only chunks should be dropped
        for chunk in chunks:
            readable = sum(1 for c in chunk.text if c.isalnum() or c.isspace())
            assert (readable / len(chunk.text)) >= 0.4

    def test_normal_text_passes_filter(self):
        pipe, _, _ = _pipeline()
        text = "This is a perfectly normal paragraph with useful information."
        chunks = pipe._chunk_text(text, "Title")
        assert len(chunks) == 1

    def test_is_useful_chunk_raw_text(self):
        pipe, _, _ = _pipeline()
        # Garbage content (no title prefix — raw text)
        assert not pipe._is_useful_chunk("┌──┐│──│└──┘" * 3)
        # Real content
        assert pipe._is_useful_chunk("This is real text content")


# ---------- _split_by_headings -----------------------------------------------


class TestSplitByHeadings:
    def test_no_headings_returns_full_text(self):
        sections = NotionEmbeddingPipeline._split_by_headings(
            "Just some text\nAnother line"
        )
        assert len(sections) == 1
        assert sections[0][0] == ""  # No heading context
        assert "Just some text" in sections[0][1]

    def test_single_heading(self):
        text = "# Introduction\nSome intro text here."
        sections = NotionEmbeddingPipeline._split_by_headings(text)
        assert len(sections) == 1
        assert sections[0][0] == "# Introduction"
        assert "Some intro text here." in sections[0][1]

    def test_preamble_before_first_heading(self):
        text = "Preamble text\n# Section One\nBody of section."
        sections = NotionEmbeddingPipeline._split_by_headings(text)
        assert len(sections) == 2
        assert sections[0][0] == ""  # Preamble has no heading context
        assert "Preamble text" in sections[0][1]
        assert sections[1][0] == "# Section One"
        assert "Body of section." in sections[1][1]

    def test_heading_hierarchy(self):
        text = "# Main\nMain body\n## Sub\nSub body\n### Detail\nDetail body"
        sections = NotionEmbeddingPipeline._split_by_headings(text)
        # Should have 3 sections: Main, Sub, Detail
        assert len(sections) == 3
        assert sections[0][0] == "# Main"
        assert sections[1][0] == "# Main > ## Sub"
        assert sections[2][0] == "# Main > ## Sub > ### Detail"

    def test_sibling_headings_reset_deeper(self):
        text = "# A\nBody A\n## A1\nBody A1\n# B\nBody B\n## B1\nBody B1"
        sections = NotionEmbeddingPipeline._split_by_headings(text)
        assert len(sections) == 4
        assert sections[0][0] == "# A"
        assert sections[1][0] == "# A > ## A1"
        assert sections[2][0] == "# B"  # ## A1 is cleared
        assert sections[3][0] == "# B > ## B1"

    def test_empty_body_sections_skipped(self):
        text = "# Empty\n# Has Content\nSome text"
        sections = NotionEmbeddingPipeline._split_by_headings(text)
        # First heading has no body (next heading immediately follows)
        assert len(sections) == 1
        assert sections[0][0] == "# Has Content"

    def test_headings_inside_code_blocks_ignored(self):
        text = (
            "# Setup\nRun the following:\n"
            "```bash\n# install dependencies\napt install foo\n```\n"
            "# Usage\nStart the app."
        )
        sections = NotionEmbeddingPipeline._split_by_headings(text)
        # Only real headings (Setup, Usage), not the bash comment
        headings = [ctx for ctx, _ in sections]
        assert "# Setup" in headings
        assert "# Usage" in headings
        assert all("install" not in ctx for ctx in headings)

    def test_code_block_content_preserved_in_body(self):
        text = "# Setup\nIntro\n```python\n# comment\nprint('hi')\n```\nMore text."
        sections = NotionEmbeddingPipeline._split_by_headings(text)
        assert len(sections) == 1
        assert "print('hi')" in sections[0][1]
        assert "# comment" in sections[0][1]


# ---------- Heading-aware _chunk_text ----------------------------------------


class TestHeadingAwareChunking:
    def test_heading_provides_context_in_prefix(self):
        pipe, _, _ = _pipeline()
        text = "# Installation\nRun pip install niles."
        chunks = pipe._chunk_text(text, "Docs")
        assert len(chunks) == 1
        assert chunks[0].text.startswith("[Docs > # Installation]")
        assert "Run pip install niles." in chunks[0].text
        assert chunks[0].page_title == "Docs"
        assert chunks[0].heading_context == "# Installation"

    def test_multiple_sections_get_separate_chunks(self):
        pipe, _, _ = _pipeline(chunk_size=100, chunk_overlap=0)
        text = (
            "# Setup\nInstall the dependencies first.\n"
            "# Usage\nRun the main command to start."
        )
        chunks = pipe._chunk_text(text, "Guide")
        assert len(chunks) == 2
        assert "[Guide > # Setup]" in chunks[0].text
        assert "[Guide > # Usage]" in chunks[1].text

    def test_no_cross_section_overlap(self):
        pipe, _, _ = _pipeline(chunk_size=50, chunk_overlap=20)
        text = "# A\nShort section A.\n# B\nShort section B."
        chunks = pipe._chunk_text(text, "")
        # Section A content should not leak into Section B chunk
        for chunk in chunks:
            if "# B]" in chunk.text:
                assert "section A" not in chunk.text

    def test_fallback_without_headings(self):
        pipe, _, _ = _pipeline(chunk_size=50, chunk_overlap=0)
        text = "\n".join(f"Paragraph {i} with content." for i in range(5))
        chunks = pipe._chunk_text(text, "Page")
        # Without headings, all chunks get plain [Page] prefix
        for chunk in chunks:
            assert chunk.text.startswith("[Page] ")

    def test_nested_heading_hierarchy_in_prefix(self):
        pipe, _, _ = _pipeline()
        text = "# Main\n## Sub\nContent under sub."
        chunks = pipe._chunk_text(text, "Page")
        assert len(chunks) == 1
        assert chunks[0].text.startswith("[Page > # Main > ## Sub]")
        assert chunks[0].heading_context == "# Main > ## Sub"


# ---------- _build_breadcrumbs -----------------------------------------------


class TestBuildBreadcrumbs:
    async def test_single_page_no_parent(self):
        pipe, pool, _ = _pipeline()
        pool.fetch.return_value = [
            {"id": "p1", "title": "Root Page", "parent_id": None},
        ]
        bc = await pipe._build_breadcrumbs()
        assert bc["p1"] == "Root Page"

    async def test_child_with_parent(self):
        pipe, pool, _ = _pipeline()
        pool.fetch.return_value = [
            {"id": "parent1", "title": "Wiki", "parent_id": None},
            {"id": "child1", "title": "Setup Guide", "parent_id": "parent1"},
        ]
        bc = await pipe._build_breadcrumbs()
        assert bc["child1"] == "Wiki > Setup Guide"
        assert bc["parent1"] == "Wiki"

    async def test_max_depth_limits_ancestors(self):
        pipe, pool, _ = _pipeline()
        pool.fetch.return_value = [
            {"id": "g", "title": "Grandparent", "parent_id": None},
            {"id": "p", "title": "Parent", "parent_id": "g"},
            {"id": "c", "title": "Child", "parent_id": "p"},
        ]
        bc = await pipe._build_breadcrumbs()
        # Max depth is 2 ancestors, so Child gets Grandparent > Parent > Child
        assert bc["c"] == "Grandparent > Parent > Child"
        assert bc["p"] == "Grandparent > Parent"

    async def test_parent_not_in_db(self):
        pipe, pool, _ = _pipeline()
        pool.fetch.return_value = [
            {"id": "orphan", "title": "Orphan Page", "parent_id": "unknown_id"},
        ]
        bc = await pipe._build_breadcrumbs()
        # Parent not found → just the page title
        assert bc["orphan"] == "Orphan Page"


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
        pending = [{"id": "p1", "title": "Test", "content_text": "Hello world"}]
        _setup_embed_pending(pool, pending)
        pool.execute = AsyncMock()
        pool.fetchval = AsyncMock(return_value=0)
        embedder.embed.return_value = _fake_embedding()

        stats = await pipe.embed_pending()

        assert stats["pages_embedded"] == 1
        assert stats["chunks_created"] >= 1

        # Should delete old embeddings before inserting
        delete_call = pool.execute.call_args_list[0]
        assert "DELETE FROM notion_embeddings" in delete_call[0][0]

    async def test_no_pending_pages(self):
        pipe, pool, _ = _pipeline()
        _setup_embed_pending(pool, [])
        pool.fetchval = AsyncMock(return_value=0)

        stats = await pipe.embed_pending()

        assert stats["pages_embedded"] == 0
        assert stats["chunks_created"] == 0

    async def test_embedding_failure_counted(self):
        pipe, pool, embedder = _pipeline(chunk_size=2000)
        pending = [{"id": "p1", "title": "Test", "content_text": "Some content here"}]
        _setup_embed_pending(pool, pending)
        pool.execute = AsyncMock()
        pool.fetchval = AsyncMock(return_value=0)
        embedder.embed.return_value = None

        stats = await pipe.embed_pending()

        assert stats["errors"] >= 1
        assert stats["chunks_created"] == 0

    async def test_partial_failure_skips_embedded_at(self):
        """Fix #1: page not marked as embedded when some chunks fail."""
        pipe, pool, embedder = _pipeline(chunk_size=20, chunk_overlap=0)
        pending = [
            {"id": "p1", "title": "", "content_text": "First chunk.\nSecond chunk."}
        ]
        _setup_embed_pending(pool, pending)
        pool.execute = AsyncMock()
        pool.fetchval = AsyncMock(return_value=0)
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
        pending = [{"id": "p1", "title": "Empty", "content_text": "   "}]
        _setup_embed_pending(pool, pending)
        pool.fetchval = AsyncMock(return_value=0)

        stats = await pipe.embed_pending()

        # _chunk_text returns [] for whitespace, so page is skipped
        assert stats["pages_embedded"] == 0

    async def test_marks_page_embedded(self):
        pipe, pool, embedder = _pipeline(chunk_size=2000)
        pending = [{"id": "p1", "title": "Test", "content_text": "Content here"}]
        _setup_embed_pending(pool, pending)
        pool.execute = AsyncMock()
        pool.fetchval = AsyncMock(return_value=0)
        embedder.embed.return_value = _fake_embedding()

        await pipe.embed_pending()

        # Last execute call should update embedded_at
        last_call = pool.execute.call_args_list[-1]
        assert "embedded_at" in last_call[0][0]

    async def test_embed_uses_document_prefix(self):
        pipe, pool, embedder = _pipeline(chunk_size=2000)
        pending = [{"id": "p1", "title": "Test", "content_text": "Content here"}]
        _setup_embed_pending(pool, pending)
        pool.execute = AsyncMock()
        pool.fetchval = AsyncMock(return_value=0)
        embedder.embed.return_value = _fake_embedding()

        await pipe.embed_pending()

        # embed() should be called with search_document prefix
        embedder.embed.assert_called_once_with(
            "[Test] Content here", prefix="search_document: "
        )

    async def test_insert_uses_chunk_level_detail(self):
        """Detail chunks are inserted with chunk_level=1."""
        pipe, pool, embedder = _pipeline(chunk_size=2000)
        pending = [{"id": "p1", "title": "Test", "content_text": "Content here"}]
        _setup_embed_pending(pool, pending)
        pool.execute = AsyncMock()
        pool.fetchval = AsyncMock(return_value=0)
        embedder.embed.return_value = _fake_embedding()

        await pipe.embed_pending()

        # Find INSERT calls
        insert_calls = [c for c in pool.execute.call_args_list if "INSERT" in c[0][0]]
        assert len(insert_calls) == 1
        # $2 = chunk_level (LEVEL_DETAIL = 1)
        assert insert_calls[0][0][2] == LEVEL_DETAIL

    async def test_insert_includes_metadata_columns(self):
        """Detail INSERT passes page_title and heading_context as $6, $7."""
        pipe, pool, embedder = _pipeline(chunk_size=2000)
        pending = [
            {
                "id": "p1",
                "title": "My Page",
                "content_text": "# Setup\nInstall steps.",
            }
        ]
        _setup_embed_pending(pool, pending)
        pool.execute = AsyncMock()
        pool.fetchval = AsyncMock(return_value=0)
        embedder.embed.return_value = _fake_embedding()

        await pipe.embed_pending()

        insert_calls = [c for c in pool.execute.call_args_list if "INSERT" in c[0][0]]
        assert len(insert_calls) == 1
        # $6 = page_title (breadcrumb), $7 = heading_context
        assert insert_calls[0][0][6] == "My Page"
        assert insert_calls[0][0][7] == "# Setup"

    async def test_no_summarizer_skips_summaries(self):
        """Without summarizer, only detail chunks are generated."""
        pipe, pool, embedder = _pipeline(chunk_size=2000)
        pending = [{"id": "p1", "title": "Test", "content_text": "A" * 200}]
        _setup_embed_pending(pool, pending)
        pool.execute = AsyncMock()
        pool.fetchval = AsyncMock(return_value=0)
        embedder.embed.return_value = _fake_embedding()

        stats = await pipe.embed_pending()

        assert stats["summaries_created"] == 0
        assert stats["chunks_created"] >= 1

    async def test_breadcrumb_used_in_chunk_prefix(self):
        """Chunks use breadcrumb (parent > page) instead of just title."""
        pipe, pool, embedder = _pipeline(chunk_size=2000)
        pending = [{"id": "c1", "title": "Setup", "content_text": "Install steps."}]
        breadcrumb_rows = [
            {"id": "p1", "title": "Wiki", "parent_id": None},
            {"id": "c1", "title": "Setup", "parent_id": "p1"},
        ]
        _setup_embed_pending(pool, pending, breadcrumb_rows=breadcrumb_rows)
        pool.execute = AsyncMock()
        pool.fetchval = AsyncMock(return_value=0)
        embedder.embed.return_value = _fake_embedding()

        await pipe.embed_pending()

        # Chunk text should contain breadcrumb prefix
        embedder.embed.assert_called_once()
        chunk_text = embedder.embed.call_args[0][0]
        assert chunk_text.startswith("[Wiki > Setup]")


# ---------- embed_pending (with summarizer) -----------------------------------


class TestEmbedPendingWithSummarizer:
    async def test_summary_generated_and_inserted(self):
        """Summarizer produces text -> level-0 INSERT + level-1 detail chunks."""
        summarizer = AsyncMock(spec=NotionSummarizer)
        summarizer.summarize.return_value = "This page is about testing."
        pipe, pool, embedder = _pipeline(chunk_size=2000, summarizer=summarizer)
        pending = [{"id": "p1", "title": "Test", "content_text": "A" * 200}]
        _setup_embed_pending(pool, pending)
        pool.execute = AsyncMock()
        pool.fetchval = AsyncMock(return_value=0)
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

    async def test_summary_failure_does_not_block_page(self):
        """If summary generation fails, page is still marked as embedded."""
        summarizer = AsyncMock(spec=NotionSummarizer)
        summarizer.summarize.return_value = None  # Failure
        pipe, pool, embedder = _pipeline(chunk_size=2000, summarizer=summarizer)
        pending = [{"id": "p1", "title": "Test", "content_text": "A" * 200}]
        _setup_embed_pending(pool, pending)
        pool.execute = AsyncMock()
        pool.fetchval = AsyncMock(return_value=0)
        embedder.embed.return_value = _fake_embedding()

        stats = await pipe.embed_pending()

        assert stats["summaries_failed"] == 1
        assert stats["pages_embedded"] == 1
        # Detail chunks should still be created
        assert stats["chunks_created"] >= 1

    async def test_summary_embedding_failure_does_not_block_page(self):
        """If summary text is generated but embedding fails, page still marked."""
        summarizer = AsyncMock(spec=NotionSummarizer)
        summarizer.summarize.return_value = "A summary."
        pipe, pool, embedder = _pipeline(chunk_size=2000, summarizer=summarizer)
        pending = [{"id": "p1", "title": "Test", "content_text": "A" * 200}]
        _setup_embed_pending(pool, pending)
        pool.execute = AsyncMock()
        pool.fetchval = AsyncMock(return_value=0)
        # First call (summary embed) fails, rest succeed
        embedder.embed.side_effect = [None, _fake_embedding()]

        stats = await pipe.embed_pending()

        assert stats["summaries_created"] == 0
        assert stats["summaries_failed"] == 1
        assert stats["pages_embedded"] == 1

    async def test_short_content_no_summary(self):
        """Content < 100 chars: no summary attempt even with summarizer."""
        summarizer = AsyncMock(spec=NotionSummarizer)
        pipe, pool, embedder = _pipeline(chunk_size=2000, summarizer=summarizer)
        pending = [{"id": "p1", "title": "Short", "content_text": "Brief note."}]
        _setup_embed_pending(pool, pending)
        pool.execute = AsyncMock()
        pool.fetchval = AsyncMock(return_value=0)
        embedder.embed.return_value = _fake_embedding()

        stats = await pipe.embed_pending()

        summarizer.summarize.assert_not_called()
        assert stats["summaries_created"] == 0
        assert stats["chunks_created"] == 1
        assert stats["pages_embedded"] == 1

    async def test_summary_insert_includes_metadata(self):
        """Summary INSERT passes breadcrumb as page_title, empty heading_context."""
        summarizer = AsyncMock(spec=NotionSummarizer)
        summarizer.summarize.return_value = "A summary."
        pipe, pool, embedder = _pipeline(chunk_size=2000, summarizer=summarizer)
        pending = [{"id": "p1", "title": "Test", "content_text": "A" * 200}]
        _setup_embed_pending(pool, pending)
        pool.execute = AsyncMock()
        pool.fetchval = AsyncMock(return_value=0)
        embedder.embed.return_value = _fake_embedding()

        await pipe.embed_pending()

        insert_calls = [c for c in pool.execute.call_args_list if "INSERT" in c[0][0]]
        summary_insert = insert_calls[0]
        # $6 = page_title (breadcrumb), $7 = heading_context (empty for summaries)
        assert summary_insert[0][6] == "Test"
        assert summary_insert[0][7] == ""

    async def test_summary_has_breadcrumb_prefix(self):
        """Summary text includes [Breadcrumb] prefix."""
        summarizer = AsyncMock(spec=NotionSummarizer)
        summarizer.summarize.return_value = "A summary of the page."
        pipe, pool, embedder = _pipeline(chunk_size=2000, summarizer=summarizer)
        pending = [{"id": "c1", "title": "My Page", "content_text": "A" * 200}]
        breadcrumb_rows = [
            {"id": "p1", "title": "Wiki", "parent_id": None},
            {"id": "c1", "title": "My Page", "parent_id": "p1"},
        ]
        _setup_embed_pending(pool, pending, breadcrumb_rows=breadcrumb_rows)
        pool.execute = AsyncMock()
        pool.fetchval = AsyncMock(return_value=0)
        embedder.embed.return_value = _fake_embedding()

        await pipe.embed_pending()

        insert_calls = [c for c in pool.execute.call_args_list if "INSERT" in c[0][0]]
        summary_text = insert_calls[0][0][4]  # $4 = chunk_text
        assert summary_text.startswith("[Wiki > My Page] ")


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
