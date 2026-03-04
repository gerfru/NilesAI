"""Chat routes: page, history, send, stream, clear."""

import json
import logging
from datetime import datetime, timezone

import structlog
from fastapi import Form, Query, Request, Response
from fastapi.responses import HTMLResponse, StreamingResponse

from ...metrics import ACTIVE_SSE
from ._core import (
    _CHAT_PAGE_SIZE,
    _ensure_csrf_cookie,
    _get_session_user,
    _require_auth_and_csrf,
    _require_auth_page,
    _resolve_channel,
    _user_chat_id,
    router,
    templates,
)

logger = logging.getLogger(__name__)


@router.get("/chat", response_class=HTMLResponse)
async def chat_page(
    request: Request,
    channel: str = Query(default="web"),
):
    """Chat page with channel selection and per-user conversation history."""
    user, error = await _require_auth_page(request)
    if error:
        return error
    assert user is not None

    wa_store = getattr(request.app.state, "wa_store", None)

    # Fetch session once, reuse for channel resolution and tab visibility
    wa_session = None
    if wa_store:
        wa_session = await wa_store.get_session(user["uid"])

    settings = request.app.state.settings
    signal_phone = settings.signal_phone_number if settings.signal_api_url else ""
    chat_id, readonly = await _resolve_channel(
        user, channel, wa_store, wa_session, signal_phone=signal_phone
    )
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
    if signal_phone:
        available_channels.append(("signal", "Signal"))

    response = templates.TemplateResponse(
        request,
        "chat.html",
        {
            "messages": messages,
            "has_more": has_more,
            "next_offset": _CHAT_PAGE_SIZE,
            "active_page": "chat",
            "user": user,
            "channel": channel
            if not readonly or channel in ("whatsapp", "signal")
            else "web",
            "readonly": readonly,
            "available_channels": available_channels,
            "vikunja_url": settings.vikunja_public_url or "",
            "feature_search": settings.feature_search,
            "feature_notion": settings.feature_notion
            and bool(getattr(request.app.state, "notion_retriever", None)),
        },
    )
    _ensure_csrf_cookie(request, response)
    return response


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
    assert user is not None

    if len(message) > 2000:
        return Response(
            status_code=400, content="Nachricht zu lang (max. 2000 Zeichen)."
        )

    chat_id = _user_chat_id(user)
    structlog.contextvars.bind_contextvars(chat_id=chat_id, source="web")
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
async def chat_stream(
    request: Request,
    message: str = Form(...),
    web_search: bool = Form(default=False),
    notion_search: bool = Form(default=False),
):
    """Process a chat message via SSE streaming.

    Uses fetch+ReadableStream on the client (not EventSource), so native SSE
    reconnect semantics (retry/last-event-id) don't apply.  A dropped
    connection simply ends the stream; the user re-sends if needed.
    """
    user, error = await _require_auth_and_csrf(request)
    if error:
        return error
    assert user is not None

    if len(message) > 2000:
        return Response(
            status_code=400, content="Nachricht zu lang (max. 2000 Zeichen)."
        )

    # Server-side guard: ignore client flags when features are globally disabled
    settings = request.app.state.settings
    if not settings.feature_search:
        web_search = False
    if not settings.feature_notion:
        notion_search = False

    # Notion context injection (deterministic, bypasses LLM tool selection).
    # When the toggle is active, the `search_notion` tool is removed from
    # the LLM tools (via notion_search metadata flag in context.py) to
    # prevent duplicate searches.
    enriched_message = message
    if notion_search:
        retriever = getattr(request.app.state, "notion_retriever", None)
        if retriever:
            results = await retriever.search(message, max_results=5)
            if results:
                context_parts = [
                    "[Notion-Kontext]\n"
                    "Die folgenden Abschnitte wurden per Aehnlichkeitssuche "
                    "gefunden. Beantworte die Frage NUR anhand dieser Inhalte. "
                    "Ignoriere Abschnitte, die thematisch nicht zur Frage passen."
                ]
                for r in results:
                    score = r.get("similarity", 0)
                    title = r["page_title"]
                    url = r["page_url"]
                    context_parts.append(
                        f"Quelle: [{title}]({url}) (Relevanz: {score:.0%})\n"
                        f"> {r['chunk_text']}"
                    )
                context_parts.append(f"[Frage]\n{message}")
                enriched_message = "\n\n".join(context_parts)
            else:
                enriched_message = (
                    "[Notion-Kontext]\n"
                    "Keine relevanten Inhalte im Notion-Wissensspeicher "
                    "gefunden. Teile dem Benutzer mit, dass zu seiner Frage "
                    "keine passenden Notion-Seiten vorhanden sind.\n\n"
                    f"[Frage]\n{message}"
                )

    chat_id = _user_chat_id(user)
    structlog.contextvars.bind_contextvars(chat_id=chat_id, source="web")
    agent = request.app.state.agent
    event = {
        "type": "web",
        "from": chat_id,
        "content": enriched_message,
        "metadata": {"web_search": web_search, "notion_search": notion_search},
    }

    async def event_generator():
        shutdown_event = getattr(request.app.state, "shutdown_event", None)
        ACTIVE_SSE.inc()
        try:
            async for item in agent.process_event_stream(event):
                # Best-effort drain: checked between LLM responses.
                # During active inference (10-30s with local models) the
                # connection stays open until the current chunk completes.
                if shutdown_event and shutdown_event.is_set():
                    yield f"data: {json.dumps({'type': 'done'})}\n\n"
                    return
                data = json.dumps(item, ensure_ascii=False)
                yield f"data: {data}\n\n"
        except Exception:
            logger.exception("Agent streaming error")
            err = json.dumps(
                {"type": "chunk", "text": "Entschuldigung, ein Fehler ist aufgetreten."}
            )
            yield f"data: {err}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        finally:
            ACTIVE_SSE.dec()

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
    assert user is not None

    chat_id = _user_chat_id(user)
    history = request.app.state.history
    await history.clear(chat_id)
    return HTMLResponse("")
