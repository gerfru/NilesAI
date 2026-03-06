"""Settings routes: settings page, update_setting, ollama_models."""

import html as _html
import logging

from fastapi import Form, Query, Request
from fastapi.responses import HTMLResponse
from openai import AsyncOpenAI

from ...config import apply_overrides
from ._core import (
    _USER_EDITABLE_SETTINGS,
    _ensure_csrf_cookie,
    _google_configured,
    _require_admin,
    _require_admin_page,
    _require_auth_and_csrf,
    _require_auth_page,
    _safe_settings_dict,
    router,
    templates,
)

logger = logging.getLogger(__name__)


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, error: str = Query(default="")):
    """Settings dashboard (safe dict, no __dict__ access)."""
    user, auth_error = await _require_auth_page(request)
    if auth_error:
        return auth_error
    assert user is not None

    # Map error codes to user-visible messages
    error_msg = ""
    if error == "calendar_connect_failed":
        error_msg = "Google Kalender-Verbindung fehlgeschlagen. Bitte erneut versuchen."

    safe = _safe_settings_dict(request.app.state.settings)

    # Check if user has connected Google Calendar
    google_connected = False
    token_store = getattr(request.app.state, "google_token_store", None)
    if token_store:
        google_connected = await token_store.has_tokens(user["uid"])

    response = templates.TemplateResponse(
        request,
        "settings.html",
        {
            **safe,
            **safe.get("weather", {}),
            "active_page": "settings",
            "user": user,
            "google_configured": _google_configured(request),
            "google_connected": google_connected,
            "calendar_error": error_msg,
            "signal_api_url": bool(request.app.state.settings.signal_api_url),
            "vikunja_url": request.app.state.settings.vikunja_public_url or "",
        },
    )
    _ensure_csrf_cookie(request, response)
    return response


@router.get("/api/settings/ollama_models", response_class=HTMLResponse)
async def ollama_models(request: Request):
    """Return <option> elements for all locally available Ollama models."""
    _user, error = await _require_admin_page(request)
    if error:
        return error

    settings = request.app.state.settings
    # Strip /v1 suffix to get Ollama's native API base
    base = settings.llm_base_url.rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]

    current_model = settings.llm_model
    try:
        general = request.app.state.http_clients.general
        resp = await general.get(f"{base}/api/tags", timeout=5)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        # Ollama unreachable — return single option with current value
        return HTMLResponse(
            f'<option value="{_html.escape(current_model)}" selected>'
            f"{_html.escape(current_model)} (Ollama nicht erreichbar)</option>"
        )

    models = sorted(
        (m["name"] for m in data.get("models", [])),
        key=str.lower,
    )

    if not models:
        return HTMLResponse(
            f'<option value="{_html.escape(current_model)}" selected>'
            f"{_html.escape(current_model)}</option>"
        )

    options = []
    for name in models:
        selected = " selected" if name == current_model else ""
        options.append(
            f'<option value="{_html.escape(name)}"{selected}>'
            f"{_html.escape(name)}</option>"
        )

    # If current model is not in the list (e.g. deleted), add it at top
    if current_model and current_model not in models:
        options.insert(
            0,
            f'<option value="{_html.escape(current_model)}" selected>'
            f"{_html.escape(current_model)} (nicht installiert)</option>",
        )

    return HTMLResponse("\n".join(options))


@router.post("/api/settings/{key}", response_class=HTMLResponse)
async def update_setting(request: Request, key: str, value: str = Form(...)):
    """Update a single runtime setting."""
    if key in _USER_EDITABLE_SETTINGS:
        _user, error = await _require_auth_and_csrf(request)
    else:
        _user, error = await _require_admin(request)
    if error:
        return error

    settings_store = request.app.state.settings_store
    settings = request.app.state.settings

    # Validate key exists on settings before touching DB
    if not hasattr(settings, key):
        return templates.TemplateResponse(
            request,
            "fragments/toast.html",
            {
                "message": f"Unbekannte Einstellung: '{key}'",
                "toast_type": "error",
            },
        )

    # Convert value to appropriate type
    parsed_value: str | bool
    if key.startswith("feature_"):
        parsed_value = value.lower() in ("true", "1", "on")
    else:
        parsed_value = value

    try:
        await settings_store.set(key, parsed_value)
        new_settings = apply_overrides(settings, {key: parsed_value})
        request.app.state.settings = new_settings
        # Keep CalDAV sync config in sync so allowed_collections() reads fresh data
        caldav = getattr(request.app.state, "caldav", None)
        if caldav:
            caldav.config = new_settings
        # Hot-reload CardDAV credentials when they change
        if key.startswith("carddav_"):
            carddav_sync = getattr(request.app.state, "carddav_sync", None)
            if carddav_sync:
                carddav_sync.update_config(new_settings)
        # Hot-reload LLM settings on the running agent
        agent = request.app.state.agent
        if agent is not None:
            if key == "llm_model":
                agent.model = new_settings.llm_model
            elif key == "llm_base_url":
                # Ollama ignores the key; non-empty string required by SDK
                agent.llm = AsyncOpenAI(
                    base_url=new_settings.llm_base_url,
                    api_key="not-needed",
                )
    except ValueError as e:
        return templates.TemplateResponse(
            request,
            "fragments/toast.html",
            {
                "message": str(e),
                "toast_type": "error",
            },
        )

    return templates.TemplateResponse(
        request,
        "fragments/toast.html",
        {
            "message": f"'{key}' gespeichert",
            "toast_type": "success",
        },
    )
