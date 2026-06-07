"""Settings routes: settings page, update_setting, ollama_models."""

import html as _html
import logging

from fastapi import Form, Query, Request
from fastapi.responses import HTMLResponse
from openai import AsyncOpenAI

from ._core import (
    _USER_EDITABLE_SETTINGS,
    _ensure_csrf_cookie,
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

    safe = _safe_settings_dict(request.app.state.settings)

    response = templates.TemplateResponse(
        request,
        "settings.html",
        {
            **safe,
            **safe.get("weather", {}),
            "active_page": "settings",
            "user": user,
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
    current_model = settings.llm_model

    try:
        settings_action = request.app.state.settings_action
        models = await settings_action.list_ollama_models(settings.llm_base_url, current_model)
    except Exception:
        # Ollama unreachable — return single option with current value
        return HTMLResponse(
            f'<option value="{_html.escape(current_model)}" selected>'  # nosemgrep: raw-html-format
            f"{_html.escape(current_model)} (Ollama nicht erreichbar)</option>"
        )

    if not models:
        return HTMLResponse(
            f'<option value="{_html.escape(current_model)}" selected>{_html.escape(current_model)}</option>'  # nosemgrep: raw-html-format
        )

    options = []
    for m in models:
        name = m["name"]
        selected = " selected" if m["selected"] else ""
        options.append(
            f'<option value="{_html.escape(name)}"{selected}>{_html.escape(name)}</option>'  # nosemgrep: raw-html-format
        )

    # If current model is not in the list (e.g. deleted), add it at top
    model_names = [m["name"] for m in models]
    if current_model and current_model not in model_names:
        options.insert(
            0,
            f'<option value="{_html.escape(current_model)}" selected>'  # nosemgrep: raw-html-format
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

    settings = request.app.state.settings
    settings_action = request.app.state.settings_action

    try:
        new_settings = await settings_action.update(key, value, settings)
        request.app.state.settings = new_settings
        # Keep CalDAV sync config in sync so allowed_collections() reads fresh data
        caldav = getattr(request.app.state, "caldav", None)
        if caldav:
            caldav.config = new_settings
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
