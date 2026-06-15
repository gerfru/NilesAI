"""Tests for the web fetch MCP server."""

import os
import socket
from unittest.mock import AsyncMock, MagicMock, patch

from niles.network import is_private_host
from niles.mcp.fetch.server import fetch_url

# A fixed public IP that resolve_public_ip is stubbed to return in tests.
_PUBLIC_IP = "93.184.216.34"


def _mock_client(get_return=None, get_side_effect=None):
    client = AsyncMock()
    if get_side_effect is not None:
        client.get = AsyncMock(side_effect=get_side_effect)
    else:
        client.get = AsyncMock(return_value=get_return)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


def _html_response(text="<html><body><p>Hi</p></body></html>", content_type="text/html"):
    resp = MagicMock()
    resp.status_code = 200
    resp.headers = {"content-type": content_type}
    resp.content = text.encode()
    resp.text = text
    resp.raise_for_status = MagicMock()
    resp.is_redirect = False
    return resp


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

    async def test_prepends_https_and_pins_ip(self):
        """URL without scheme gets https://, and the connection is pinned to the
        validated IP while the original host is preserved in Host + SNI."""
        client = _mock_client(get_return=_html_response())

        with (
            patch("niles.mcp.fetch.server.resolve_public_ip", return_value=_PUBLIC_IP),
            patch("niles.mcp.fetch.server.httpx.AsyncClient", return_value=client),
            patch("niles.mcp.fetch.server.trafilatura.extract", return_value="Hello World"),
        ):
            result = await fetch_url("example.com")

        call = client.get.call_args
        assert call.args[0].startswith(f"https://{_PUBLIC_IP}")  # connect to the IP
        assert call.kwargs["headers"]["Host"] == "example.com"  # preserve Host
        assert call.kwargs["extensions"]["sni_hostname"] == "example.com"  # preserve SNI
        assert "Hello World" in result

    async def test_timeout_error(self):
        import httpx as httpx_mod

        client = _mock_client(get_side_effect=httpx_mod.TimeoutException("timeout"))
        with (
            patch("niles.mcp.fetch.server.resolve_public_ip", return_value=_PUBLIC_IP),
            patch("niles.mcp.fetch.server.httpx.AsyncClient", return_value=client),
        ):
            result = await fetch_url("https://slow-site.example.com")
            assert "Timeout" in result

    async def test_wrong_content_type(self):
        client = _mock_client(get_return=_html_response(content_type="application/pdf"))
        with (
            patch("niles.mcp.fetch.server.resolve_public_ip", return_value=_PUBLIC_IP),
            patch("niles.mcp.fetch.server.httpx.AsyncClient", return_value=client),
        ):
            result = await fetch_url("https://example.com/doc.pdf")
            assert "Content-Type" in result

    async def test_successful_extraction(self):
        client = _mock_client(get_return=_html_response())
        with (
            patch("niles.mcp.fetch.server.resolve_public_ip", return_value=_PUBLIC_IP),
            patch("niles.mcp.fetch.server.httpx.AsyncClient", return_value=client),
            patch("niles.mcp.fetch.server.trafilatura.extract", return_value="Main content here."),
        ):
            result = await fetch_url("https://example.com/article")
            assert "Main content here." in result

    async def test_truncation(self):
        long_text = "Dies ist ein Satz. " * 500
        client = _mock_client(get_return=_html_response())
        with (
            patch("niles.mcp.fetch.server.resolve_public_ip", return_value=_PUBLIC_IP),
            patch("niles.mcp.fetch.server.httpx.AsyncClient", return_value=client),
            patch("niles.mcp.fetch.server.trafilatura.extract", return_value=long_text),
            patch.dict(os.environ, {"FETCH_MAX_CHARS": "200"}),
        ):
            result = await fetch_url("https://example.com")
            assert "Gekuerzt" in result
            assert len(result) < 400

    async def test_no_content_extracted(self):
        client = _mock_client(get_return=_html_response())
        with (
            patch("niles.mcp.fetch.server.resolve_public_ip", return_value=_PUBLIC_IP),
            patch("niles.mcp.fetch.server.httpx.AsyncClient", return_value=client),
            patch("niles.mcp.fetch.server.trafilatura.extract", return_value=None),
        ):
            result = await fetch_url("https://example.com/empty")
            assert "Kein Textinhalt" in result

    async def test_ssrf_blocks_private_ip(self):
        """A host resolving to a private/reserved IP is blocked (resolve→None)."""
        with patch("niles.mcp.fetch.server.resolve_public_ip", return_value=None):
            result = await fetch_url("https://169.254.169.254/metadata")
            assert "interne Adressen" in result

    async def test_ssrf_allows_public_ip(self):
        client = _mock_client(get_return=_html_response(text="<html><body>Public</body></html>"))
        with (
            patch("niles.mcp.fetch.server.resolve_public_ip", return_value=_PUBLIC_IP),
            patch("niles.mcp.fetch.server.httpx.AsyncClient", return_value=client),
            patch("niles.mcp.fetch.server.trafilatura.extract", return_value="Public content"),
        ):
            result = await fetch_url("https://example.com")
            assert "Public content" in result

    async def test_ssrf_rebinding_redirect_to_private_blocked(self):
        """Redirect target that resolves to a private IP is blocked at connect."""
        redirect = MagicMock()
        redirect.is_redirect = True
        redirect.headers = {"location": "http://169.254.169.254/metadata"}
        client = _mock_client(get_return=redirect)

        # First host (evil.example.com) is public; the redirect target resolves private.
        def resolve(host):
            return None if host == "169.254.169.254" else _PUBLIC_IP

        with (
            patch("niles.mcp.fetch.server.resolve_public_ip", side_effect=resolve),
            patch("niles.mcp.fetch.server.httpx.AsyncClient", return_value=client),
        ):
            result = await fetch_url("https://evil.example.com/redirect")
            assert "interne Adressen" in result

    async def test_ssrf_redirect_to_public_allowed(self):
        redirect = MagicMock()
        redirect.is_redirect = True
        redirect.headers = {"location": "https://other.example.com/page"}
        final = _html_response(text="<html><body>Redirected</body></html>")
        client = _mock_client(get_side_effect=[redirect, final])

        with (
            patch("niles.mcp.fetch.server.resolve_public_ip", return_value=_PUBLIC_IP),
            patch("niles.mcp.fetch.server.httpx.AsyncClient", return_value=client),
            patch("niles.mcp.fetch.server.trafilatura.extract", return_value="Redirected content"),
        ):
            result = await fetch_url("https://example.com/old-page")
            assert "Redirected content" in result

    async def test_ssrf_too_many_redirects(self):
        redirect = MagicMock()
        redirect.is_redirect = True
        redirect.headers = {"location": "https://example.com/loop"}
        client = _mock_client(get_return=redirect)

        with (
            patch("niles.mcp.fetch.server.resolve_public_ip", return_value=_PUBLIC_IP),
            patch("niles.mcp.fetch.server.httpx.AsyncClient", return_value=client),
        ):
            result = await fetch_url("https://example.com/loop")
            assert "Zu viele Redirects" in result


class TestIsPrivateHost:
    def test_localhost_is_private(self):
        assert is_private_host("localhost") is True

    def test_private_ip_is_private(self):
        with patch(
            "niles.network.socket.getaddrinfo",
            return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.1", 0))],
        ):
            assert is_private_host("internal.example.com") is True

    def test_public_ip_is_not_private(self):
        with patch(
            "niles.network.socket.getaddrinfo",
            return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))],
        ):
            assert is_private_host("example.com") is False

    def test_unresolvable_host_returns_true(self):
        with patch(
            "niles.network.socket.getaddrinfo",
            side_effect=socket.gaierror("not found"),
        ):
            assert is_private_host("nonexistent.invalid") is True
