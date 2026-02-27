"""Tests for the web fetch MCP server."""

import os
import socket
from unittest.mock import AsyncMock, MagicMock, patch

from niles.mcp.fetch.server import _is_private_host, fetch_url


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
        mock_response.is_redirect = False

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
        mock_response.is_redirect = False

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
        mock_response.is_redirect = False

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
        mock_response.is_redirect = False

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
        mock_response.is_redirect = False

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

    async def test_ssrf_blocks_private_ip(self):
        """Localhost/private IPs are blocked."""
        with patch("niles.mcp.fetch.server._is_private_host", return_value=True):
            result = await fetch_url("https://169.254.169.254/metadata")
            assert "interne Adressen" in result

    async def test_ssrf_allows_public_ip(self):
        """Public IPs are allowed through SSRF check."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "text/html"}
        mock_response.content = b"<html><body>Public</body></html>"
        mock_response.text = "<html><body>Public</body></html>"
        mock_response.raise_for_status = MagicMock()
        mock_response.is_redirect = False

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("niles.mcp.fetch.server._is_private_host", return_value=False),
            patch(
                "niles.mcp.fetch.server.httpx.AsyncClient",
                return_value=mock_client,
            ),
            patch(
                "niles.mcp.fetch.server.trafilatura.extract",
                return_value="Public content",
            ),
        ):
            result = await fetch_url("https://example.com")
            assert "Public content" in result

    async def test_ssrf_redirect_to_private_ip_blocked(self):
        """Redirect to private IP is blocked (SSRF via redirect chain)."""
        redirect_response = MagicMock()
        redirect_response.is_redirect = True
        redirect_response.headers = {"location": "http://169.254.169.254/metadata"}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=redirect_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("niles.mcp.fetch.server._is_private_host") as mock_priv,
            patch(
                "niles.mcp.fetch.server.httpx.AsyncClient",
                return_value=mock_client,
            ),
        ):
            # Initial URL is public, redirect target is private
            mock_priv.side_effect = lambda h: h == "169.254.169.254"
            result = await fetch_url("https://evil.example.com/redirect")
            assert "Redirect" in result and "blockiert" in result

    async def test_ssrf_redirect_to_public_ip_allowed(self):
        """Redirect to another public IP is allowed."""
        redirect_response = MagicMock()
        redirect_response.is_redirect = True
        redirect_response.headers = {"location": "https://other.example.com/page"}

        final_response = MagicMock()
        final_response.is_redirect = False
        final_response.status_code = 200
        final_response.headers = {"content-type": "text/html"}
        final_response.content = b"<html><body>Redirected</body></html>"
        final_response.text = "<html><body>Redirected</body></html>"
        final_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[redirect_response, final_response])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("niles.mcp.fetch.server._is_private_host", return_value=False),
            patch(
                "niles.mcp.fetch.server.httpx.AsyncClient",
                return_value=mock_client,
            ),
            patch(
                "niles.mcp.fetch.server.trafilatura.extract",
                return_value="Redirected content",
            ),
        ):
            result = await fetch_url("https://example.com/old-page")
            assert "Redirected content" in result

    async def test_ssrf_too_many_redirects(self):
        """More than 5 redirects returns error."""
        redirect_response = MagicMock()
        redirect_response.is_redirect = True
        redirect_response.headers = {"location": "https://example.com/loop"}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=redirect_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("niles.mcp.fetch.server._is_private_host", return_value=False),
            patch(
                "niles.mcp.fetch.server.httpx.AsyncClient",
                return_value=mock_client,
            ),
        ):
            result = await fetch_url("https://example.com/loop")
            assert "Zu viele Redirects" in result


class TestIsPrivateHost:
    def test_localhost_is_private(self):
        assert _is_private_host("localhost") is True

    def test_private_ip_is_private(self):
        with patch(
            "niles.mcp.fetch.server.socket.getaddrinfo",
            return_value=[
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.1", 0))
            ],
        ):
            assert _is_private_host("internal.example.com") is True

    def test_public_ip_is_not_private(self):
        with patch(
            "niles.mcp.fetch.server.socket.getaddrinfo",
            return_value=[
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))
            ],
        ):
            assert _is_private_host("example.com") is False

    def test_unresolvable_host_returns_false(self):
        with patch(
            "niles.mcp.fetch.server.socket.getaddrinfo",
            side_effect=socket.gaierror("not found"),
        ):
            assert _is_private_host("nonexistent.invalid") is False
