# SPDX-License-Identifier: AGPL-3.0-only
"""Weather location search and persistence."""

import httpx

from ..config import Settings, apply_overrides
from ..settings_store import SettingsStore

_GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"


class WeatherAction:
    """Weather location search and persistence."""

    def __init__(self, settings_store: SettingsStore, *, http_client: httpx.AsyncClient):
        self.settings_store = settings_store
        self.http_client = http_client

    async def search_locations(self, query: str) -> list[dict]:
        """Search via Open-Meteo Geocoding API.

        Returns raw result dicts. Raises httpx.HTTPError on failure.
        """
        resp = await self.http_client.get(
            _GEOCODING_URL,
            params={"name": query.strip(), "count": 5, "language": "de"},
        )
        resp.raise_for_status()
        return resp.json().get("results", [])

    async def set_location(self, lat: str, lon: str, name: str, current_settings: Settings) -> Settings:
        """Persist weather location, return updated settings.

        Raises ValueError if lat/lon are not valid numbers.
        """
        try:
            float(lat.strip())
            float(lon.strip())
        except ValueError:
            raise ValueError("Ungültige Koordinaten.")
        await self.settings_store.set("weather_latitude", lat.strip())
        await self.settings_store.set("weather_longitude", lon.strip())
        await self.settings_store.set("weather_location_name", name.strip())
        return apply_overrides(
            current_settings,
            {
                "weather_latitude": lat.strip(),
                "weather_longitude": lon.strip(),
                "weather_location_name": name.strip(),
            },
        )

    async def remove_location(self, current_settings: Settings) -> Settings:
        """Remove weather location, return updated settings."""
        for key in ("weather_latitude", "weather_longitude", "weather_location_name"):
            await self.settings_store.delete(key)
        return apply_overrides(
            current_settings,
            {
                "weather_latitude": "",
                "weather_longitude": "",
                "weather_location_name": "",
            },
        )
