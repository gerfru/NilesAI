"""Tests for SSRF protection (network.py + consumers)."""

from unittest.mock import AsyncMock, patch

import pytest

from niles.network import is_private_host


class TestIsPrivateHost:
    """Test SSRF rejection for private/reserved IP ranges."""

    def test_localhost_is_private(self):
        assert is_private_host("localhost") is True

    def test_127_0_0_1_is_private(self):
        assert is_private_host("127.0.0.1") is True

    @patch("niles.network.socket.getaddrinfo")
    def test_10_x_is_private(self, mock_gai):
        mock_gai.return_value = [
            (2, 1, 6, "", ("10.0.0.1", 0)),
        ]
        assert is_private_host("internal.example.com") is True

    @patch("niles.network.socket.getaddrinfo")
    def test_172_16_is_private(self, mock_gai):
        mock_gai.return_value = [
            (2, 1, 6, "", ("172.16.0.5", 0)),
        ]
        assert is_private_host("internal.example.com") is True

    @patch("niles.network.socket.getaddrinfo")
    def test_192_168_is_private(self, mock_gai):
        mock_gai.return_value = [
            (2, 1, 6, "", ("192.168.1.1", 0)),
        ]
        assert is_private_host("internal.example.com") is True

    @patch("niles.network.socket.getaddrinfo")
    def test_169_254_link_local(self, mock_gai):
        mock_gai.return_value = [
            (2, 1, 6, "", ("169.254.169.254", 0)),
        ]
        assert is_private_host("metadata.google.internal") is True

    @patch("niles.network.socket.getaddrinfo")
    def test_public_ip_is_not_private(self, mock_gai):
        mock_gai.return_value = [
            (2, 1, 6, "", ("93.184.216.34", 0)),
        ]
        assert is_private_host("example.com") is False

    @patch("niles.network.socket.getaddrinfo")
    def test_dns_failure_returns_true(self, mock_gai):
        import socket

        mock_gai.side_effect = socket.gaierror("Name resolution failed")
        assert is_private_host("nonexistent.invalid") is True


class TestCalendarManagerSSRF:
    """Test that CalendarSourceManager.add_source blocks internal URLs."""

    async def test_rejects_localhost_url(self):
        from niles.sync.manager import CalendarSourceManager

        pool = AsyncMock()
        settings = AsyncMock()
        settings.caldav_url = ""
        mgr = CalendarSourceManager(pool, settings, client=AsyncMock())

        with pytest.raises(ValueError, match="Interne Adressen"):
            await mgr.add_source(
                name="Evil",
                url="https://localhost/calendar.ics",
            )

    async def test_rejects_private_ip_url(self):
        from niles.sync.manager import CalendarSourceManager

        pool = AsyncMock()
        settings = AsyncMock()
        settings.caldav_url = ""
        mgr = CalendarSourceManager(pool, settings, client=AsyncMock())

        with pytest.raises(ValueError, match="Interne Adressen"):
            await mgr.add_source(
                name="Evil",
                url="https://127.0.0.1/calendar.ics",
            )

    async def test_rejects_non_https(self):
        from niles.sync.manager import CalendarSourceManager

        pool = AsyncMock()
        settings = AsyncMock()
        settings.caldav_url = ""
        mgr = CalendarSourceManager(pool, settings, client=AsyncMock())

        with pytest.raises(ValueError, match="HTTPS"):
            await mgr.add_source(
                name="Evil",
                url="http://example.com/calendar.ics",
            )


class TestCardDAVManagerSSRF:
    """Test that CardDAVSourceManager.add_source uses canonical is_private_host."""

    async def test_rejects_private_host(self):
        from niles.sync.carddav_manager import CardDAVSourceManager

        pool = AsyncMock()
        mgr = CardDAVSourceManager(pool, client=AsyncMock())

        with patch("niles.sync.carddav_manager.is_private_host", return_value=True):
            with pytest.raises(ValueError, match="Interne Adressen"):
                await mgr.add_source("https://internal.corp/carddav", "user", "pass")

    async def test_allows_public_host(self):
        from niles.sync.carddav_manager import CardDAVSourceManager

        pool = AsyncMock()
        pool.fetchrow = AsyncMock(return_value={"id": 1, "url": "https://dav.example.com"})
        mgr = CardDAVSourceManager(pool, client=AsyncMock())

        with patch("niles.sync.carddav_manager.is_private_host", return_value=False):
            result = await mgr.add_source("https://dav.example.com/contacts", "user", "pass")
            assert result is not None

    async def test_test_connection_rejects_non_https(self):
        from niles.sync.carddav_manager import CardDAVSourceManager

        pool = AsyncMock()
        mgr = CardDAVSourceManager(pool, client=AsyncMock())

        with pytest.raises(ValueError, match="HTTPS"):
            await mgr.test_connection("http://dav.example.com/contacts", "user", "pass")

    async def test_test_connection_rejects_private_host(self):
        from niles.sync.carddav_manager import CardDAVSourceManager

        pool = AsyncMock()
        mgr = CardDAVSourceManager(pool, client=AsyncMock())

        with patch("niles.sync.carddav_manager.is_private_host", return_value=True):
            with pytest.raises(ValueError, match="Interne Adressen"):
                await mgr.test_connection("https://192.168.1.100/contacts", "user", "pass")
