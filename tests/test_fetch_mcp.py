"""Tests for the web fetch MCP server."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

from niles.mcp.fetch.server import fetch_url


class TestFetchUrl:
    async def test_empty_url(self):
        result = await fetch_url("")
        assert "Keine URL" in result

    async def test_blocked_scheme_file(self):
        result = await fetch_url("file:///etc/passwd")
        assert "nicht erlaubt" in result

    async def test_blocked_scheme_javascript(self):
        result = await fetch_url("javascript:alert(1)")
        assert "nicht erlaubt" in result

    async def test_prepends_https(self):
        """URL without scheme gets https:// prepended."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "text/html"}
        mock_response.content = b"<html><body><p>Hello World</p></body></html>"
        mock_response.text = "<html><body><p>Hello World</p></body></html>"
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "niles.mcp.fetch.server.httpx.AsyncClient", return_value=mock_client
        ):
            with patch(
                "niles.mcp.fetch.server.trafilatura.extract",
                return_value="Hello World",
            ):
                result = await fetch_url("example.com")
                # Verify https:// was prepended
                call_args = mock_client.get.call_args[0][0]
                assert call_args == "https://example.com"
                assert "Hello World" in result

    async def test_timeout_error(self):
        import httpx as httpx_mod

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx_mod.TimeoutException("timeout"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "niles.mcp.fetch.server.httpx.AsyncClient", return_value=mock_client
        ):
            result = await fetch_url("https://slow-site.example.com")
            assert "Timeout" in result

    async def test_wrong_content_type(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/pdf"}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "niles.mcp.fetch.server.httpx.AsyncClient", return_value=mock_client
        ):
            result = await fetch_url("https://example.com/doc.pdf")
            assert "Content-Type" in result

    async def test_successful_extraction(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "text/html; charset=utf-8"}
        mock_response.content = (
            b"<html><body><article><p>Main content here.</p></article></body></html>"
        )
        mock_response.text = (
            "<html><body><article><p>Main content here.</p></article></body></html>"
        )
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "niles.mcp.fetch.server.httpx.AsyncClient",
                return_value=mock_client,
            ),
            patch(
                "niles.mcp.fetch.server.trafilatura.extract",
                return_value="Main content here.",
            ),
        ):
            result = await fetch_url("https://example.com/article")
            assert "Main content here." in result

    async def test_truncation(self):
        long_text = "Dies ist ein Satz. " * 500  # ~9500 chars
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "text/html"}
        mock_response.content = b"<html><body>long</body></html>"
        mock_response.text = "<html><body>long</body></html>"
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "niles.mcp.fetch.server.httpx.AsyncClient",
                return_value=mock_client,
            ),
            patch(
                "niles.mcp.fetch.server.trafilatura.extract",
                return_value=long_text,
            ),
            patch.dict(os.environ, {"FETCH_MAX_CHARS": "200"}),
        ):
            result = await fetch_url("https://example.com")
            assert "Gekuerzt" in result
            assert len(result) < 400  # 200 + truncation notice

    async def test_no_content_extracted(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "text/html"}
        mock_response.content = b"<html><body></body></html>"
        mock_response.text = "<html><body></body></html>"
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "niles.mcp.fetch.server.httpx.AsyncClient",
                return_value=mock_client,
            ),
            patch(
                "niles.mcp.fetch.server.trafilatura.extract",
                return_value=None,
            ),
        ):
            result = await fetch_url("https://example.com/empty")
            assert "Kein Textinhalt" in result
