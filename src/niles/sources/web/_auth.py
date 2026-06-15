# SPDX-License-Identifier: AGPL-3.0-only
"""Authentication routes: login, Google OAuth, logout."""

import hmac
import logging
import secrets
import time
import urllib.parse
from collections import OrderedDict

import httpx
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from ._core import (
    CSRF_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    _GOOGLE_AUTH_URL,
    _GOOGLE_USERINFO_URL,
    _build_redirect_uri,
    _create_session_cookie,
    _google_configured,
    _is_secure_context,
    _maybe_provision_vikunja,
    _set_csrf_cookie,
    router,
    templates,
)

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105

logger = logging.getLogger(__name__)

_ph = PasswordHasher()

# --- Login rate limiting ---
_login_attempts: OrderedDict[str, list[float]] = OrderedDict()
_LOGIN_MAX_ATTEMPTS = 5
_LOGIN_WINDOW = 300.0  # 5 minutes
_MAX_LOGIN_IPS = 10_000


def _check_login_rate(client_ip: str) -> bool:
    """Return True if the client is within the login rate limit."""
    now = time.monotonic()
    window = now - _LOGIN_WINDOW
    attempts = _login_attempts.get(client_ip, [])
    recent = [t for t in attempts if t > window]
    if recent:
        _login_attempts[client_ip] = recent
        _login_attempts.move_to_end(client_ip)
    else:
        _login_attempts.pop(client_ip, None)
    return len(recent) < _LOGIN_MAX_ATTEMPTS


def _record_login_attempt(client_ip: str) -> None:
    attempts = _login_attempts.get(client_ip, [])
    attempts.append(time.monotonic())
    _login_attempts[client_ip] = attempts
    _login_attempts.move_to_end(client_ip)
    while len(_login_attempts) > _MAX_LOGIN_IPS:
        _login_attempts.popitem(last=False)


# --- Routes ---


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> Response:
    """Login page: Google OAuth button and/or email+password form."""
    user_store = getattr(request.app.state, "user_store", None)
    pw_users_exist = await user_store.has_password_users() if user_store else False
    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "error": None,
            "google_configured": _google_configured(request),
            "password_users_exist": pw_users_exist,
        },
    )


@router.post("/login")
async def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
) -> Response:
    """Validate email + password and set session cookie."""
    client_ip = request.client.host if request.client else "unknown"
    user_store = request.app.state.user_store
    pw_users_exist = await user_store.has_password_users()

    ctx = {
        "google_configured": _google_configured(request),
        "password_users_exist": pw_users_exist,
    }

    if not _check_login_rate(client_ip):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Zu viele Anmeldeversuche. Bitte warte 5 Minuten.", **ctx},
            status_code=429,
        )

    _record_login_attempt(client_ip)

    # Look up user and verify password
    user = await user_store.get_with_hash(email)
    if user is None or user.get("auth_method") != "password" or not user.get("password_hash"):
        # Hash dummy to prevent timing-based user enumeration
        _ph.hash("dummy-password-timing-defense")
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Ungültige E-Mail oder Passwort", **ctx},
            status_code=401,
        )

    try:
        _ph.verify(user["password_hash"], password)
    except VerifyMismatchError:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Ungültige E-Mail oder Passwort", **ctx},
            status_code=401,
        )

    # Update last_login
    await user_store.update_last_login(user["id"])

    await _maybe_provision_vikunja(request, user["id"], user["email"], password=password)

    response = RedirectResponse(url="/ui/chat", status_code=303)
    _create_session_cookie(request, response, user)
    _set_csrf_cookie(request, response)
    return response


# --- Google OAuth routes ---


@router.get("/login/google")
async def login_google(request: Request) -> Response:
    """Redirect to Google OAuth consent screen."""
    if not _google_configured(request):
        return RedirectResponse(url="/ui/login", status_code=303)

    state = secrets.token_urlsafe(32)
    try:
        redirect_uri = _build_redirect_uri(request)
    except ValueError:
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "error": "BASE_URL muss konfiguriert sein fuer Google OAuth.",
                "google_configured": False,
                "password_users_exist": True,
            },
        )
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
) -> Response:
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
    if not state or len(state) > 512 or not stored_state or not hmac.compare_digest(state, stored_state):
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "error": "Ungueltiger OAuth-State. Bitte erneut versuchen.",
                "google_configured": gc,
            },
        )

    settings = request.app.state.settings
    try:
        redirect_uri = _build_redirect_uri(request)
    except ValueError:
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "error": "BASE_URL muss konfiguriert sein fuer Google OAuth.",
                "google_configured": False,
                "password_users_exist": True,
            },
        )

    try:
        google_client = request.app.state.http_clients.google_oauth
        # Exchange authorization code for tokens
        token_resp = await google_client.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=10.0,
        )
        if token_resp.status_code != 200:
            logger.error(  # nosemgrep: python-logger-credential-disclosure
                "Google token exchange failed (HTTP %s)", token_resp.status_code
            )
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
        userinfo_resp = await google_client.get(
            _GOOGLE_USERINFO_URL,
            headers={
                "Authorization": f"Bearer {tokens['access_token']}",
            },
            timeout=10.0,
        )
        if userinfo_resp.status_code != 200:
            logger.error("Google userinfo request failed (HTTP %s)", userinfo_resp.status_code)
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
        allowed = [e.strip().lower() for e in settings.google_allowed_emails.split(",") if e.strip()]
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

    # Create or update user in DB (returns None if deactivated)
    user_store = request.app.state.user_store
    user = await user_store.create_or_update(
        email=email,
        display_name=userinfo.get("name", email),
        avatar_url=userinfo.get("picture"),
    )
    if user is None:
        logger.warning("Google login blocked for deactivated user: %s", email)
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Dieses Konto wurde deaktiviert.", "google_configured": gc},
            status_code=403,
        )
    logger.info("Google login: %s (user_id=%d)", email, user["id"])

    await _maybe_provision_vikunja(request, user["id"], email)

    response = RedirectResponse(url="/ui/chat", status_code=303)
    _create_session_cookie(request, response, user)
    _set_csrf_cookie(request, response)
    response.delete_cookie("oauth_state")
    return response


@router.post("/logout")
async def logout(request: Request) -> Response:
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
