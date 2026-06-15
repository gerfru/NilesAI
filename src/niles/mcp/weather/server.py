# SPDX-License-Identifier: AGPL-3.0-only
"""Weather MCP server using Open-Meteo API (ECMWF IFS data).

Provides two tools:
- get_current_weather: current conditions for the configured location
- get_forecast: multi-day forecast (1-7 days)

Configuration via environment variables:
  WEATHER_LATITUDE   e.g. "48.2082"
  WEATHER_LONGITUDE  e.g. "16.3738"
  WEATHER_TIMEZONE   e.g. "Europe/Vienna"
"""

import os
from datetime import datetime
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

from niles.http_retry import retry_http

mcp = FastMCP("weather")

_BASE_URL = "https://api.open-meteo.com/v1/forecast"

# WMO Weather interpretation codes -> German descriptions
# https://open-meteo.com/en/docs#weathervariables
WEATHER_CODES: dict[int, str] = {
    0: "Klar",
    1: "Ueberwiegend klar",
    2: "Teilweise bewoelkt",
    3: "Bedeckt",
    45: "Nebel",
    48: "Nebel mit Reifbildung",
    51: "Leichter Nieselregen",
    53: "Maessiger Nieselregen",
    55: "Starker Nieselregen",
    56: "Leichter gefrierender Nieselregen",
    57: "Starker gefrierender Nieselregen",
    61: "Leichter Regen",
    63: "Maessiger Regen",
    65: "Starker Regen",
    66: "Leichter gefrierender Regen",
    67: "Starker gefrierender Regen",
    71: "Leichter Schneefall",
    73: "Maessiger Schneefall",
    75: "Starker Schneefall",
    77: "Schneegriesel",
    80: "Leichte Regenschauer",
    81: "Maessige Regenschauer",
    82: "Starke Regenschauer",
    85: "Leichte Schneeschauer",
    86: "Starke Schneeschauer",
    95: "Gewitter",
    96: "Gewitter mit leichtem Hagel",
    99: "Gewitter mit starkem Hagel",
}

_WIND_DIRECTIONS = ["N", "NO", "O", "SO", "S", "SW", "W", "NW"]
_WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


def describe_weather(code: int) -> str:
    """Translate a WMO weather code to a German description."""
    return WEATHER_CODES.get(code, f"Unbekannt ({code})")


def wind_direction_text(degrees: float) -> str:
    """Convert wind direction in degrees to a compass abbreviation."""
    idx = round(degrees / 45) % 8
    return _WIND_DIRECTIONS[idx]


def _daily_value(daily: dict, key: str, index: int, default: Any = "?") -> Any:
    """Safely get a value from Open-Meteo daily data arrays."""
    values = daily.get(key) or []
    return values[index] if index < len(values) else default


def _get_config() -> tuple[str, str, str]:
    """Read location config from environment.

    Returns (latitude, longitude, timezone).
    Raises ValueError if location is not configured.
    """
    lat = os.environ.get("WEATHER_LATITUDE", "")
    lon = os.environ.get("WEATHER_LONGITUDE", "")
    tz = os.environ.get("WEATHER_TIMEZONE", "Europe/Vienna")
    if not lat or not lon:
        raise ValueError("Standort nicht konfiguriert. Bitte Breitengrad und Laengengrad in den Einstellungen angeben.")
    return lat, lon, tz


@retry_http
async def _fetch_open_meteo(params: dict) -> dict:
    """HTTP call to Open-Meteo API (retryable on transient failures)."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(_BASE_URL, params=params)
        resp.raise_for_status()
        return resp.json()


@mcp.tool()
async def get_current_weather() -> str:
    """Aktuelles Wetter am konfigurierten Standort abrufen.

    Liefert Temperatur, gefuehlte Temperatur, Luftfeuchtigkeit,
    Wetterlage und Wind.
    """
    try:
        lat, lon, tz = _get_config()
    except ValueError as e:
        return str(e)

    params = {
        "latitude": lat,
        "longitude": lon,
        "current": ",".join(
            [
                "temperature_2m",
                "apparent_temperature",
                "relative_humidity_2m",
                "weather_code",
                "wind_speed_10m",
                "wind_direction_10m",
            ]
        ),
        "timezone": tz,
    }

    try:
        data = await _fetch_open_meteo(params)
    except httpx.HTTPError as e:
        return f"Fehler beim Abrufen der Wetterdaten: {e}"

    current = data.get("current", {})
    weather_code = current.get("weather_code", -1)
    temp = current.get("temperature_2m", "?")
    feels = current.get("apparent_temperature", "?")
    humidity = current.get("relative_humidity_2m", "?")
    wind_speed = current.get("wind_speed_10m", "?")
    wind_dir = current.get("wind_direction_10m", 0)

    time_str = current.get("time", "")
    try:
        dt = datetime.fromisoformat(time_str)
        formatted_time = dt.strftime("%d.%m.%Y %H:%M")
    except ValueError, TypeError:
        formatted_time = time_str

    lines = [
        f"Aktuelles Wetter ({formatted_time}):",
        f"  Wetter: {describe_weather(weather_code)}",
        f"  Temperatur: {temp}\u00b0C",
        f"  Gefuehlt: {feels}\u00b0C",
        f"  Luftfeuchtigkeit: {humidity}%",
        f"  Wind: {wind_speed} km/h aus {wind_direction_text(wind_dir)}",
    ]
    return "\n".join(lines)


@mcp.tool()
async def get_forecast(days: int = 3) -> str:
    """Wettervorhersage fuer die naechsten Tage abrufen.

    Args:
        days: Anzahl der Vorhersagetage (1-7, Standard: 3)
    """
    days = max(1, min(7, days))

    try:
        lat, lon, tz = _get_config()
    except ValueError as e:
        return str(e)

    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": ",".join(
            [
                "weather_code",
                "temperature_2m_max",
                "temperature_2m_min",
                "precipitation_sum",
                "precipitation_probability_max",
                "sunrise",
                "sunset",
            ]
        ),
        "timezone": tz,
        "forecast_days": str(days),
    }

    try:
        data = await _fetch_open_meteo(params)
    except httpx.HTTPError as e:
        return f"Fehler beim Abrufen der Vorhersage: {e}"

    daily = data.get("daily", {})
    dates = daily.get("time", [])
    if not dates:
        return "Keine Vorhersagedaten verfuegbar."

    lines = [f"Wettervorhersage ({len(dates)} Tage):"]

    for i, date_str in enumerate(dates):
        try:
            dt = datetime.fromisoformat(date_str)
            weekday = _WEEKDAYS[dt.weekday()]
            day_label = f"{weekday}, {dt.strftime('%d.%m.')}"
        except ValueError, TypeError:
            day_label = date_str

        code = _daily_value(daily, "weather_code", i, default=0)
        t_min = _daily_value(daily, "temperature_2m_min", i)
        t_max = _daily_value(daily, "temperature_2m_max", i)
        precip = _daily_value(daily, "precipitation_sum", i, default=0)
        prob = _daily_value(daily, "precipitation_probability_max", i, default=0)
        sunrise_raw = _daily_value(daily, "sunrise", i, default="")
        sunset_raw = _daily_value(daily, "sunset", i, default="")

        try:
            sunrise = datetime.fromisoformat(sunrise_raw).strftime("%H:%M")
        except ValueError, TypeError:
            sunrise = sunrise_raw
        try:
            sunset = datetime.fromisoformat(sunset_raw).strftime("%H:%M")
        except ValueError, TypeError:
            sunset = sunset_raw

        lines.append(f"\n{day_label}:")
        lines.append(f"  {describe_weather(code)}")
        lines.append(f"  Temperatur: {t_min}\u2013{t_max}\u00b0C")
        lines.append(f"  Niederschlag: {precip}mm (Wahrscheinlichkeit: {prob}%)")
        if sunrise and sunset:
            lines.append(f"  Sonne: {sunrise} \u2013 {sunset}")

    return "\n".join(lines)
