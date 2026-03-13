"""Tests for WeatherAction."""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from niles.actions.weather import WeatherAction

from tests.helpers import make_test_settings


class TestSearchLocations:
    @pytest.mark.asyncio
    async def test_returns_results(self):
        response = MagicMock()
        response.json.return_value = {
            "results": [
                {"name": "Wien", "admin1": "Wien", "country": "Austria"},
                {"name": "Wiener Neustadt", "admin1": "NÖ", "country": "Austria"},
            ]
        }
        response.raise_for_status = MagicMock()
        client = AsyncMock()
        client.get.return_value = response
        action = WeatherAction(AsyncMock(), http_client=client)

        results = await action.search_locations("Wien")

        assert len(results) == 2
        assert results[0]["name"] == "Wien"

    @pytest.mark.asyncio
    async def test_returns_empty_on_no_results(self):
        response = MagicMock()
        response.json.return_value = {}
        response.raise_for_status = MagicMock()
        client = AsyncMock()
        client.get.return_value = response
        action = WeatherAction(AsyncMock(), http_client=client)

        results = await action.search_locations("xyznonexistent")

        assert results == []

    @pytest.mark.asyncio
    async def test_raises_on_http_error(self):
        client = AsyncMock()
        client.get.side_effect = httpx.ConnectError("Connection refused")
        action = WeatherAction(AsyncMock(), http_client=client)

        with pytest.raises(httpx.ConnectError):
            await action.search_locations("Wien")


class TestSetLocation:
    @pytest.mark.asyncio
    async def test_persists_and_returns_updated_settings(self):
        store = AsyncMock()
        action = WeatherAction(store, http_client=AsyncMock())
        settings = make_test_settings()

        new_settings = await action.set_location(
            " 48.2082 ", " 16.3738 ", " Wien ", settings
        )

        assert store.set.call_count == 3
        store.set.assert_any_call("weather_latitude", "48.2082")
        store.set.assert_any_call("weather_longitude", "16.3738")
        store.set.assert_any_call("weather_location_name", "Wien")
        assert new_settings.weather_latitude == "48.2082"
        assert new_settings.weather_longitude == "16.3738"
        assert new_settings.weather_location_name == "Wien"

    @pytest.mark.asyncio
    async def test_invalid_lat_raises(self):
        action = WeatherAction(AsyncMock(), http_client=AsyncMock())
        settings = make_test_settings()

        with pytest.raises(ValueError, match="Ungültige Koordinaten"):
            await action.set_location("not-a-number", "16.3738", "Wien", settings)

    @pytest.mark.asyncio
    async def test_invalid_lon_raises(self):
        action = WeatherAction(AsyncMock(), http_client=AsyncMock())
        settings = make_test_settings()

        with pytest.raises(ValueError, match="Ungültige Koordinaten"):
            await action.set_location("48.2082", "abc", "Wien", settings)


class TestRemoveLocation:
    @pytest.mark.asyncio
    async def test_deletes_and_returns_cleared_settings(self):
        store = AsyncMock()
        action = WeatherAction(store, http_client=AsyncMock())
        settings = make_test_settings(
            weather_latitude="48.2082",
            weather_longitude="16.3738",
            weather_location_name="Wien",
        )

        new_settings = await action.remove_location(settings)

        assert store.delete.call_count == 3
        store.delete.assert_any_call("weather_latitude")
        store.delete.assert_any_call("weather_longitude")
        store.delete.assert_any_call("weather_location_name")
        assert new_settings.weather_latitude == ""
        assert new_settings.weather_longitude == ""
        assert new_settings.weather_location_name == ""
