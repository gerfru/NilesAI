"""Integration tests for MCP tools (weather, fetch, searxng)."""

import httpx
import pytest

from .conftest import SEARXNG_URL

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]


class TestWeatherMCP:
    @pytest.fixture(autouse=True)
    def _set_weather_env(self, monkeypatch):
        """Set weather location for Vienna (Open-Meteo, no auth needed)."""
        monkeypatch.setenv("WEATHER_LATITUDE", "48.2082")
        monkeypatch.setenv("WEATHER_LONGITUDE", "16.3738")
        monkeypatch.setenv("WEATHER_TIMEZONE", "Europe/Vienna")

    async def test_get_current_weather(self):
        from niles.mcp.weather.server import get_current_weather

        result = await get_current_weather()
        assert isinstance(result, str)
        assert len(result) > 0
        # Should contain temperature info in German
        assert "°C" in result or "Temperatur" in result

    async def test_get_forecast(self):
        from niles.mcp.weather.server import get_forecast

        result = await get_forecast(days=2)
        assert isinstance(result, str)
        assert len(result) > 0


class TestFetchMCP:
    async def test_fetch_public_url(self):
        from niles.mcp.fetch.server import fetch_url

        try:
            async with httpx.AsyncClient(timeout=5) as client:
                await client.head("https://example.com")
        except (httpx.ConnectError, httpx.TimeoutException):
            pytest.skip("No outbound internet access")
        result = await fetch_url("https://example.com")
        assert len(result) > 0

    async def test_fetch_blocks_private_ip(self):
        from niles.mcp.fetch.server import fetch_url

        result = await fetch_url("http://127.0.0.1:9999")
        assert "nicht erlaubt" in result or "Fehler" in result or "error" in result.lower()

    async def test_fetch_blocks_file_scheme(self):
        from niles.mcp.fetch.server import fetch_url

        result = await fetch_url("file:///etc/passwd")
        assert "nicht erlaubt" in result or "Fehler" in result or "error" in result.lower()


class TestSearXNG:
    async def test_search(self, searxng_available):
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{SEARXNG_URL}/search",
                params={"q": "test", "format": "json"},
            )
            resp.raise_for_status()
            data = resp.json()
            assert "results" in data
