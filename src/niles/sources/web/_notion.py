"""Notion RAG routes: status, connect, disconnect, sync, search."""

import asyncio
import logging

from fastapi import Form, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse

from ...config import apply_overrides
from ._core import (
    _get_session_user,
    _require_auth_and_csrf,
    router,
    templates,
)

logger = logging.getLogger(__name__)


async def _notion_status_ctx(request: Request) -> dict:
    """Build template context for notion_status.html fragment."""
    settings = request.app.state.settings
    connected = settings.feature_notion and bool(settings.notion_token)
    ctx: dict = {"connected": connected, "notion_error": None}
    if not connected:
        return ctx

    # Mask token for display
    token = settings.notion_token
    if len(token) > 8:
        ctx["notion_token_masked"] = token[:7] + "..." + token[-4:]
    else:
        ctx["notion_token_masked"] = "****"

    pool = request.app.state.pool
    try:
        row = await pool.fetchrow(
            "SELECT COUNT(*) AS cnt, MAX(synced_at) AS last_sync FROM notion_pages"
        )
        if row:
            ctx["page_count"] = row["cnt"]
            ctx["last_sync"] = row["last_sync"]
    except Exception:
        logger.warning("Failed to fetch notion page count")

    try:
        row = await pool.fetchrow("SELECT COUNT(*) AS cnt FROM notion_embeddings")
        if row:
            ctx["chunk_count"] = row["cnt"]
    except Exception:
        logger.warning("Failed to fetch notion chunk count")

    return ctx


@router.get("/api/notion/status", response_class=HTMLResponse)
async def notion_status(request: Request):
    """Return Notion connection status fragment."""
    user = _get_session_user(request)
    if user is None:
        return Response(status_code=401, headers={"HX-Redirect": "/ui/login"})

    ctx = await _notion_status_ctx(request)
    return templates.TemplateResponse(
        request,
        "fragments/notion_status.html",
        ctx,
    )


@router.post("/api/notion/connect", response_class=HTMLResponse)
async def notion_connect(
    request: Request,
    token: str = Form(...),
):
    """Test Notion connection, save token, and trigger initial sync."""
    _user, error = await _require_auth_and_csrf(request)
    if error:
        return error

    token = token.strip()
    if not token:
        return templates.TemplateResponse(
            request,
            "fragments/notion_status.html",
            {"connected": False, "notion_error": "Token darf nicht leer sein."},
        )

    pool = request.app.state.pool

    # Test connection before persisting
    from ...sync.notion import NotionSync

    test_sync = NotionSync(pool, token)
    ok, message = await test_sync.test_connection()
    if not ok:
        return templates.TemplateResponse(
            request,
            "fragments/notion_status.html",
            {"connected": False, "notion_error": message},
        )

    # Persist settings
    settings_store = request.app.state.settings_store
    try:
        await settings_store.set("notion_token", token)
        await settings_store.set("feature_notion", True)
    except Exception:
        logger.exception("Failed to persist Notion credentials")
        return templates.TemplateResponse(
            request,
            "fragments/notion_status.html",
            {
                "connected": False,
                "notion_error": "Speichern fehlgeschlagen. Details siehe Logs.",
            },
        )

    # Update settings
    settings = request.app.state.settings
    new_settings = apply_overrides(
        settings,
        {"notion_token": token, "feature_notion": True},
    )
    request.app.state.settings = new_settings

    # Create sync/embed/retrieval instances
    from ...sync.notion_embeddings import NotionEmbeddingPipeline
    from ...actions.notion import NotionRetriever

    notion_sync = NotionSync(pool, token)
    notion_embedder = NotionEmbeddingPipeline(
        pool=pool,
        ollama_base_url=new_settings.llm_base_url,
        model=new_settings.notion_embedding_model,
        chunk_size=new_settings.notion_chunk_size,
        chunk_overlap=new_settings.notion_chunk_overlap,
    )
    notion_retriever = NotionRetriever(
        pool=pool,
        ollama_base_url=new_settings.llm_base_url,
        model=new_settings.notion_embedding_model,
        similarity_threshold=new_settings.notion_similarity_threshold,
    )

    request.app.state.notion_sync = notion_sync
    request.app.state.notion_embedder = notion_embedder
    request.app.state.notion_retriever = notion_retriever

    # Wire retriever into agent
    agent = getattr(request.app.state, "agent", None)
    if agent:
        agent.notion_retriever = notion_retriever

    # Register scheduler job
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler and not scheduler.get_job("notion_sync"):

        async def notion_sync_and_embed():
            await notion_sync.sync_all()
            await notion_embedder.embed_pending()

        scheduler.add_job(
            notion_sync_and_embed,
            "interval",
            minutes=new_settings.notion_sync_interval,
            id="notion_sync",
            max_instances=1,
            misfire_grace_time=600,
        )
        logger.info("Notion sync job registered via UI")

    # Trigger initial sync in background
    async def _initial_sync():
        try:
            await notion_sync.sync_all()
            await notion_embedder.embed_pending()
        except Exception:
            logger.exception("Initial Notion sync failed after connect")

    asyncio.create_task(_initial_sync())

    ctx = await _notion_status_ctx(request)
    return templates.TemplateResponse(
        request,
        "fragments/notion_status.html",
        ctx,
    )


@router.post("/api/notion/disconnect", response_class=HTMLResponse)
async def notion_disconnect(request: Request):
    """Remove Notion token and clear all synced data."""
    _user, error = await _require_auth_and_csrf(request)
    if error:
        return error

    settings_store = request.app.state.settings_store

    # Delete settings
    for key in ("notion_token", "feature_notion"):
        await settings_store.delete(key)

    # Revert settings
    new_settings = apply_overrides(
        request.app.state.settings,
        {"notion_token": "", "feature_notion": False},
    )
    request.app.state.settings = new_settings

    # Remove scheduler job
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler and scheduler.get_job("notion_sync"):
        scheduler.remove_job("notion_sync")

    # Clear data
    pool = request.app.state.pool
    try:
        await pool.execute("DELETE FROM notion_embeddings")
        await pool.execute("DELETE FROM notion_pages")
        logger.info("Notion data cleared (disconnected)")
    except Exception:
        logger.exception("Failed to clear Notion data on disconnect")

    # Clear app state
    request.app.state.notion_sync = None
    request.app.state.notion_embedder = None
    request.app.state.notion_retriever = None

    agent = getattr(request.app.state, "agent", None)
    if agent:
        agent.notion_retriever = None

    return templates.TemplateResponse(
        request,
        "fragments/notion_status.html",
        {"connected": False, "notion_error": None},
    )


@router.post("/api/notion/sync", response_class=HTMLResponse)
async def notion_sync_trigger(request: Request):
    """Trigger a manual Notion sync + embed."""
    _user, error = await _require_auth_and_csrf(request)
    if error:
        return error

    notion_sync = getattr(request.app.state, "notion_sync", None)
    notion_embedder = getattr(request.app.state, "notion_embedder", None)
    if not notion_sync:
        ctx = await _notion_status_ctx(request)
        ctx["notion_error"] = "Notion Sync nicht verfuegbar."
        return templates.TemplateResponse(
            request,
            "fragments/notion_status.html",
            ctx,
        )

    try:
        await notion_sync.sync_all()
        if notion_embedder:
            await notion_embedder.embed_pending()
    except Exception:
        logger.exception("Manual Notion sync failed")

    ctx = await _notion_status_ctx(request)
    return templates.TemplateResponse(
        request,
        "fragments/notion_status.html",
        ctx,
    )


@router.post("/api/notion/search")
async def notion_search(request: Request, query: str = Form(...)):
    """Direct Notion search (bypasses LLM tool selection)."""
    _user, error = await _require_auth_and_csrf(request)
    if error:
        return error

    retriever = getattr(request.app.state, "notion_retriever", None)
    if not retriever:
        return JSONResponse(
            status_code=404,
            content={"error": "Notion not configured"},
        )

    results = await retriever.search(query, max_results=5)
    return {"results": results}
