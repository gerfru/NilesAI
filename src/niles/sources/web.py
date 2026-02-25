"""Web GUI router -- htmx-powered chat and settings UI.

UI language: German (de) -- intentional design choice for the target user.
"""

import asyncio
import hmac
import json
import logging
import secrets
import time
import urllib.parse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import asyncpg
import httpx
from fastapi import APIRouter, Form, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from openai import AsyncOpenAI

from ..config import apply_overrides
from ..sync.google_auth import GOOGLE_TOKEN_URL

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
    token = serializer.dumps(
        {
            "uid": user["id"],
            "email": user["email"],
            "display_name": user.get("display_name", user["email"]),
            "avatar_url": user.get("avatar_url") or "",
        }
    )
    is_secure = _is_secure_context(request)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
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
            CSRF_COOKIE_NAME,
            secrets.token_urlsafe(32),
            max_age=COOKIE_MAX_AGE,
            httponly=False,
            secure=is_secure,
            samesite="strict",
        )


def _set_csrf_cookie(request: Request, response: Response) -> None:
    """Always set a fresh CSRF cookie (used after login)."""
    is_secure = _is_secure_context(request)
    response.set_cookie(
        CSRF_COOKIE_NAME,
        secrets.token_urlsafe(32),
        max_age=COOKIE_MAX_AGE,
        httponly=False,
        secure=is_secure,
        samesite="strict",
    )


async def _require_auth_and_csrf(
    request: Request,
) -> tuple[dict | None, Response | None]:
    """Check session + CSRF + user existence in DB.

    Returns (user_dict, None) or (None, error_response).
    Invalidates session cookie when the user row no longer exists (e.g. after
    a database reset while the browser still holds a signed cookie).
    """
    user = _get_session_user(request)
    if user is None:
        return None, Response(status_code=401, headers={"HX-Redirect": "/ui/login"})
    if not _verify_csrf(request):
        return None, Response(status_code=403, headers={"HX-Redirect": "/ui/login"})

    # Verify user still exists in DB (skip for API-key admin uid=0)
    uid = user.get("uid")
    if uid:  # uid=0 is the synthetic API-key admin; real users have uid > 0
        user_store = getattr(request.app.state, "user_store", None)
        if user_store and await user_store.get_by_id(uid) is None:
            logger.warning("Stale session: user_id=%s not in users table", uid)
            response = Response(status_code=401, headers={"HX-Redirect": "/ui/login"})
            response.delete_cookie(SESSION_COOKIE_NAME)
            response.delete_cookie(CSRF_COOKIE_NAME)
            return None, response

    return user, None


def _user_chat_id(user: dict) -> str:
    """Per-user chat ID for conversation history."""
    return f"web-user-{user['uid']}"


async def _resolve_channel(
    user: dict,
    channel: str,
    wa_store,
    wa_session: dict | None = None,
) -> tuple[str, bool]:
    """Resolve channel name to (chat_id, readonly).

    Returns web-chat as fallback for unknown/invalid channels.
    Accepts an optional pre-fetched wa_session to avoid duplicate DB queries.
    """
    if channel == "whatsapp":
        session = wa_session
        if session is None and wa_store:
            session = await wa_store.get_session(user["uid"])
        if session and session.get("phone_number"):
            chat_id = (
                f"wa-self-{session['phone_number'].replace('+', '').replace(' ', '')}"
            )
            return chat_id, True
    return _user_chat_id(user), False


def _google_configured(request: Request) -> bool:
    """Check if Google OAuth credentials are configured."""
    s = request.app.state.settings
    return bool(s.google_client_id and s.google_client_secret)


def _build_redirect_uri(request: Request, path: str = "/ui/callback/google") -> str:
    """Build Google OAuth redirect URI. Uses base_url if configured, else request headers."""
    base_url = request.app.state.settings.base_url
    if base_url:
        return f"{base_url.rstrip('/')}{path}"
    # Fallback: derive from request headers (less secure behind reverse proxy)
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get(
        "x-forwarded-host",
        request.headers.get("host", "localhost"),
    )
    return f"{scheme}://{host}{path}"


def _safe_settings_dict(settings) -> dict:
    """Build a safe dict of settings values for templates (no __dict__ access)."""
    feature_flags = {}
    for key in [
        "feature_whatsapp_send_others",
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
        "caldav_url (Legacy)": settings.caldav_url,
        "caldav_user (Legacy)": settings.caldav_user,
        "caldav_password (Legacy)": "********"
        if settings.caldav_password
        else "(not set)",
    }

    briefing = {
        "feature_briefing_daily": getattr(settings, "feature_briefing_daily", False),
        "feature_briefing_weekly": getattr(settings, "feature_briefing_weekly", False),
        "briefing_daily_time": getattr(settings, "briefing_daily_time", "07:30"),
        "briefing_weekly_time": getattr(settings, "briefing_weekly_time", "07:15"),
    }

    return {
        "feature_flags": feature_flags,
        "text_settings": text_settings,
        "general": {"timezone": settings.timezone, "log_level": settings.log_level},
        "infra": infra,
        "briefing": briefing,
    }


# --- Page routes ---


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Login page: Google OAuth button or API-key form (fallback)."""
    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "error": None,
            "google_configured": _google_configured(request),
        },
    )


@router.post("/login")
async def login_submit(request: Request, api_key: str = Form(...)):
    """Validate API key and set session cookie (fallback when no Google OAuth)."""
    client_ip = request.client.host if request.client else "unknown"

    if not _check_login_rate(client_ip):
        return templates.TemplateResponse(
            request,
            "login.html",
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
            request,
            "login.html",
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
        "oauth_state",
        state,
        max_age=600,
        httponly=True,
        secure=_is_secure_context(request),
        samesite="lax",
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
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "error": f"Google Login fehlgeschlagen: {safe_msg}",
                "google_configured": gc,
            },
        )

    # Verify state parameter (CSRF protection for OAuth)
    stored_state = request.cookies.get("oauth_state", "")
    if not state or not stored_state or not hmac.compare_digest(state, stored_state):
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "error": "Ungueltiger OAuth-State. Bitte erneut versuchen.",
                "google_configured": gc,
            },
        )

    settings = request.app.state.settings
    redirect_uri = _build_redirect_uri(request)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Exchange authorization code for tokens
            token_resp = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
            if token_resp.status_code != 200:
                logger.error("Google token exchange failed: %s", token_resp.text)
                return templates.TemplateResponse(
                    request,
                    "login.html",
                    {
                        "error": "Token-Austausch fehlgeschlagen.",
                        "google_configured": gc,
                    },
                )
            tokens = token_resp.json()

            # Get user info from Google
            userinfo_resp = await client.get(
                _GOOGLE_USERINFO_URL,
                headers={
                    "Authorization": f"Bearer {tokens['access_token']}",
                },
            )
            if userinfo_resp.status_code != 200:
                logger.error("Google userinfo failed: %s", userinfo_resp.text)
                return templates.TemplateResponse(
                    request,
                    "login.html",
                    {
                        "error": "Benutzerinformationen konnten nicht abgerufen werden.",
                        "google_configured": gc,
                    },
                )
            userinfo = userinfo_resp.json()
    except httpx.HTTPError as e:
        logger.error("Google OAuth HTTP error: %s", e)
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "error": "Verbindung zu Google fehlgeschlagen.",
                "google_configured": gc,
            },
        )

    email = userinfo.get("email", "")
    if not email:
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "error": "Keine E-Mail-Adresse von Google erhalten.",
                "google_configured": gc,
            },
        )

    if not userinfo.get("verified_email", userinfo.get("email_verified", False)):
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "error": "E-Mail-Adresse nicht verifiziert.",
                "google_configured": gc,
            },
        )

    # Check allowed emails whitelist
    if settings.google_allowed_emails:
        allowed = [
            e.strip().lower()
            for e in settings.google_allowed_emails.split(",")
            if e.strip()
        ]
        if email.lower() not in allowed:
            logger.warning("Google login rejected for %s (not in allowed list)", email)
            return templates.TemplateResponse(
                request,
                "login.html",
                {
                    "error": "Diese E-Mail-Adresse ist nicht berechtigt.",
                    "google_configured": gc,
                },
            )

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
async def chat_page(
    request: Request,
    channel: str = Query(default="web"),
):
    """Chat page with channel selection and per-user conversation history."""
    user = _get_session_user(request)
    if user is None:
        return RedirectResponse(url="/ui/login", status_code=303)

    wa_store = getattr(request.app.state, "wa_store", None)

    # Fetch session once, reuse for channel resolution and tab visibility
    wa_session = None
    if wa_store:
        wa_session = await wa_store.get_session(user["uid"])

    chat_id, readonly = await _resolve_channel(user, channel, wa_store, wa_session)
    history = request.app.state.history
    messages = await history.get_recent(chat_id, limit=_CHAT_PAGE_SIZE)
    has_more = len(messages) == _CHAT_PAGE_SIZE

    # Determine available channels (WhatsApp only if connected with phone)
    available_channels = [("web", "Web-Chat")]
    if (
        wa_session
        and wa_session.get("phone_number")
        and wa_session["status"] == "connected"
    ):
        available_channels.append(("whatsapp", "WhatsApp"))

    response = templates.TemplateResponse(
        request,
        "chat.html",
        {
            "messages": messages,
            "has_more": has_more,
            "next_offset": _CHAT_PAGE_SIZE,
            "active_page": "chat",
            "user": user,
            "channel": channel if not readonly or channel == "whatsapp" else "web",
            "readonly": readonly,
            "available_channels": available_channels,
        },
    )
    _ensure_csrf_cookie(request, response)
    return response


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, error: str = Query(default="")):
    """Settings dashboard (safe dict, no __dict__ access)."""
    user = _get_session_user(request)
    if user is None:
        return RedirectResponse(url="/ui/login", status_code=303)

    # Map error codes to user-visible messages
    error_msg = ""
    if error == "calendar_connect_failed":
        error_msg = "Google Kalender-Verbindung fehlgeschlagen. Bitte erneut versuchen."

    safe = _safe_settings_dict(request.app.state.settings)
    response = templates.TemplateResponse(
        request,
        "settings.html",
        {
            **safe,
            "active_page": "settings",
            "user": user,
            "google_configured": _google_configured(request),
            "calendar_error": error_msg,
        },
    )
    _ensure_csrf_cookie(request, response)
    return response


# --- htmx fragment endpoints ---


@router.get("/api/chat/history", response_class=HTMLResponse)
async def chat_history(
    request: Request,
    offset: int = Query(default=0, ge=0),
    channel: str = Query(default="web"),
):
    """Load older chat messages (pagination), channel-aware."""
    user = _get_session_user(request)
    if user is None:
        return Response(status_code=401, headers={"HX-Redirect": "/ui/login"})

    wa_store = getattr(request.app.state, "wa_store", None)
    chat_id, _readonly = await _resolve_channel(user, channel, wa_store)
    history = request.app.state.history
    messages = await history.get_recent(chat_id, limit=_CHAT_PAGE_SIZE, offset=offset)
    has_more = len(messages) == _CHAT_PAGE_SIZE
    return templates.TemplateResponse(
        request,
        "fragments/history.html",
        {
            "messages": messages,
            "has_more": has_more,
            "next_offset": offset + _CHAT_PAGE_SIZE,
            "user": user,
            "channel": channel,
        },
    )


@router.post("/api/chat", response_class=HTMLResponse)
async def chat_send(request: Request, message: str = Form(...)):
    """Process a chat message, return HTML fragment with user + assistant bubbles."""
    user, error = await _require_auth_and_csrf(request)
    if error:
        return error

    if len(message) > 2000:
        return Response(
            status_code=400, content="Nachricht zu lang (max. 2000 Zeichen)."
        )

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
            "Entschuldigung, es ist ein Fehler aufgetreten. Bitte versuche es erneut."
        )

    return templates.TemplateResponse(
        request,
        "fragments/message.html",
        {
            "user_message": message,
            "assistant_message": response_text,
            "user_timestamp": now,
            "assistant_timestamp": datetime.now(timezone.utc).isoformat(),
            "user": user,
        },
    )


@router.post("/api/chat/stream")
async def chat_stream(request: Request, message: str = Form(...)):
    """Process a chat message via SSE streaming.

    Uses fetch+ReadableStream on the client (not EventSource), so native SSE
    reconnect semantics (retry/last-event-id) don't apply.  A dropped
    connection simply ends the stream; the user re-sends if needed.
    """
    user, error = await _require_auth_and_csrf(request)
    if error:
        return error

    if len(message) > 2000:
        return Response(
            status_code=400, content="Nachricht zu lang (max. 2000 Zeichen)."
        )

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
            err = json.dumps(
                {"type": "chunk", "text": "Entschuldigung, ein Fehler ist aufgetreten."}
            )
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
    user, error = await _require_auth_and_csrf(request)
    if error:
        return error

    chat_id = _user_chat_id(user)
    history = request.app.state.history
    await history.clear(chat_id)
    return HTMLResponse("")


@router.post("/api/settings/{key}", response_class=HTMLResponse)
async def update_setting(request: Request, key: str, value: str = Form(...)):
    """Update a single runtime setting."""
    _user, error = await _require_auth_and_csrf(request)
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


@router.post("/api/briefing/test/{briefing_type}", response_class=HTMLResponse)
async def briefing_test(request: Request, briefing_type: str):
    """Manually trigger a briefing (generate + send via WhatsApp)."""
    _user, error = await _require_auth_and_csrf(request)
    if error:
        return error

    if briefing_type not in ("daily", "weekly"):
        return templates.TemplateResponse(
            request,
            "fragments/toast.html",
            {
                "message": "Unbekannter Briefing-Typ",
                "toast_type": "error",
            },
        )

    from ..jobs.briefing import send_daily_briefing, send_weekly_briefing

    try:
        if briefing_type == "daily":
            sent = await send_daily_briefing(request.app.state)
        else:
            sent = await send_weekly_briefing(request.app.state)
    except Exception:
        logger.exception("Manual briefing test failed")
        return templates.TemplateResponse(
            request,
            "fragments/toast.html",
            {
                "message": "Briefing fehlgeschlagen (siehe Logs)",
                "toast_type": "error",
            },
        )

    if not sent:
        return templates.TemplateResponse(
            request,
            "fragments/toast.html",
            {
                "message": "Kein WhatsApp verbunden",
                "toast_type": "error",
            },
        )

    return templates.TemplateResponse(
        request,
        "fragments/toast.html",
        {
            "message": f"{'Tages' if briefing_type == 'daily' else 'Wochen'}briefing gesendet",
            "toast_type": "success",
        },
    )


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

    return templates.TemplateResponse(
        request,
        "fragments/calendars.html",
        {
            "collections": collections,
            "selected": selected,
        },
    )


# --- Calendar source management ---


@router.get("/api/calendar/sources", response_class=HTMLResponse)
async def calendar_sources_list(request: Request):
    """Return htmx fragment listing all calendar sources."""
    user = _get_session_user(request)
    if user is None:
        return Response(status_code=401, headers={"HX-Redirect": "/ui/login"})

    manager = getattr(request.app.state, "calendar_manager", None)
    if not manager:
        return templates.TemplateResponse(
            request, "fragments/calendar_unavailable.html", {}
        )

    sources = await manager.get_sources()
    return templates.TemplateResponse(
        request,
        "fragments/calendar_sources.html",
        {
            "sources": sources,
        },
    )


@router.post("/api/calendar/sources", response_class=HTMLResponse)
async def calendar_source_add(
    request: Request,
    source_type: str = Form(...),
    name: str = Form(""),
    url: str = Form(...),
    auth_user: str = Form(""),
    auth_password: str = Form(""),
):
    """Add a new calendar source and return updated sources list."""
    _user, error = await _require_auth_and_csrf(request)
    if error:
        return error

    manager = getattr(request.app.state, "calendar_manager", None)
    if not manager:
        return HTMLResponse(
            '<p class="text-sm text-red-500">Kalender-Manager nicht verfuegbar.</p>'
        )

    # Default name from URL if not provided
    if not name.strip():
        name = url.split("//", 1)[-1].split("/")[0][:80]

    writable = source_type in ("caldav", "google")

    try:
        await manager.add_source(
            name=name.strip(),
            url=url.strip(),
            source_type=source_type,
            writable=writable,
            auth_user=auth_user.strip() or None,
            auth_password=auth_password or None,
        )
    except asyncpg.UniqueViolationError:
        sources = await manager.get_sources()
        return templates.TemplateResponse(
            request,
            "fragments/calendar_sources.html",
            {
                "sources": sources,
                "error": "Diese Quelle existiert bereits.",
            },
        )
    except ValueError as exc:
        sources = await manager.get_sources()
        return templates.TemplateResponse(
            request,
            "fragments/calendar_sources.html",
            {
                "sources": sources,
                "error": str(exc),
            },
        )

    sources = await manager.get_sources()
    return templates.TemplateResponse(
        request,
        "fragments/calendar_sources.html",
        {
            "sources": sources,
        },
    )


@router.delete("/api/calendar/sources/{source_id}", response_class=HTMLResponse)
async def calendar_source_remove(request: Request, source_id: int):
    """Remove a calendar source (CASCADE deletes events)."""
    _user, error = await _require_auth_and_csrf(request)
    if error:
        return error

    manager = getattr(request.app.state, "calendar_manager", None)
    if not manager:
        return HTMLResponse(
            '<p class="text-sm text-red-500">Kalender-Manager nicht verfuegbar.</p>'
        )

    removed = await manager.remove_source(source_id)
    sources = await manager.get_sources()
    ctx = {"sources": sources}
    if not removed:
        ctx["error"] = "Quelle nicht gefunden."
    return templates.TemplateResponse(request, "fragments/calendar_sources.html", ctx)


@router.post("/api/calendar/sources/{source_id}/sync", response_class=HTMLResponse)
async def calendar_source_sync(request: Request, source_id: int):
    """Sync a single calendar source."""
    _user, error = await _require_auth_and_csrf(request)
    if error:
        return error

    manager = getattr(request.app.state, "calendar_manager", None)
    if not manager:
        return HTMLResponse(
            '<p class="text-sm text-red-500">Kalender-Manager nicht verfuegbar.</p>'
        )

    ctx: dict = {}
    try:
        count = await manager.sync_source(source_id)
        if count is None:
            ctx["error"] = "Quelle nicht gefunden oder deaktiviert."
    except Exception:
        logger.exception("Manual sync failed for source %d", source_id)

    sources = await manager.get_sources()
    ctx["sources"] = sources
    return templates.TemplateResponse(request, "fragments/calendar_sources.html", ctx)


# --- Google Calendar OAuth (Phase B) ---

_GOOGLE_CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar"
_GOOGLE_CALENDAR_LIST_URL = (
    "https://www.googleapis.com/calendar/v3/users/me/calendarList"
)
_GCAL_OAUTH_COOKIE = "gcal_oauth_state"


def _log_task_exception(task: asyncio.Task) -> None:
    """Done-callback for fire-and-forget tasks: log exceptions instead of losing them."""
    if not task.cancelled() and task.exception():
        logger.error("Background task failed: %s", task.exception())


@router.get("/api/calendar/google/connect")
async def google_calendar_connect(request: Request):
    """Redirect to Google OAuth with Calendar scope."""
    user = _get_session_user(request)
    if user is None:
        return RedirectResponse(url="/ui/login", status_code=303)

    if not _google_configured(request):
        return RedirectResponse(url="/ui/settings", status_code=303)

    settings = request.app.state.settings
    state = secrets.token_urlsafe(32)
    redirect_uri = _build_redirect_uri(request, "/ui/callback/google/calendar")

    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": _GOOGLE_CALENDAR_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    auth_url = f"{_GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}"

    response = RedirectResponse(url=auth_url, status_code=303)
    response.set_cookie(
        _GCAL_OAUTH_COOKIE,
        state,
        max_age=600,
        httponly=True,
        secure=_is_secure_context(request),
        samesite="lax",
    )
    return response


@router.get("/callback/google/calendar")
async def callback_google_calendar(
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
):
    """Handle Google Calendar OAuth callback.

    Exchanges code for tokens, discovers calendars via Google Calendar API,
    and creates calendar_sources entries for each discovered calendar.
    """
    _fail_url = "/ui/settings?error=calendar_connect_failed"

    # Verify user session (match connect endpoint auth requirement)
    user = _get_session_user(request)
    if user is None:
        return RedirectResponse(url="/ui/login", status_code=303)

    # Validate OAuth state
    stored_state = request.cookies.get(_GCAL_OAUTH_COOKIE, "")
    if not state or not stored_state or not hmac.compare_digest(state, stored_state):
        logger.warning("Google Calendar OAuth: invalid state parameter")
        return RedirectResponse(url=_fail_url, status_code=303)

    if error or not code:
        logger.warning("Google Calendar OAuth error: %s", error or "no code")
        return RedirectResponse(url=_fail_url, status_code=303)

    settings = request.app.state.settings
    redirect_uri = _build_redirect_uri(request, "/ui/callback/google/calendar")

    # Exchange authorization code for tokens
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=30,
        )

    if token_resp.status_code != 200:
        logger.error(
            "Google Calendar token exchange failed: %d", token_resp.status_code
        )
        return RedirectResponse(url=_fail_url, status_code=303)

    tokens = token_resp.json()
    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")
    expires_in = tokens.get("expires_in", 3600)

    if not access_token or not refresh_token:
        logger.error(
            "Google Calendar OAuth: missing tokens (refresh_token=%s)",
            "present" if refresh_token else "absent",
        )
        return RedirectResponse(url=_fail_url, status_code=303)

    token_expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    # Discover calendars via Google Calendar REST API
    async with httpx.AsyncClient() as client:
        cal_resp = await client.get(
            _GOOGLE_CALENDAR_LIST_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=30,
        )

    if cal_resp.status_code != 200:
        logger.error("Google Calendar list failed: %d", cal_resp.status_code)
        return RedirectResponse(url=_fail_url, status_code=303)

    calendars = cal_resp.json().get("items", [])
    manager = getattr(request.app.state, "calendar_manager", None)
    if not manager:
        return RedirectResponse(url=_fail_url, status_code=303)

    added = 0
    for cal in calendars:
        cal_id = cal.get("id", "")
        summary = cal.get("summary", cal_id)
        access_role = cal.get("accessRole", "reader")
        writable = access_role in ("owner", "writer")

        # Build Google CalDAV URL
        encoded_id = urllib.parse.quote(cal_id, safe="")
        caldav_url = (
            f"https://apidata.googleusercontent.com/caldav/v2/{encoded_id}/events/"
        )

        try:
            await manager.add_source(
                name=summary,
                url=caldav_url,
                source_type="google",
                writable=writable,
                google_refresh_token=refresh_token,
                google_token_expiry=token_expiry,
            )
            added += 1
        except asyncpg.UniqueViolationError:
            logger.debug("Skipping calendar %s (already exists)", cal_id)
        except Exception:
            logger.warning("Failed to add calendar %s", cal_id, exc_info=True)

    logger.info("Google Calendar OAuth: added %d calendar(s)", added)

    # Trigger initial sync in background (store reference to prevent GC)
    if added > 0:
        task = asyncio.create_task(manager.sync_all())
        task.add_done_callback(_log_task_exception)

    response = RedirectResponse(url="/ui/settings", status_code=303)
    response.delete_cookie(_GCAL_OAUTH_COOKIE)
    return response


# --- WhatsApp session management ---


_WA_REQUIRES_GOOGLE = (
    '<p class="text-sm text-zinc-500 dark:text-zinc-400 py-2">'
    "WhatsApp-Verknuepfung erfordert einen Google-Login.</p>"
)


@router.get("/api/whatsapp/status", response_class=HTMLResponse)
async def whatsapp_status(request: Request):
    """Return WhatsApp connection status fragment."""
    user = _get_session_user(request)
    if user is None:
        return Response(status_code=401, headers={"HX-Redirect": "/ui/login"})

    # API-key admin (uid=0) has no row in users table → FK would violate
    if user.get("uid") == 0:
        return HTMLResponse(_WA_REQUIRES_GOOGLE)

    wa_store = getattr(request.app.state, "wa_store", None)
    if not wa_store:
        return HTMLResponse(
            '<p class="text-sm text-zinc-500 dark:text-zinc-400 py-2">'
            "WhatsApp nicht verfuegbar.</p>"
        )

    session = await wa_store.get_session(user["uid"])
    ctx: dict = {"wa_status": "disconnected", "wa_phone": "", "wa_qr": ""}

    if session:
        whatsapp_action = request.app.state.whatsapp_action
        state = await whatsapp_action.get_connection_state(session["instance_name"])

        if state == "open":
            phone = session.get("phone_number")
            if not phone or session["status"] != "connected":
                # Fetch phone from Evolution API (ownerJid)
                owner_jid = await whatsapp_action.get_owner_jid(
                    session["instance_name"],
                )
                if owner_jid and "@" in owner_jid:
                    phone = owner_jid.split("@")[0]
                await wa_store.update_status(
                    user["uid"],
                    "connected",
                    phone_number=phone,
                )
            ctx["wa_status"] = "connected"
            ctx["wa_phone"] = phone or ""
        elif session["status"] == "connecting":
            ctx["wa_status"] = "connecting"
            # Fetch fresh QR code
            qr_data = await whatsapp_action.get_qr_code(session["instance_name"])
            ctx["wa_qr"] = qr_data.get("base64", "")
        else:
            # Instance exists in DB but Evolution says closed — stale row
            # will be overwritten on next reconnect via upsert_session
            ctx["wa_status"] = "disconnected"

    return templates.TemplateResponse(request, "fragments/whatsapp_status.html", ctx)


@router.post("/api/whatsapp/connect", response_class=HTMLResponse)
async def whatsapp_connect(request: Request):
    """Create an Evolution API instance and return QR code fragment."""
    user, error = await _require_auth_and_csrf(request)
    if error:
        return error

    if user.get("uid") == 0:
        return HTMLResponse(_WA_REQUIRES_GOOGLE)

    wa_store = getattr(request.app.state, "wa_store", None)
    whatsapp_action = request.app.state.whatsapp_action
    if not wa_store:
        return HTMLResponse(
            '<p class="text-sm text-red-500">WhatsApp nicht verfuegbar.</p>'
        )

    instance_name = f"niles-wa-{user['uid']}"
    # Use internal Docker address — Evolution API and Niles Core are on the
    # same Docker network, so no TLS needed (avoids self-signed cert errors).
    # Configurable via WEBHOOK_BASE_URL for non-standard Docker setups.
    settings = request.app.state.settings
    webhook_url = (
        f"{settings.webhook_base_url.rstrip('/')}/webhook/whatsapp"
        f"?token={settings.evolution_api_key}"
    )

    result = await whatsapp_action.create_instance(instance_name, webhook_url)

    if "error" in result:
        # Instance may already exist — try to get QR code directly
        qr_data = await whatsapp_action.get_qr_code(instance_name)
        qr_base64 = qr_data.get("base64", "")
    else:
        qr_base64 = result.get("qrcode", {}).get("base64", "")

    try:
        await wa_store.upsert_session(user["uid"], instance_name, status="connecting")
    except asyncpg.ForeignKeyViolationError:
        logger.warning("FK violation: user_id=%s not in users table", user["uid"])
        response = HTMLResponse(
            '<p class="text-sm text-red-500">'
            "Sitzung ungueltig &ndash; bitte erneut einloggen.</p>",
            status_code=401,
            headers={"HX-Redirect": "/ui/login"},
        )
        response.delete_cookie(SESSION_COOKIE_NAME)
        return response

    return templates.TemplateResponse(
        request,
        "fragments/whatsapp_status.html",
        {
            "wa_status": "connecting",
            "wa_qr": qr_base64,
            "wa_phone": "",
        },
    )


@router.post("/api/whatsapp/disconnect", response_class=HTMLResponse)
async def whatsapp_disconnect(request: Request):
    """Logout and delete the user's Evolution API instance."""
    user, error = await _require_auth_and_csrf(request)
    if error:
        return error

    if user.get("uid") == 0:
        return HTMLResponse(_WA_REQUIRES_GOOGLE)

    wa_store = getattr(request.app.state, "wa_store", None)
    whatsapp_action = request.app.state.whatsapp_action
    if not wa_store:
        return HTMLResponse(
            '<p class="text-sm text-red-500">WhatsApp nicht verfuegbar.</p>'
        )

    session = await wa_store.get_session(user["uid"])
    if session:
        instance_name = session["instance_name"]
        await whatsapp_action.logout_instance(instance_name)
        await whatsapp_action.delete_instance(instance_name)
        await wa_store.delete_session(user["uid"])

    return templates.TemplateResponse(
        request,
        "fragments/whatsapp_status.html",
        {
            "wa_status": "disconnected",
            "wa_phone": "",
            "wa_qr": "",
        },
    )


# --- CardDAV contacts endpoints ---


async def _contacts_status_ctx(request: Request) -> dict:
    """Build template context for carddav_status.html fragment."""
    settings = request.app.state.settings
    connected = bool(settings.carddav_url)
    ctx: dict = {"connected": connected, "carddav_error": None}
    if not connected:
        return ctx

    ctx["carddav_url"] = settings.carddav_url
    ctx["carddav_user"] = settings.carddav_user

    pool = request.app.state.pool
    try:
        row = await pool.fetchrow(
            "SELECT COUNT(*) AS cnt, MAX(updated_at) AS last_sync FROM contacts"
        )
        if row:
            ctx["contact_count"] = row["cnt"]
            ctx["last_sync"] = row["last_sync"]
    except Exception:
        logger.warning("Failed to fetch contact status")
    return ctx


@router.get("/api/contacts/status", response_class=HTMLResponse)
async def contacts_status(request: Request):
    """Return CardDAV sync status fragment (form or connected card)."""
    user = _get_session_user(request)
    if user is None:
        return Response(status_code=401, headers={"HX-Redirect": "/ui/login"})

    ctx = await _contacts_status_ctx(request)
    return templates.TemplateResponse(
        request,
        "fragments/carddav_status.html",
        ctx,
    )


@router.post("/api/contacts/connect", response_class=HTMLResponse)
async def contacts_connect(
    request: Request,
    url: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
):
    """Test CardDAV connection, then save credentials and trigger initial sync."""
    _user, error = await _require_auth_and_csrf(request)
    if error:
        return error

    carddav_sync = getattr(request.app.state, "carddav_sync", None)
    if not carddav_sync:
        return templates.TemplateResponse(
            request,
            "fragments/carddav_status.html",
            {"connected": False, "carddav_error": "CardDAV Sync nicht verfuegbar."},
        )

    settings = request.app.state.settings

    # Apply overrides temporarily for connection test (not persisted yet)
    new_settings = apply_overrides(
        settings,
        {
            "carddav_url": url.strip(),
            "carddav_user": username.strip(),
            "carddav_password": password,
        },
    )
    carddav_sync.update_config(new_settings)

    # Test connection BEFORE saving to DB
    ok, message = await carddav_sync.test_connection()
    if not ok:
        # Revert to previous config
        carddav_sync.update_config(settings)
        return templates.TemplateResponse(
            request,
            "fragments/carddav_status.html",
            {"connected": False, "carddav_error": message},
        )

    # Connection successful — persist credentials (plaintext in DB,
    # acceptable for self-hosted; same pattern as CalDAV credentials).
    settings_store = request.app.state.settings_store
    try:
        await settings_store.set("carddav_url", url.strip())
        await settings_store.set("carddav_user", username.strip())
        await settings_store.set("carddav_password", password)
    except Exception as exc:
        logger.exception("Failed to persist CardDAV credentials")
        carddav_sync.update_config(settings)
        return templates.TemplateResponse(
            request,
            "fragments/carddav_status.html",
            {"connected": False, "carddav_error": f"Speichern fehlgeschlagen: {exc}"},
        )

    request.app.state.settings = new_settings

    # Register daily sync job if not already scheduled
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler and not scheduler.get_job("carddav_daily_sync"):
        scheduler.add_job(
            carddav_sync.sync_contacts,
            "cron",
            hour=3,
            minute=0,
            id="carddav_daily_sync",
            max_instances=1,
            misfire_grace_time=300,
        )
        logger.info("CardDAV daily sync job registered via UI")

    # Run initial sync
    try:
        await carddav_sync.sync_contacts()
    except Exception:
        logger.exception("Initial CardDAV sync failed after connect")

    ctx = await _contacts_status_ctx(request)
    return templates.TemplateResponse(
        request,
        "fragments/carddav_status.html",
        ctx,
    )


@router.post("/api/contacts/disconnect", response_class=HTMLResponse)
async def contacts_disconnect(request: Request):
    """Remove CardDAV credentials and delete all synced contacts."""
    _user, error = await _require_auth_and_csrf(request)
    if error:
        return error

    settings_store = request.app.state.settings_store

    # Delete credentials from settings store
    for key in ("carddav_url", "carddav_user", "carddav_password"):
        await settings_store.delete(key)

    # Apply overrides (empty strings revert to env/defaults)
    new_settings = apply_overrides(
        request.app.state.settings,
        {
            "carddav_url": "",
            "carddav_user": "",
            "carddav_password": "",
        },
    )
    request.app.state.settings = new_settings

    carddav_sync = getattr(request.app.state, "carddav_sync", None)
    if carddav_sync:
        carddav_sync.update_config(new_settings)

    # Delete all contacts
    pool = request.app.state.pool
    try:
        await pool.execute("DELETE FROM contacts")
        logger.info("All contacts deleted (CardDAV disconnected)")
    except Exception:
        logger.exception("Failed to delete contacts on disconnect")

    return templates.TemplateResponse(
        request,
        "fragments/carddav_status.html",
        {"connected": False, "carddav_error": None},
    )


@router.post("/api/contacts/sync", response_class=HTMLResponse)
async def contacts_sync(request: Request):
    """Trigger a manual CardDAV contact sync."""
    _user, error = await _require_auth_and_csrf(request)
    if error:
        return error

    carddav_sync = getattr(request.app.state, "carddav_sync", None)
    if not carddav_sync:
        ctx = await _contacts_status_ctx(request)
        ctx["carddav_error"] = "CardDAV Sync nicht verfuegbar."
        return templates.TemplateResponse(
            request,
            "fragments/carddav_status.html",
            ctx,
        )

    try:
        await carddav_sync.sync_contacts()
    except Exception:
        logger.exception("Manual CardDAV sync failed")

    ctx = await _contacts_status_ctx(request)
    return templates.TemplateResponse(
        request,
        "fragments/carddav_status.html",
        ctx,
    )


# --- Vikunja (per-user task management) ---


_VK_REQUIRES_GOOGLE = (
    '<p class="text-sm text-zinc-500 dark:text-zinc-400 py-2">'
    "Vikunja-Token erfordert einen Google-Login.</p>"
)


@router.get("/api/vikunja/status", response_class=HTMLResponse)
async def vikunja_status(request: Request):
    """Return Vikunja connection status fragment."""
    user = _get_session_user(request)
    if user is None:
        return Response(status_code=401, headers={"HX-Redirect": "/ui/login"})

    if user.get("uid") == 0:
        return HTMLResponse(_VK_REQUIRES_GOOGLE)

    vikunja_store = getattr(request.app.state, "vikunja_store", None)
    if not vikunja_store:
        return HTMLResponse(
            '<p class="text-sm text-zinc-500 dark:text-zinc-400 py-2">'
            "Vikunja nicht verfuegbar.</p>"
        )

    creds = await vikunja_store.get_credentials(user["uid"])
    ctx: dict = {
        "vikunja_connected": False,
        "vikunja_error": None,
        "vikunja_project_count": 0,
    }

    if creds:
        api_url = creds["api_url"] or request.app.state.settings.vikunja_api_url
        if api_url:
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(
                        f"{api_url.rstrip('/')}/projects",
                        headers={"Authorization": f"Bearer {creds['api_token']}"},
                        timeout=5,
                    )
                    resp.raise_for_status()
                    ctx["vikunja_connected"] = True
                    ctx["vikunja_project_count"] = len(resp.json())
            except Exception:
                ctx["vikunja_connected"] = True
                ctx["vikunja_error"] = "Verbindung zum Vikunja-Server fehlgeschlagen."
        else:
            ctx["vikunja_connected"] = True
            ctx["vikunja_error"] = "Keine Vikunja API-URL konfiguriert."

    return templates.TemplateResponse(
        request,
        "fragments/vikunja_status.html",
        ctx,
    )


@router.post("/api/vikunja/connect", response_class=HTMLResponse)
async def vikunja_connect(
    request: Request,
    api_token: str = Form(...),
    api_url: str = Form(""),
):
    """Save Vikunja API token for the current user."""
    user, error = await _require_auth_and_csrf(request)
    if error:
        return error

    if user.get("uid") == 0:
        return HTMLResponse(_VK_REQUIRES_GOOGLE)

    vikunja_store = getattr(request.app.state, "vikunja_store", None)
    if not vikunja_store:
        return templates.TemplateResponse(
            request,
            "fragments/vikunja_status.html",
            {
                "vikunja_connected": False,
                "vikunja_project_count": 0,
                "vikunja_error": "Vikunja nicht verfuegbar.",
            },
        )

    effective_url = api_url.strip() or request.app.state.settings.vikunja_api_url
    if not effective_url:
        return templates.TemplateResponse(
            request,
            "fragments/vikunja_status.html",
            {
                "vikunja_connected": False,
                "vikunja_project_count": 0,
                "vikunja_error": "Keine API-URL. Bitte URL angeben oder global konfigurieren.",
            },
        )

    # SSRF protection: only allow http/https and reject private IP ranges
    from urllib.parse import urlparse
    import ipaddress

    try:
        parsed = urlparse(effective_url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError("scheme")
        host = parsed.hostname or ""
        if not host:
            raise ValueError("host")
        # Reject private/loopback IPs (except Docker-internal hostnames)
        try:
            addr = ipaddress.ip_address(host)
            if addr.is_private or addr.is_loopback or addr.is_link_local:
                raise ValueError("private IP")
        except ValueError as ve:
            # Not an IP address — allow hostnames (e.g. "vikunja", "localhost" for Docker)
            if str(ve) == "private IP":
                raise
    except ValueError:
        return templates.TemplateResponse(
            request,
            "fragments/vikunja_status.html",
            {
                "vikunja_connected": False,
                "vikunja_project_count": 0,
                "vikunja_error": "Ungueltige URL. Nur http:// und https:// erlaubt.",
            },
        )

    # Test connection before saving
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{effective_url.rstrip('/')}/projects",
                headers={"Authorization": f"Bearer {api_token}"},
                timeout=10,
            )
            resp.raise_for_status()
            project_count = len(resp.json())
    except Exception:
        return templates.TemplateResponse(
            request,
            "fragments/vikunja_status.html",
            {
                "vikunja_connected": False,
                "vikunja_project_count": 0,
                "vikunja_error": "Verbindung fehlgeschlagen: Token oder URL ungueltig.",
            },
        )

    try:
        await vikunja_store.upsert_credentials(
            user_id=user["uid"],
            api_token=api_token,
            api_url=api_url.strip(),
        )
    except asyncpg.ForeignKeyViolationError:
        logger.warning("FK violation: user_id=%s not in users table", user["uid"])
        response = HTMLResponse(
            '<p class="text-sm text-red-500">'
            "Sitzung ungueltig &ndash; bitte erneut einloggen.</p>",
            status_code=401,
            headers={"HX-Redirect": "/ui/login"},
        )
        response.delete_cookie(SESSION_COOKIE_NAME)
        return response

    return templates.TemplateResponse(
        request,
        "fragments/vikunja_status.html",
        {
            "vikunja_connected": True,
            "vikunja_project_count": project_count,
            "vikunja_error": None,
        },
    )


@router.post("/api/vikunja/disconnect", response_class=HTMLResponse)
async def vikunja_disconnect(request: Request):
    """Remove Vikunja API token for current user."""
    user, error = await _require_auth_and_csrf(request)
    if error:
        return error

    if user.get("uid") == 0:
        return HTMLResponse(_VK_REQUIRES_GOOGLE)

    vikunja_store = getattr(request.app.state, "vikunja_store", None)
    if vikunja_store and user.get("uid"):
        await vikunja_store.delete_credentials(user["uid"])

    return templates.TemplateResponse(
        request,
        "fragments/vikunja_status.html",
        {"vikunja_connected": False, "vikunja_project_count": 0, "vikunja_error": None},
    )
