# SPDX-License-Identifier: AGPL-3.0-only
"""Web GUI shared infrastructure — router, templates, auth guards, helpers.

UI language: German (de) -- intentional design choice for the target user.
"""

import hmac
import logging
import secrets
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from niles.types import AppState

if TYPE_CHECKING:
    from niles.config import Settings
    from niles.types import WhatsAppSession
    from niles.whatsapp_store import WhatsAppSessionStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ui", tags=["web-ui"])


def _state(request: Request) -> AppState:
    """Return typed app.state for mypy attribute resolution."""
    return request.app.state  # type: ignore[return-value]  # AppState protocol not recognized by mypy


_TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "templates"
_STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "static"


def _asset_hash() -> str:
    """Content hash of style.css for cache-busting query param."""
    css = _STATIC_DIR / "css" / "style.css"
    if css.exists():
        import hashlib

        return hashlib.sha256(css.read_bytes()).hexdigest()[:8]
    return "0"


_ASSET_VERSION = _asset_hash()


class _NilesTemplates(Jinja2Templates):
    """Jinja2Templates with automatic CSP nonce injection."""

    def TemplateResponse(  # type: ignore[override]  # Starlette TemplateResponse signature
        self,
        request: Request,
        name: str,
        context: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> HTMLResponse:
        ctx = context or {}
        ctx.setdefault("csp_nonce", getattr(request.state, "csp_nonce", ""))
        ctx.setdefault("v", _ASSET_VERSION)
        return super().TemplateResponse(request, name, ctx, **kwargs)


templates = _NilesTemplates(directory=str(_TEMPLATES_DIR))

# --- Constants ---

SESSION_COOKIE_NAME = "niles_session"
CSRF_COOKIE_NAME = "niles_csrf"
COOKIE_MAX_AGE = 7 * 24 * 3600  # 7 days

_CHAT_PAGE_SIZE = 20

_USER_EDITABLE_SETTINGS = {
    "feature_briefing_daily",
    "feature_briefing_weekly",
    "briefing_daily_time",
    "briefing_weekly_time",
}

# Google OAuth endpoints
_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"


# --- Security helpers ---


def _is_secure_context(request: Request) -> bool:
    """Detect whether the request arrived over HTTPS (directly or via reverse proxy)."""
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"


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
    except BadSignature, SignatureExpired:
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
            "is_admin": user.get("is_admin", False),
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

    # Verify user still exists in DB and refresh is_admin from DB
    uid = user.get("uid")
    user_store = getattr(request.app.state, "user_store", None)
    if uid and user_store:
        db_row = await user_store.get_by_id(uid)
        if db_row is None:
            logger.warning("Stale session: user_id=%s not in users table", uid)
            response = Response(status_code=401, headers={"HX-Redirect": "/ui/login"})
            response.delete_cookie(SESSION_COOKIE_NAME)
            response.delete_cookie(CSRF_COOKIE_NAME)
            return None, response
        # Keep is_admin in sync with DB (session cookie may be stale)
        user["is_admin"] = db_row.get("is_admin", False)

    return user, None


async def _require_admin(
    request: Request,
) -> tuple[dict | None, Response | None]:
    """Check session + CSRF + admin status. Returns (user, None) or (None, error).

    Use for mutating endpoints (POST/DELETE) that need CSRF protection.
    """
    user, error = await _require_auth_and_csrf(request)
    if error:
        return None, error
    assert user is not None
    if not user.get("is_admin"):
        return None, Response(status_code=403, headers={"HX-Redirect": "/ui/settings"})
    return user, None


async def _require_auth_page(
    request: Request,
) -> tuple[dict | None, Response | None]:
    """Check session + verify user exists in DB (no CSRF). For GET pages.

    Invalidates session when the user row no longer exists in the DB.
    """
    user = _get_session_user(request)
    if user is None:
        return None, RedirectResponse(url="/ui/login", status_code=303)

    uid = user.get("uid")
    user_store = getattr(request.app.state, "user_store", None)
    if uid and user_store:
        db_row = await user_store.get_by_id(uid)
        if db_row is None:
            response = RedirectResponse(url="/ui/login", status_code=303)
            response.delete_cookie(SESSION_COOKIE_NAME)
            response.delete_cookie(CSRF_COOKIE_NAME)
            return None, response
        user["is_admin"] = db_row.get("is_admin", False)

    return user, None


async def _require_admin_page(
    request: Request,
) -> tuple[dict | None, Response | None]:
    """Check session + admin status (no CSRF). For GET admin pages."""
    user, error = await _require_auth_page(request)
    if error:
        return None, error
    assert user is not None
    if not user.get("is_admin"):
        return None, RedirectResponse(url="/ui/settings", status_code=303)
    return user, None


def _user_chat_id(user: dict) -> str:
    """Per-user chat ID for conversation history."""
    return f"web-user-{user['uid']}"


async def _maybe_provision_vikunja(request: Request, user_id: int, email: str, *, password: str | None = None) -> None:
    """Auto-provision Vikunja account after login (no-op if not configured).

    When *password* is provided (password login), syncs it to Vikunja so the
    user can log into Vikunja with the same credentials.  Without password
    (Google OAuth), falls back to HMAC-derived internal password.
    """
    provisioner = request.app.state.vikunja_provisioner
    if provisioner:
        if password:
            await provisioner.sync_password(user_id, email, password)
        else:
            await provisioner.ensure_provisioned(user_id, email)


async def _resolve_channel(
    user: dict,
    channel: str,
    wa_store: "WhatsAppSessionStore | None",
    wa_session: "WhatsAppSession | None" = None,
    signal_phone: str = "",
) -> tuple[str, bool]:
    """Resolve channel name to (chat_id, readonly).

    Returns web-chat as fallback for unknown/invalid channels.
    Accepts an optional pre-fetched wa_session to avoid duplicate DB queries.
    """
    if channel == "whatsapp":
        session = wa_session
        if session is None and wa_store:
            session = await wa_store.get_session(user["uid"])
        phone_number = session.get("phone_number") if session else None
        if phone_number:
            chat_id = f"wa-self-{phone_number.replace('+', '').replace(' ', '')}"
            return chat_id, True
    if channel == "signal" and signal_phone:
        phone_digits = signal_phone.lstrip("+").replace(" ", "")
        return f"signal-self-{phone_digits}", True
    return _user_chat_id(user), False


def _google_configured(request: Request) -> bool:
    """Check if Google OAuth credentials are configured."""
    s = request.app.state.settings
    return bool(s.google_client_id and s.google_client_secret)


def _build_redirect_uri(request: Request, path: str = "/ui/callback/google") -> str:
    """Build Google OAuth redirect URI from configured base_url.

    Raises ValueError if base_url is not configured — OAuth requires a
    stable redirect URI and trusting X-Forwarded-Host is unsafe.
    """
    base_url = request.app.state.settings.base_url
    if not base_url:
        raise ValueError("BASE_URL must be configured for OAuth")
    return f"{base_url.rstrip('/')}{path}"


def _safe_settings_dict(settings: "Settings") -> dict:
    """Build a safe dict of settings values for templates (no __dict__ access)."""
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
        "caldav_password (Legacy)": "********" if settings.caldav_password else "(not set)",
    }

    briefing = {
        "feature_briefing_daily": getattr(settings, "feature_briefing_daily", False),
        "feature_briefing_weekly": getattr(settings, "feature_briefing_weekly", False),
        "briefing_daily_time": getattr(settings, "briefing_daily_time", "07:30"),
        "briefing_weekly_time": getattr(settings, "briefing_weekly_time", "07:15"),
        "briefing_channel": getattr(settings, "briefing_channel", "whatsapp"),
    }

    weather = {
        "weather_latitude": getattr(settings, "weather_latitude", ""),
        "weather_longitude": getattr(settings, "weather_longitude", ""),
        "weather_location_name": getattr(settings, "weather_location_name", ""),
    }

    return {
        "feature_whatsapp_send_others": getattr(settings, "feature_whatsapp_send_others", False),
        "feature_signal_send_others": getattr(settings, "feature_signal_send_others", False),
        "text_settings": text_settings,
        "general": {"timezone": settings.timezone, "log_level": settings.log_level},
        "infra": infra,
        "briefing": briefing,
        "weather": weather,
        "feature_search": getattr(settings, "feature_search", False),
        "searxng_url": getattr(settings, "searxng_url", "http://searxng:8888"),
        "feature_notion": getattr(settings, "feature_notion", False),
    }
