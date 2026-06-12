# SPDX-License-Identifier: AGPL-3.0-only
"""Weather location routes: search, set, remove."""

import html as _html
import logging

import httpx
from fastapi import Form, Query, Request, Response
from fastapi.responses import HTMLResponse

from ._core import (
    _get_session_user,
    _require_auth_and_csrf,
    router,
    templates,
)

logger = logging.getLogger(__name__)


@router.get("/api/weather/location-search", response_class=HTMLResponse)
async def weather_location_search(
    request: Request,
    q: str = Query(default="", min_length=2, max_length=100),
):
    """Proxy location search via Open-Meteo Geocoding API, return HTMX fragment."""
    user = _get_session_user(request)
    if user is None:
        return Response(status_code=401, headers={"HX-Redirect": "/ui/login"})

    if len(q.strip()) < 2:
        return HTMLResponse("")

    weather_action = request.app.state.weather_action

    try:
        results = await weather_action.search_locations(q)
    except httpx.HTTPError:
        return HTMLResponse('<p class="text-sm text-red-500 py-1">Suche fehlgeschlagen.</p>')

    if not results:
        return HTMLResponse('<p class="text-sm text-zinc-500 dark:text-zinc-400 py-1">Kein Ergebnis gefunden.</p>')

    items = []
    for r in results:
        name = r.get("name", "")
        admin1 = r.get("admin1", "")
        country = r.get("country", "")
        lat = r.get("latitude", "")
        lon = r.get("longitude", "")
        label = ", ".join(filter(None, [name, admin1, country]))
        label_esc = _html.escape(label)
        lat_esc = _html.escape(str(lat))
        lon_esc = _html.escape(str(lon))
        items.append(
            f'<button type="button" '
            f'class="block w-full text-left px-3 py-2 text-sm text-zinc-700 '
            f"dark:text-zinc-200 hover:bg-blue-50 dark:hover:bg-zinc-700 "
            f'cursor-pointer rounded" '
            f"data-weather-select "
            f'data-lat="{lat_esc}" data-lon="{lon_esc}" data-label="{label_esc}">'
            f"{label_esc}</button>"
        )
    return HTMLResponse("\n".join(items))


@router.post("/api/weather/location", response_class=HTMLResponse)
async def weather_location_set(
    request: Request,
    latitude: str = Form(...),
    longitude: str = Form(...),
    location_name: str = Form(""),
):
    """Save weather location (latitude, longitude, display name)."""
    _user, error = await _require_auth_and_csrf(request)
    if error:
        return error

    settings = request.app.state.settings
    weather_action = request.app.state.weather_action

    try:
        new_settings = await weather_action.set_location(latitude, longitude, location_name, settings)
        request.app.state.settings = new_settings
    except ValueError as e:
        return templates.TemplateResponse(
            request,
            "fragments/toast.html",
            {"message": str(e), "toast_type": "error"},
        )

    return templates.TemplateResponse(
        request,
        "fragments/weather_location.html",
        {
            "weather_location_name": location_name.strip(),
            "weather_latitude": latitude.strip(),
            "weather_longitude": longitude.strip(),
            "weather_just_saved": True,
        },
    )


@router.post("/api/weather/location/remove", response_class=HTMLResponse)
async def weather_location_remove(request: Request):
    """Remove weather location configuration."""
    _user, error = await _require_auth_and_csrf(request)
    if error:
        return error

    settings = request.app.state.settings
    weather_action = request.app.state.weather_action

    new_settings = await weather_action.remove_location(settings)
    request.app.state.settings = new_settings

    return templates.TemplateResponse(
        request,
        "fragments/weather_location.html",
        {
            "weather_location_name": "",
            "weather_latitude": "",
            "weather_longitude": "",
        },
    )
