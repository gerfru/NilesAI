"""Web GUI router -- htmx-powered chat and settings UI."""

import hmac
import logging
from pathlib import Path

from fastapi import APIRouter, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..config import apply_overrides

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ui", tags=["web-ui"])

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

WEB_CHAT_ID = "web-ui"
COOKIE_NAME = "niles_api_key"
COOKIE_MAX_AGE = 30 * 24 * 3600  # 30 days


def _verify_cookie(request: Request) -> bool:
    """Check if the API key cookie is valid."""
    cookie_key = request.cookies.get(COOKIE_NAME, "")
    expected = request.app.state.settings.niles_api_key
    if not cookie_key or len(cookie_key) > 256:
        return False
    return hmac.compare_digest(cookie_key, expected)


# --- Page routes (return full HTML pages) ---


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Show API key login form."""
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login")
async def login_submit(request: Request, api_key: str = Form(...)):
    """Validate API key and set auth cookie."""
    expected = request.app.state.settings.niles_api_key
    if not api_key or len(api_key) > 256 or not hmac.compare_digest(api_key, expected):
        return templates.TemplateResponse(
            request, "login.html",
            {"error": "Ungueltiger API-Key"},
            status_code=401,
        )
    response = RedirectResponse(url="/ui/chat", status_code=303)
    response.set_cookie(
        COOKIE_NAME, api_key,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        secure=True,
        samesite="strict",
    )
    return response


@router.get("/logout")
async def logout():
    """Clear auth cookie and redirect to login."""
    response = RedirectResponse(url="/ui/login", status_code=303)
    response.delete_cookie(COOKIE_NAME)
    return response


@router.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    """Chat page with conversation history."""
    if not _verify_cookie(request):
        return RedirectResponse(url="/ui/login", status_code=303)
    history = request.app.state.history
    messages = await history.get_recent(WEB_CHAT_ID, limit=50)
    return templates.TemplateResponse(request, "chat.html", {
        "messages": messages,
        "active_page": "chat",
    })


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """Settings dashboard."""
    if not _verify_cookie(request):
        return RedirectResponse(url="/ui/login", status_code=303)
    return templates.TemplateResponse(request, "settings.html", {
        "settings": request.app.state.settings,
        "active_page": "settings",
    })


# --- htmx fragment endpoints ---


@router.post("/api/chat", response_class=HTMLResponse)
async def chat_send(request: Request, message: str = Form(...)):
    """Process a chat message, return HTML fragment with user + assistant bubbles."""
    if not _verify_cookie(request):
        return Response(status_code=401, headers={"HX-Redirect": "/ui/login"})

    agent = request.app.state.agent
    event = {
        "type": "web",
        "from": WEB_CHAT_ID,
        "content": message,
        "metadata": {},
    }
    response_text = await agent.process_event(event)

    return templates.TemplateResponse(request, "fragments/message.html", {
        "user_message": message,
        "assistant_message": response_text,
    })


@router.post("/api/chat/clear", response_class=HTMLResponse)
async def chat_clear(request: Request):
    """Clear chat history, return empty content."""
    if not _verify_cookie(request):
        return Response(status_code=401, headers={"HX-Redirect": "/ui/login"})
    history = request.app.state.history
    await history.clear(WEB_CHAT_ID)
    return HTMLResponse("")


@router.post("/api/settings/{key}", response_class=HTMLResponse)
async def update_setting(request: Request, key: str, value: str = Form(...)):
    """Update a single runtime setting."""
    if not _verify_cookie(request):
        return Response(status_code=401, headers={"HX-Redirect": "/ui/login"})

    settings_store = request.app.state.settings_store
    settings = request.app.state.settings

    # Convert value to appropriate type
    if key.startswith("feature_"):
        parsed_value = value.lower() in ("true", "1", "on")
    else:
        parsed_value = value

    try:
        await settings_store.set(key, parsed_value)
        apply_overrides(settings, {key: parsed_value})
    except ValueError as e:
        return templates.TemplateResponse(request, "fragments/toast.html", {
            "message": str(e),
            "toast_type": "error",
        })

    return templates.TemplateResponse(request, "fragments/toast.html", {
        "message": f"'{key}' gespeichert",
        "toast_type": "success",
    })
