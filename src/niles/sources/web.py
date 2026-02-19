"""Web GUI router -- htmx-powered chat and settings UI.

UI language: German (de) -- intentional design choice for the target user.
"""

import hmac
import json
import logging
import secrets
import time
import urllib.parse
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import APIRouter, Form, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from ..config import apply_overrides

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ui", tags=["web-ui"])

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

# --- Constants ---

SESSION_COOKIE_NAME = "niles_session"
CSRF_COOKIE_NAME = "niles_csrf"
COOKIE_MAX_AGE = 30 * 24 * 3600  # 30 days

_CHAT_PAGE_SIZE = 20

# Google OAuth endpoints
_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"

# --- Login rate limiting ---
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


def _get_serializer(request: Request) -> URLSafeTimedSerializer:
    """Get the session serializer using dedicated session_secret."""
    return URLSafeTimedSerializer(request.app.state.settings.session_secret)


def _get_session_user(request: Request) -> dict | None:
    """Verify signed session cookie and return user data or None.

    Returns dict with keys: uid, email, display_name, avatar_url.
    """
    token = request.cookies.get(SESSION_COOKIE_NAME, "")
    if not token or len(token) > 4096:
        return None
    try:
        serializer = _get_serializer(request)
        return serializer.loads(token, max_age=COOKIE_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None


def _create_session_cookie(request: Request, response: Response, user: dict) -> None:
    """Set signed session cookie with user data."""
    serializer = _get_serializer(request)
    token = serializer.dumps({
        "uid": user["id"],
        "email": user["email"],
        "display_name": user.get("display_name", user["email"]),
        "avatar_url": user.get("avatar_url") or "",
    })
    is_secure = _is_secure_context(request)
    response.set_cookie(
        SESSION_COOKIE_NAME, token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        secure=is_secure,
        samesite="lax",  # "lax" needed for OAuth redirect flow
    )


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


def _set_csrf_cookie(request: Request, response: Response) -> None:
    """Always set a fresh CSRF cookie (used after login)."""
    is_secure = _is_secure_context(request)
    response.set_cookie(
        CSRF_COOKIE_NAME, secrets.token_urlsafe(32),
        max_age=COOKIE_MAX_AGE, httponly=False,
        secure=is_secure, samesite="strict",
    )


def _require_auth_and_csrf(request: Request) -> tuple[dict | None, Response | None]:
    """Check session + CSRF. Returns (user_dict, None) or (None, error_response)."""
    user = _get_session_user(request)
    if user is None:
        return None, Response(status_code=401, headers={"HX-Redirect": "/ui/login"})
    if not _verify_csrf(request):
        return None, Response(status_code=403, headers={"HX-Redirect": "/ui/login"})
    return user, None


def _user_chat_id(user: dict) -> str:
    """Per-user chat ID for conversation history."""
    return f"web-user-{user['uid']}"


def _google_configured(request: Request) -> bool:
    """Check if Google OAuth credentials are configured."""
    s = request.app.state.settings
    return bool(s.google_client_id and s.google_client_secret)


def _build_redirect_uri(request: Request) -> str:
    """Build Google OAuth redirect URI. Uses base_url if configured, else request headers."""
    base_url = request.app.state.settings.base_url
    if base_url:
        return f"{base_url.rstrip('/')}/ui/callback/google"
    # Fallback: derive from request headers (less secure behind reverse proxy)
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get(
        "x-forwarded-host", request.headers.get("host", "localhost"),
    )
    return f"{scheme}://{host}/ui/callback/google"


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
        "caldav_enabled": settings.feature_caldav_sync,
    }


# --- Page routes ---


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Login page: Google OAuth button or API-key form (fallback)."""
    return templates.TemplateResponse(request, "login.html", {
        "error": None,
        "google_configured": _google_configured(request),
    })


@router.post("/login")
async def login_submit(request: Request, api_key: str = Form(...)):
    """Validate API key and set session cookie (fallback when no Google OAuth)."""
    client_ip = request.client.host if request.client else "unknown"

    if not _check_login_rate(client_ip):
        return templates.TemplateResponse(
            request, "login.html",
            {
                "error": "Zu viele Anmeldeversuche. Bitte warte 5 Minuten.",
                "google_configured": _google_configured(request),
            },
            status_code=429,
        )

    _record_login_attempt(client_ip)

    expected = request.app.state.settings.niles_api_key
    if not api_key or len(api_key) > 256 or not hmac.compare_digest(api_key, expected):
        return templates.TemplateResponse(
            request, "login.html",
            {
                "error": "Ungueltiger API-Key",
                "google_configured": _google_configured(request),
            },
            status_code=401,
        )

    # Create local admin session (no DB user for API-key login)
    user = {"id": 0, "email": "admin@local", "display_name": "Admin", "avatar_url": ""}
    response = RedirectResponse(url="/ui/chat", status_code=303)
    _create_session_cookie(request, response, user)
    _set_csrf_cookie(request, response)
    return response


# --- Google OAuth routes ---


@router.get("/login/google")
async def login_google(request: Request):
    """Redirect to Google OAuth consent screen."""
    if not _google_configured(request):
        return RedirectResponse(url="/ui/login", status_code=303)

    state = secrets.token_urlsafe(32)
    redirect_uri = _build_redirect_uri(request)
    settings = request.app.state.settings

    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "prompt": "select_account",
    }
    auth_url = f"{_GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}"

    response = RedirectResponse(url=auth_url, status_code=303)
    response.set_cookie(
        "oauth_state", state,
        max_age=600, httponly=True,
        secure=_is_secure_context(request), samesite="lax",
    )
    return response


@router.get("/callback/google")
async def callback_google(
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
):
    """Handle Google OAuth callback: exchange code, create/find user, set session."""
    gc = _google_configured(request)

    if error:
        logger.warning("Google OAuth error: %s", error)
        # Map known error codes to safe user-facing messages
        error_messages = {
            "access_denied": "Zugriff verweigert.",
            "invalid_scope": "Ungueltige Berechtigungen.",
        }
        safe_msg = error_messages.get(error, "Bitte erneut versuchen.")
        return templates.TemplateResponse(request, "login.html", {
            "error": f"Google Login fehlgeschlagen: {safe_msg}",
            "google_configured": gc,
        })

    # Verify state parameter (CSRF protection for OAuth)
    stored_state = request.cookies.get("oauth_state", "")
    if not state or not stored_state or not hmac.compare_digest(state, stored_state):
        return templates.TemplateResponse(request, "login.html", {
            "error": "Ungueltiger OAuth-State. Bitte erneut versuchen.",
            "google_configured": gc,
        })

    settings = request.app.state.settings
    redirect_uri = _build_redirect_uri(request)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Exchange authorization code for tokens
            token_resp = await client.post(_GOOGLE_TOKEN_URL, data={
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            })
            if token_resp.status_code != 200:
                logger.error("Google token exchange failed: %s", token_resp.text)
                return templates.TemplateResponse(request, "login.html", {
                    "error": "Token-Austausch fehlgeschlagen.",
                    "google_configured": gc,
                })
            tokens = token_resp.json()

            # Get user info from Google
            userinfo_resp = await client.get(_GOOGLE_USERINFO_URL, headers={
                "Authorization": f"Bearer {tokens['access_token']}",
            })
            if userinfo_resp.status_code != 200:
                logger.error("Google userinfo failed: %s", userinfo_resp.text)
                return templates.TemplateResponse(request, "login.html", {
                    "error": "Benutzerinformationen konnten nicht abgerufen werden.",
                    "google_configured": gc,
                })
            userinfo = userinfo_resp.json()
    except httpx.HTTPError as e:
        logger.error("Google OAuth HTTP error: %s", e)
        return templates.TemplateResponse(request, "login.html", {
            "error": "Verbindung zu Google fehlgeschlagen.",
            "google_configured": gc,
        })

    email = userinfo.get("email", "")
    if not email:
        return templates.TemplateResponse(request, "login.html", {
            "error": "Keine E-Mail-Adresse von Google erhalten.",
            "google_configured": gc,
        })

    if not userinfo.get("verified_email", userinfo.get("email_verified", False)):
        return templates.TemplateResponse(request, "login.html", {
            "error": "E-Mail-Adresse nicht verifiziert.",
            "google_configured": gc,
        })

    # Check allowed emails whitelist
    if settings.google_allowed_emails:
        allowed = [
            e.strip().lower()
            for e in settings.google_allowed_emails.split(",")
            if e.strip()
        ]
        if email.lower() not in allowed:
            logger.warning("Google login rejected for %s (not in allowed list)", email)
            return templates.TemplateResponse(request, "login.html", {
                "error": "Diese E-Mail-Adresse ist nicht berechtigt.",
                "google_configured": gc,
            })

    # Create or update user in DB
    user_store = request.app.state.user_store
    user = await user_store.create_or_update(
        email=email,
        display_name=userinfo.get("name", email),
        avatar_url=userinfo.get("picture"),
    )
    logger.info("Google login: %s (user_id=%d)", email, user["id"])

    response = RedirectResponse(url="/ui/chat", status_code=303)
    _create_session_cookie(request, response, user)
    _set_csrf_cookie(request, response)
    response.delete_cookie("oauth_state")
    return response


@router.post("/logout")
async def logout(request: Request):
    """Clear session and CSRF cookies (POST to prevent logout CSRF)."""
    # htmx requests need HX-Redirect header; regular requests get 303
    if request.headers.get("hx-request"):
        response = Response(status_code=200, headers={"HX-Redirect": "/ui/login"})
    else:
        response = RedirectResponse(url="/ui/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE_NAME)
    response.delete_cookie(CSRF_COOKIE_NAME)
    response.delete_cookie("oauth_state")
    return response


@router.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    """Chat page with per-user conversation history (paginated)."""
    user = _get_session_user(request)
    if user is None:
        return RedirectResponse(url="/ui/login", status_code=303)

    chat_id = _user_chat_id(user)
    history = request.app.state.history
    messages = await history.get_recent(chat_id, limit=_CHAT_PAGE_SIZE)
    has_more = len(messages) == _CHAT_PAGE_SIZE

    response = templates.TemplateResponse(request, "chat.html", {
        "messages": messages,
        "has_more": has_more,
        "next_offset": _CHAT_PAGE_SIZE,
        "active_page": "chat",
        "user": user,
    })
    _ensure_csrf_cookie(request, response)
    return response


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """Settings dashboard (safe dict, no __dict__ access)."""
    user = _get_session_user(request)
    if user is None:
        return RedirectResponse(url="/ui/login", status_code=303)

    safe = _safe_settings_dict(request.app.state.settings)
    response = templates.TemplateResponse(request, "settings.html", {
        **safe,
        "active_page": "settings",
        "user": user,
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
    user = _get_session_user(request)
    if user is None:
        return Response(status_code=401, headers={"HX-Redirect": "/ui/login"})

    chat_id = _user_chat_id(user)
    history = request.app.state.history
    messages = await history.get_recent(chat_id, limit=_CHAT_PAGE_SIZE, offset=offset)
    has_more = len(messages) == _CHAT_PAGE_SIZE
    return templates.TemplateResponse(request, "fragments/history.html", {
        "messages": messages,
        "has_more": has_more,
        "next_offset": offset + _CHAT_PAGE_SIZE,
    })


@router.post("/api/chat", response_class=HTMLResponse)
async def chat_send(request: Request, message: str = Form(...)):
    """Process a chat message, return HTML fragment with user + assistant bubbles."""
    user, error = _require_auth_and_csrf(request)
    if error:
        return error

    if len(message) > 2000:
        return Response(status_code=400, content="Nachricht zu lang (max. 2000 Zeichen).")

    chat_id = _user_chat_id(user)
    agent = request.app.state.agent
    # ISO timestamp for client-side local-time formatting
    now = datetime.now(timezone.utc).isoformat()
    event = {
        "type": "web",
        "from": chat_id,
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
        "user_timestamp": now,
        "assistant_timestamp": datetime.now(timezone.utc).isoformat(),
    })


@router.post("/api/chat/stream")
async def chat_stream(request: Request, message: str = Form(...)):
    """Process a chat message via SSE streaming.

    Uses fetch+ReadableStream on the client (not EventSource), so native SSE
    reconnect semantics (retry/last-event-id) don't apply.  A dropped
    connection simply ends the stream; the user re-sends if needed.
    """
    user, error = _require_auth_and_csrf(request)
    if error:
        return error

    if len(message) > 2000:
        return Response(status_code=400, content="Nachricht zu lang (max. 2000 Zeichen).")

    chat_id = _user_chat_id(user)
    agent = request.app.state.agent
    event = {
        "type": "web",
        "from": chat_id,
        "content": message,
        "metadata": {},
    }

    async def event_generator():
        try:
            async for item in agent.process_event_stream(event):
                data = json.dumps(item, ensure_ascii=False)
                yield f"data: {data}\n\n"
        except Exception:
            logger.exception("Agent streaming error")
            err = json.dumps({"type": "chunk", "text": "Entschuldigung, ein Fehler ist aufgetreten."})
            yield f"data: {err}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


@router.post("/api/chat/clear", response_class=HTMLResponse)
async def chat_clear(request: Request):
    """Clear chat history for current user."""
    user, error = _require_auth_and_csrf(request)
    if error:
        return error

    chat_id = _user_chat_id(user)
    history = request.app.state.history
    await history.clear(chat_id)
    return HTMLResponse("")


@router.post("/api/settings/{key}", response_class=HTMLResponse)
async def update_setting(request: Request, key: str, value: str = Form(...)):
    """Update a single runtime setting."""
    _user, error = _require_auth_and_csrf(request)
    if error:
        return error

    settings_store = request.app.state.settings_store
    settings = request.app.state.settings

    # Validate key exists on settings before touching DB
    if not hasattr(settings, key):
        return templates.TemplateResponse(request, "fragments/toast.html", {
            "message": f"Unbekannte Einstellung: '{key}'",
            "toast_type": "error",
        })

    # Convert value to appropriate type
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
    except ValueError as e:
        return templates.TemplateResponse(request, "fragments/toast.html", {
            "message": str(e),
            "toast_type": "error",
        })

    return templates.TemplateResponse(request, "fragments/toast.html", {
        "message": f"'{key}' gespeichert",
        "toast_type": "success",
    })


@router.get("/api/caldav/calendars", response_class=HTMLResponse)
async def caldav_calendars(request: Request):
    """Discover available CalDAV calendars, return checkboxes fragment."""
    user = _get_session_user(request)
    if user is None:
        return Response(status_code=401, headers={"HX-Redirect": "/ui/login"})

    caldav = getattr(request.app.state, "caldav", None)
    if not caldav:
        return HTMLResponse("<p>CalDAV nicht konfiguriert.</p>")

    try:
        collections = await caldav.discover_collections()
    except Exception:
        logger.exception("CalDAV collection discovery failed")
        return HTMLResponse("<p>Fehler beim Laden der Kalender.</p>")

    # Determine which are currently selected
    selected = caldav.allowed_collections()

    return templates.TemplateResponse(request, "fragments/calendars.html", {
        "collections": collections,
        "selected": selected,
    })
