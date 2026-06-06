"""Tests for the SearXNG Web Search MCP server module."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from niles.mcp.search.server import _get_config, web_search

# --- Sample API response ---

_SAMPLE_RESULTS = {
    "query": "test query",
    "number_of_results": 100,
    "results": [
        {
            "title": "First Result",
            "url": "https://example.com/1",
            "content": "This is the first result content.",
            "engine": "google",
            "score": 1.5,
        },
        {
            "title": "Second Result",
            "url": "https://example.com/2",
            "content": "This is the second result content.",
            "engine": "bing",
            "score": 1.2,
        },
        {
            "title": "Third Result",
            "url": "https://example.com/3",
            "content": "Third result.",
            "engine": "duckduckgo",
            "score": 0.8,
        },
    ],
}

_BASE_ENV = {"SEARXNG_URL": "http://searxng:8080"}


def _mock_client(api_response: dict) -> AsyncMock:
    """Build a mocked httpx.AsyncClient returning *api_response*."""
    mock_response = MagicMock()
    mock_response.json.return_value = api_response
    mock_response.raise_for_status = MagicMock()

    client = AsyncMock()
    client.get = AsyncMock(return_value=mock_response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


class TestGetConfig:
    def test_raises_without_url(self):
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="SEARXNG_URL nicht konfiguriert"):
                _get_config()

    def test_reads_env_vars(self):
        env = {
            "SEARXNG_URL": "http://searxng:9090",
            "SEARXNG_RESULT_COUNT": "5",
            "SEARXNG_LANGUAGE": "en",
        }
        with patch.dict(os.environ, env, clear=True):
            url, count, lang = _get_config()
            assert url == "http://searxng:9090"
            assert count == 5
            assert lang == "en"

    def test_defaults(self):
        with patch.dict(os.environ, _BASE_ENV, clear=True):
            url, count, lang = _get_config()
            assert url == "http://searxng:8080"
            assert count == 10
            assert lang == "de"

    def test_trailing_slash_stripped(self):
        env = {"SEARXNG_URL": "http://searxng:8080/"}
        with patch.dict(os.environ, env, clear=True):
            url, _, _ = _get_config()
            assert url == "http://searxng:8080"


class TestWebSearch:
    @pytest.mark.asyncio
    async def test_success(self):
        client = _mock_client(_SAMPLE_RESULTS)

        with (
            patch.dict(os.environ, _BASE_ENV, clear=True),
            patch("niles.mcp.search.server.httpx.AsyncClient", return_value=client),
        ):
            result = await web_search(query="test query")

        assert "First Result" in result
        assert "https://example.com/1" in result
        assert "Second Result" in result
        assert "1." in result
        assert "2." in result

    @pytest.mark.asyncio
    async def test_no_config(self):
        with patch.dict(os.environ, {}, clear=True):
            result = await web_search(query="test")

        assert "SEARXNG_URL nicht konfiguriert" in result

    @pytest.mark.asyncio
    async def test_http_error(self):
        client = AsyncMock()
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.ConnectError("refused")
        client.get = AsyncMock(return_value=mock_response)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.dict(os.environ, _BASE_ENV, clear=True),
            patch("niles.mcp.search.server.httpx.AsyncClient", return_value=client),
        ):
            result = await web_search(query="test")

        assert "Fehler" in result

    @pytest.mark.asyncio
    async def test_no_results(self):
        empty = {"query": "nope", "number_of_results": 0, "results": []}
        client = _mock_client(empty)

        with (
            patch.dict(os.environ, _BASE_ENV, clear=True),
            patch("niles.mcp.search.server.httpx.AsyncClient", return_value=client),
        ):
            result = await web_search(query="nope")

        assert "Keine Ergebnisse" in result
        assert "nope" in result

    @pytest.mark.asyncio
    async def test_result_count_limits_output(self):
        client = _mock_client(_SAMPLE_RESULTS)  # 3 results

        with (
            patch.dict(os.environ, _BASE_ENV, clear=True),
            patch("niles.mcp.search.server.httpx.AsyncClient", return_value=client),
        ):
            result = await web_search(query="test", result_count=2)

        assert "1." in result
        assert "2." in result
        assert "3." not in result

    @pytest.mark.asyncio
    async def test_content_truncation(self):
        long_content = "A" * 300
        data = {
            "query": "test",
            "number_of_results": 1,
            "results": [
                {
                    "title": "Long",
                    "url": "https://example.com",
                    "content": long_content,
                }
            ],
        }
        client = _mock_client(data)

        with (
            patch.dict(os.environ, _BASE_ENV, clear=True),
            patch("niles.mcp.search.server.httpx.AsyncClient", return_value=client),
        ):
            result = await web_search(query="test")

        # Content should be truncated to 200 chars + "..."
        assert "..." in result
        assert long_content not in result

    @pytest.mark.asyncio
    async def test_categories_passed(self):
        client = _mock_client(_SAMPLE_RESULTS)

        with (
            patch.dict(os.environ, _BASE_ENV, clear=True),
            patch("niles.mcp.search.server.httpx.AsyncClient", return_value=client),
        ):
            await web_search(query="test", categories=["news", "general"])

        call_args = client.get.call_args
        params = call_args.kwargs.get("params") or call_args[1].get("params", {})
        assert params["categories"] == "news,general"

    @pytest.mark.asyncio
    async def test_time_range_passed(self):
        client = _mock_client(_SAMPLE_RESULTS)

        with (
            patch.dict(os.environ, _BASE_ENV, clear=True),
            patch("niles.mcp.search.server.httpx.AsyncClient", return_value=client),
        ):
            await web_search(query="test", time_range="week")

        call_args = client.get.call_args
        params = call_args.kwargs.get("params") or call_args[1].get("params", {})
        assert params["time_range"] == "week"

    @pytest.mark.asyncio
    async def test_language_override(self):
        client = _mock_client(_SAMPLE_RESULTS)

        with (
            patch.dict(os.environ, _BASE_ENV, clear=True),
            patch("niles.mcp.search.server.httpx.AsyncClient", return_value=client),
        ):
            await web_search(query="test", language="en")

        call_args = client.get.call_args
        params = call_args.kwargs.get("params") or call_args[1].get("params", {})
        assert params["language"] == "en"

    @pytest.mark.asyncio
    async def test_default_language(self):
        client = _mock_client(_SAMPLE_RESULTS)

        with (
            patch.dict(os.environ, _BASE_ENV, clear=True),
            patch("niles.mcp.search.server.httpx.AsyncClient", return_value=client),
        ):
            await web_search(query="test")

        call_args = client.get.call_args
        params = call_args.kwargs.get("params") or call_args[1].get("params", {})
        assert params["language"] == "de"
