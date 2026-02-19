"""Web GUI router -- htmx-powered chat and settings UI.

UI language: German (de) -- intentional design choice for the target user.
"""

import hmac
import logging
import secrets
import time
from collections import defaultdict
from pathlib import Path

from fastapi import APIRouter, Form, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..config import apply_overrides

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ui", tags=["web-ui"])

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

WEB_CHAT_ID = "web-ui"
COOKIE_NAME = "niles_api_key"
CSRF_COOKIE_NAME = "niles_csrf"
COOKIE_MAX_AGE = 30 * 24 * 3600  # 30 days

_CHAT_PAGE_SIZE = 20

# --- Login rate limiting (#6) ---
_login_attempts: dict[str, list[float]] = defaultdict(list)
_LOGIN_MAX_ATTEMPTS = 5
_LOGIN_WINDOW = 300.0  # 5 minutes


def _check_login_rate(client_ip: str) -> bool:
    """Return True if the client is within the login rate limit."""
    now = time.monotonic()
    window = now - _LOGIN_WINDOW
    attempts = _login_attempts[client_ip]
    _login_attempts[client_ip] = [t for t in attempts if t > window]
    return len(_login_attempts[client_ip]) < _LOGIN_MAX_ATTEMPTS


def _record_login_attempt(client_ip: str) -> None:
    _login_attempts[client_ip].append(time.monotonic())


# --- Security helpers ---


def _is_secure_context(request: Request) -> bool:
    """Detect whether the request arrived over HTTPS (directly or via reverse proxy)."""
    return (
        request.url.scheme == "https"
        or request.headers.get("x-forwarded-proto") == "https"
    )


def _verify_cookie(request: Request) -> bool:
    """Check if the API key cookie is valid (constant-time)."""
    cookie_key = request.cookies.get(COOKIE_NAME, "")
    expected = request.app.state.settings.niles_api_key
    if not cookie_key or len(cookie_key) > 256:
        # Always run compare_digest to prevent timing leaks (#4)
        hmac.compare_digest("dummy-constant-value", expected)
        return False
    return hmac.compare_digest(cookie_key, expected)


def _verify_csrf(request: Request) -> bool:
    """Validate double-submit CSRF token (cookie vs header)."""
    csrf_cookie = request.cookies.get(CSRF_COOKIE_NAME, "")
    csrf_header = request.headers.get("x-csrf-token", "")
    if not csrf_cookie or not csrf_header:
        return False
    return hmac.compare_digest(csrf_cookie, csrf_header)


def _ensure_csrf_cookie(request: Request, response: Response) -> None:
    """Set CSRF cookie if not already present."""
    if CSRF_COOKIE_NAME not in request.cookies:
        is_secure = _is_secure_context(request)
        response.set_cookie(
            CSRF_COOKIE_NAME, secrets.token_urlsafe(32),
            max_age=COOKIE_MAX_AGE, httponly=False,
            secure=is_secure, samesite="strict",
        )


def _require_auth_and_csrf(request: Request) -> Response | None:
    """Check auth cookie + CSRF token for POST endpoints. Returns error Response or None."""
    if not _verify_cookie(request):
        return Response(status_code=401, headers={"HX-Redirect": "/ui/login"})
    if not _verify_csrf(request):
        return Response(status_code=403, headers={"HX-Redirect": "/ui/login"})
    return None


def _safe_settings_dict(settings) -> dict:
    """Build a safe dict of settings values for templates (no __dict__ access)."""
    feature_flags = {}
    for key in [
        "feature_whatsapp_auto_reply", "feature_tool_send_whatsapp",
        "feature_carddav_sync", "feature_caldav_sync",
    ]:
        feature_flags[key] = getattr(settings, key)

    text_settings = {}
    for key in ["llm_base_url", "llm_model"]:
        text_settings[key] = getattr(settings, key)

    infra = {
        "postgres_host": settings.postgres_host,
        "postgres_port": settings.postgres_port,
        "postgres_db": settings.postgres_db,
        "postgres_user": settings.postgres_user,
        "postgres_password": "********",
        "evolution_api_url": settings.evolution_api_url,
        "evolution_api_key": "********",
        "carddav_url": settings.carddav_url,
        "carddav_user": settings.carddav_user,
        "carddav_password": "********" if settings.carddav_password else "(not set)",
        "caldav_url": settings.caldav_url,
        "caldav_user": settings.caldav_user,
        "caldav_password": "********" if settings.caldav_password else "(not set)",
    }

    return {
        "feature_flags": feature_flags,
        "text_settings": text_settings,
        "general": {"timezone": settings.timezone, "log_level": settings.log_level},
        "infra": infra,
    }


# --- Page routes (return full HTML pages) ---


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Show API key login form."""
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login")
async def login_submit(request: Request, api_key: str = Form(...)):
    """Validate API key and set auth cookie."""
    client_ip = request.client.host if request.client else "unknown"

    # Login rate limiting (#6)
    if not _check_login_rate(client_ip):
        return templates.TemplateResponse(
            request, "login.html",
            {"error": "Zu viele Anmeldeversuche. Bitte warte 5 Minuten."},
            status_code=429,
        )

    _record_login_attempt(client_ip)

    expected = request.app.state.settings.niles_api_key
    if not api_key or len(api_key) > 256 or not hmac.compare_digest(api_key, expected):
        return templates.TemplateResponse(
            request, "login.html",
            {"error": "Ungueltiger API-Key"},
            status_code=401,
        )

    is_secure = _is_secure_context(request)
    response = RedirectResponse(url="/ui/chat", status_code=303)
    response.set_cookie(
        COOKIE_NAME, api_key,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        secure=is_secure,
        samesite="strict",
    )
    # Set CSRF token cookie (#2)
    response.set_cookie(
        CSRF_COOKIE_NAME, secrets.token_urlsafe(32),
        max_age=COOKIE_MAX_AGE,
        httponly=False,
        secure=is_secure,
        samesite="strict",
    )
    return response


@router.get("/logout")
async def logout():
    """Clear auth cookie and CSRF cookie, redirect to login."""
    response = RedirectResponse(url="/ui/login", status_code=303)
    response.delete_cookie(COOKIE_NAME)
    response.delete_cookie(CSRF_COOKIE_NAME)
    return response


@router.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    """Chat page with conversation history (paginated)."""
    if not _verify_cookie(request):
        return RedirectResponse(url="/ui/login", status_code=303)
    history = request.app.state.history
    messages = await history.get_recent(WEB_CHAT_ID, limit=_CHAT_PAGE_SIZE)
    has_more = len(messages) == _CHAT_PAGE_SIZE
    response = templates.TemplateResponse(request, "chat.html", {
        "messages": messages,
        "has_more": has_more,
        "next_offset": _CHAT_PAGE_SIZE,
        "active_page": "chat",
    })
    _ensure_csrf_cookie(request, response)
    return response


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """Settings dashboard (safe dict, no __dict__ access)."""
    if not _verify_cookie(request):
        return RedirectResponse(url="/ui/login", status_code=303)
    safe = _safe_settings_dict(request.app.state.settings)
    response = templates.TemplateResponse(request, "settings.html", {
        **safe,
        "active_page": "settings",
    })
    _ensure_csrf_cookie(request, response)
    return response


# --- htmx fragment endpoints ---


@router.get("/api/chat/history", response_class=HTMLResponse)
async def chat_history(
    request: Request,
    offset: int = Query(default=0, ge=0),
):
    """Load older chat messages (pagination)."""
    if not _verify_cookie(request):
        return Response(status_code=401, headers={"HX-Redirect": "/ui/login"})
    history = request.app.state.history
    messages = await history.get_recent(WEB_CHAT_ID, limit=_CHAT_PAGE_SIZE, offset=offset)
    has_more = len(messages) == _CHAT_PAGE_SIZE
    return templates.TemplateResponse(request, "fragments/history.html", {
        "messages": messages,
        "has_more": has_more,
        "next_offset": offset + _CHAT_PAGE_SIZE,
    })


@router.post("/api/chat", response_class=HTMLResponse)
async def chat_send(request: Request, message: str = Form(...)):
    """Process a chat message, return HTML fragment with user + assistant bubbles."""
    error = _require_auth_and_csrf(request)
    if error:
        return error

    agent = request.app.state.agent
    event = {
        "type": "web",
        "from": WEB_CHAT_ID,
        "content": message,
        "metadata": {},
    }

    try:
        response_text = await agent.process_event(event)
    except Exception:
        logger.exception("Agent error processing web chat message")
        response_text = (
            "Entschuldigung, es ist ein Fehler aufgetreten. "
            "Bitte versuche es erneut."
        )

    return templates.TemplateResponse(request, "fragments/message.html", {
        "user_message": message,
        "assistant_message": response_text,
    })


@router.post("/api/chat/clear", response_class=HTMLResponse)
async def chat_clear(request: Request):
    """Clear chat history, return empty content."""
    error = _require_auth_and_csrf(request)
    if error:
        return error
    history = request.app.state.history
    await history.clear(WEB_CHAT_ID)
    return HTMLResponse("")


@router.post("/api/settings/{key}", response_class=HTMLResponse)
async def update_setting(request: Request, key: str, value: str = Form(...)):
    """Update a single runtime setting."""
    error = _require_auth_and_csrf(request)
    if error:
        return error

    settings_store = request.app.state.settings_store
    settings = request.app.state.settings

    # Convert value to appropriate type
    if key.startswith("feature_"):
        parsed_value = value.lower() in ("true", "1", "on")
    else:
        parsed_value = value

    try:
        await settings_store.set(key, parsed_value)
        request.app.state.settings = apply_overrides(settings, {key: parsed_value})
    except ValueError as e:
        return templates.TemplateResponse(request, "fragments/toast.html", {
            "message": str(e),
            "toast_type": "error",
        })

    return templates.TemplateResponse(request, "fragments/toast.html", {
        "message": f"'{key}' gespeichert",
        "toast_type": "success",
    })
