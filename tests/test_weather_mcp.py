"""Tests for the Weather MCP server module."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from niles.mcp.weather.server import (
    WEATHER_CODES,
    _get_config,
    describe_weather,
    get_current_weather,
    get_forecast,
    wind_direction_text,
)


class TestWeatherCodes:
    def test_known_code(self):
        assert describe_weather(0) == "Klar"

    def test_rain(self):
        assert describe_weather(61) == "Leichter Regen"

    def test_thunderstorm(self):
        assert describe_weather(95) == "Gewitter"

    def test_unknown_code(self):
        result = describe_weather(999)
        assert "999" in result
        assert "Unbekannt" in result

    def test_all_codes_are_german(self):
        """All descriptions should be non-empty strings."""
        for code, desc in WEATHER_CODES.items():
            assert isinstance(desc, str)
            assert len(desc) > 0


class TestWindDirection:
    @pytest.mark.parametrize(
        "degrees,expected",
        [
            (0, "N"),
            (45, "NO"),
            (90, "O"),
            (135, "SO"),
            (180, "S"),
            (225, "SW"),
            (270, "W"),
            (315, "NW"),
            (360, "N"),
            (22, "N"),
            (23, "NO"),
        ],
    )
    def test_direction(self, degrees, expected):
        assert wind_direction_text(degrees) == expected


class TestGetConfig:
    def test_raises_without_env(self):
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="Standort nicht konfiguriert"):
                _get_config()

    def test_reads_env_vars(self):
        env = {
            "WEATHER_LATITUDE": "48.2082",
            "WEATHER_LONGITUDE": "16.3738",
            "WEATHER_TIMEZONE": "Europe/Vienna",
        }
        with patch.dict(os.environ, env, clear=True):
            lat, lon, tz = _get_config()
            assert lat == "48.2082"
            assert lon == "16.3738"
            assert tz == "Europe/Vienna"

    def test_default_timezone(self):
        env = {
            "WEATHER_LATITUDE": "48.2",
            "WEATHER_LONGITUDE": "16.3",
        }
        with patch.dict(os.environ, env, clear=True):
            _, _, tz = _get_config()
            assert tz == "Europe/Vienna"


class TestGetCurrentWeather:
    @pytest.mark.asyncio
    async def test_success(self):
        env = {
            "WEATHER_LATITUDE": "48.2082",
            "WEATHER_LONGITUDE": "16.3738",
            "WEATHER_TIMEZONE": "Europe/Vienna",
        }
        api_response = {
            "current": {
                "time": "2026-02-26T14:30",
                "temperature_2m": 15.2,
                "apparent_temperature": 13.8,
                "relative_humidity_2m": 65,
                "weather_code": 2,
                "wind_speed_10m": 12.5,
                "wind_direction_10m": 180,
            }
        }

        mock_response = MagicMock()
        mock_response.json.return_value = api_response
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.dict(os.environ, env, clear=True),
            patch("niles.mcp.weather.server.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await get_current_weather()

        assert "Teilweise bewoelkt" in result
        assert "15.2" in result
        assert "13.8" in result
        assert "65%" in result
        assert "12.5 km/h" in result
        assert "S" in result

    @pytest.mark.asyncio
    async def test_no_config(self):
        with patch.dict(os.environ, {}, clear=True):
            result = await get_current_weather()
        assert "Standort nicht konfiguriert" in result

    @pytest.mark.asyncio
    async def test_api_error(self):
        import httpx

        env = {
            "WEATHER_LATITUDE": "48.2",
            "WEATHER_LONGITUDE": "16.3",
        }

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.dict(os.environ, env, clear=True),
            patch("niles.mcp.weather.server.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await get_current_weather()

        assert "Fehler" in result


class TestGetForecast:
    @pytest.mark.asyncio
    async def test_success(self):
        env = {
            "WEATHER_LATITUDE": "48.2082",
            "WEATHER_LONGITUDE": "16.3738",
            "WEATHER_TIMEZONE": "Europe/Vienna",
        }
        api_response = {
            "daily": {
                "time": ["2026-02-26", "2026-02-27", "2026-02-28"],
                "weather_code": [2, 61, 0],
                "temperature_2m_max": [10.0, 8.0, 12.0],
                "temperature_2m_min": [2.0, 3.0, 1.0],
                "precipitation_sum": [0.0, 5.2, 0.0],
                "precipitation_probability_max": [5, 80, 0],
                "sunrise": [
                    "2026-02-26T06:45",
                    "2026-02-27T06:43",
                    "2026-02-28T06:41",
                ],
                "sunset": [
                    "2026-02-26T17:30",
                    "2026-02-27T17:32",
                    "2026-02-28T17:34",
                ],
            }
        }

        mock_response = MagicMock()
        mock_response.json.return_value = api_response
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.dict(os.environ, env, clear=True),
            patch("niles.mcp.weather.server.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await get_forecast(days=3)

        assert "3 Tage" in result
        assert "Teilweise bewoelkt" in result
        assert "Leichter Regen" in result
        assert "Klar" in result
        assert "2.0" in result
        assert "10.0" in result
        assert "5.2mm" in result
        assert "80%" in result

    @pytest.mark.asyncio
    async def test_days_clamped(self):
        """Days parameter is clamped to 1-7."""
        env = {
            "WEATHER_LATITUDE": "48.2",
            "WEATHER_LONGITUDE": "16.3",
        }
        api_response = {
            "daily": {
                "time": ["2026-02-26"],
                "weather_code": [0],
                "temperature_2m_max": [10.0],
                "temperature_2m_min": [2.0],
                "precipitation_sum": [0.0],
                "precipitation_probability_max": [0],
                "sunrise": ["2026-02-26T06:45"],
                "sunset": ["2026-02-26T17:30"],
            }
        }

        mock_response = MagicMock()
        mock_response.json.return_value = api_response
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.dict(os.environ, env, clear=True),
            patch("niles.mcp.weather.server.httpx.AsyncClient", return_value=mock_client),
        ):
            # days=10 should be clamped to 7
            result = await get_forecast(days=10)
            assert "Klar" in result

            # Verify the API was called with forecast_days="7"
            call_kwargs = mock_client.get.call_args
            assert call_kwargs[1]["params"]["forecast_days"] == "7"

    @pytest.mark.asyncio
    async def test_no_config(self):
        with patch.dict(os.environ, {}, clear=True):
            result = await get_forecast()
        assert "Standort nicht konfiguriert" in result
