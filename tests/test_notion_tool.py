"""Tests for search_notion agent tool (agent/tools/notion.py)."""

from unittest.mock import AsyncMock, MagicMock

from niles.agent.tools.notion import handle_search_notion


# ---------- Helpers ----------------------------------------------------------


def _ctx(retriever=None):
    """Build a minimal ToolContext-like object."""
    ctx = MagicMock()
    ctx.notion_retriever = retriever
    return ctx


# ---------- Tests ------------------------------------------------------------


class TestSearchNotionTool:
    async def test_success(self):
        retriever = AsyncMock()
        retriever.search.return_value = [
            {
                "chunk_text": "Niles is an AI butler.",
                "page_title": "About",
                "page_url": "https://notion.so/about",
                "similarity": 0.85,
            },
        ]
        ctx = _ctx(retriever)

        result = await handle_search_notion({"query": "What is Niles?"}, "test-chat", ctx)

        assert len(result["results"]) == 1
        assert result["results"][0]["source"] == "About"
        assert result["results"][0]["url"] == "https://notion.so/about"
        assert "1 relevante" in result["message"]

    async def test_no_retriever(self):
        ctx = _ctx(retriever=None)

        result = await handle_search_notion({"query": "test"}, "test-chat", ctx)

        assert "error" in result
        assert "nicht konfiguriert" in result["error"]

    async def test_empty_query_rejected(self):
        retriever = AsyncMock()
        ctx = _ctx(retriever)

        result = await handle_search_notion({"query": "  "}, "test-chat", ctx)

        assert "error" in result
        retriever.search.assert_not_called()

    async def test_no_results(self):
        retriever = AsyncMock()
        retriever.search.return_value = []
        ctx = _ctx(retriever)

        result = await handle_search_notion({"query": "unknown"}, "test-chat", ctx)

        assert result["results"] == []
        assert "Keine" in result["message"]

    async def test_max_results_capped_at_10(self):
        retriever = AsyncMock()
        retriever.search.return_value = []
        ctx = _ctx(retriever)

        await handle_search_notion({"query": "test", "max_results": 50}, "test-chat", ctx)

        retriever.search.assert_called_once_with("test", max_results=10)

    async def test_default_max_results(self):
        retriever = AsyncMock()
        retriever.search.return_value = []
        ctx = _ctx(retriever)

        await handle_search_notion({"query": "test"}, "test-chat", ctx)

        retriever.search.assert_called_once_with("test", max_results=5)

    async def test_result_format(self):
        retriever = AsyncMock()
        retriever.search.return_value = [
            {
                "chunk_text": "Content here.",
                "page_title": "Page Title",
                "page_url": "https://notion.so/page",
                "similarity": 0.92,
            },
        ]
        ctx = _ctx(retriever)

        result = await handle_search_notion({"query": "test"}, "test-chat", ctx)

        item = result["results"][0]
        assert item["source"] == "Page Title"
        assert item["url"] == "https://notion.so/page"
        # Indexed content is isolated as untrusted external data (indirect injection)
        assert '<untrusted_external_content source="notion">' in item["content"]
        assert "Content here." in item["content"]
        assert item["relevance"] == 0.92
