"""Notion RAG routes: status, connect, disconnect, sync, search."""

import asyncio
import logging

from fastapi import Form, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse

from ...config import apply_overrides
from ._core import (
    _get_session_user,
    _require_admin,
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
        ctx["notion_token_masked"] = "****"  # noqa: S105

    notion_store = request.app.state.notion_store
    try:
        stats = await notion_store.get_page_stats()
        ctx["page_count"] = stats["cnt"]
        ctx["last_sync"] = stats["last_sync"]
    except Exception:
        logger.warning("Failed to fetch notion page count")

    try:
        rows = await notion_store.get_embedding_stats()
        for row in rows:
            if row["chunk_level"] == 1:
                ctx["chunk_count"] = row["cnt"]
            elif row["chunk_level"] == 0:
                ctx["summary_count"] = row["cnt"]
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
    _user, error = await _require_admin(request)
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

    # Create sync/embed/retrieval instances (shared embedder for connection pooling)
    from ...sync.notion_embeddings import NotionEmbeddingPipeline
    from ...sync.notion_summarizer import NotionSummarizer
    from ...sync.ollama_embedder import OllamaEmbedder
    from ...actions.notion import NotionRetriever

    # Wait for any in-flight sync, then close previous embedder/summarizer
    async with _notion_sync_lock:
        old_embedder = getattr(request.app.state, "ollama_embedder", None)
        if old_embedder:
            await old_embedder.close()
        old_summarizer = getattr(request.app.state, "notion_summarizer", None)
        if old_summarizer:
            await old_summarizer.close()

    ollama_embedder = OllamaEmbedder(
        ollama_base_url=new_settings.llm_base_url,
        model=new_settings.notion_embedding_model,
    )
    notion_summarizer = NotionSummarizer(
        ollama_base_url=new_settings.llm_base_url,
        model=new_settings.notion_summary_model or new_settings.llm_model,
        max_input_chars=new_settings.notion_summary_max_input,
        max_tokens=new_settings.notion_summary_max_tokens,
    )
    notion_sync = NotionSync(pool, token)
    notion_embedder = NotionEmbeddingPipeline(
        pool=pool,
        embedder=ollama_embedder,
        chunk_size=new_settings.notion_chunk_size,
        chunk_overlap=new_settings.notion_chunk_overlap,
        summarizer=notion_summarizer,
    )
    notion_retriever = NotionRetriever(
        pool=pool,
        embedder=ollama_embedder,
        similarity_threshold=new_settings.notion_similarity_threshold,
    )

    request.app.state.ollama_embedder = ollama_embedder
    request.app.state.notion_summarizer = notion_summarizer
    request.app.state.notion_sync = notion_sync
    request.app.state.notion_embedder = notion_embedder
    request.app.state.notion_retriever = notion_retriever

    # Wire retriever into agent + context builder (for tool filtering)
    agent = getattr(request.app.state, "agent", None)
    if agent:
        agent.notion_retriever = notion_retriever
        agent._ctx.notion_retriever = notion_retriever

    # Register scheduler job (remove stale job first on reconnect)
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler:
        if scheduler.get_job("notion_sync"):
            scheduler.remove_job("notion_sync")
        if new_settings.notion_sync_interval > 0:

            async def notion_sync_and_embed():
                if _notion_sync_lock.locked():
                    logger.info("Scheduled sync skipped (already running)")
                    return
                async with _notion_sync_lock:
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
        async with _notion_sync_lock:
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
    try:
        await request.app.state.notion_store.clear_all()
    except Exception:
        logger.exception("Failed to clear Notion data on disconnect")

    # Wait for any in-flight sync, then close embedder/summarizer
    async with _notion_sync_lock:
        old_embedder = getattr(request.app.state, "ollama_embedder", None)
        if old_embedder:
            await old_embedder.close()
        old_summarizer = getattr(request.app.state, "notion_summarizer", None)
        if old_summarizer:
            await old_summarizer.close()
    request.app.state.ollama_embedder = None
    request.app.state.notion_summarizer = None
    request.app.state.notion_sync = None
    request.app.state.notion_embedder = None
    request.app.state.notion_retriever = None

    agent = getattr(request.app.state, "agent", None)
    if agent:
        agent.notion_retriever = None
        agent._ctx.notion_retriever = None

    return templates.TemplateResponse(
        request,
        "fragments/notion_status.html",
        {"connected": False, "notion_error": None},
    )


_notion_sync_lock = asyncio.Lock()


@router.post("/api/notion/sync", response_class=HTMLResponse)
async def notion_sync_trigger(request: Request):
    """Trigger a manual Notion sync + embed in the background."""
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

    if _notion_sync_lock.locked():
        ctx = await _notion_status_ctx(request)
        ctx["notion_error"] = "Sync laeuft bereits."
        return templates.TemplateResponse(
            request,
            "fragments/notion_status.html",
            ctx,
        )

    async def _run_sync():
        async with _notion_sync_lock:
            try:
                await notion_sync.sync_all()
                if notion_embedder:
                    await notion_embedder.embed_pending()
            except Exception:
                logger.exception("Manual Notion sync failed")

    asyncio.create_task(_run_sync())

    ctx = await _notion_status_ctx(request)
    return templates.TemplateResponse(
        request,
        "fragments/notion_status.html",
        ctx,
    )


@router.post("/api/notion/reembed", response_class=HTMLResponse)
async def notion_force_reembed(request: Request):
    """Force re-embedding of all Notion pages (e.g. after model/prefix change)."""
    _user, error = await _require_auth_and_csrf(request)
    if error:
        return error

    notion_embedder = getattr(request.app.state, "notion_embedder", None)
    if not notion_embedder:
        ctx = await _notion_status_ctx(request)
        ctx["notion_error"] = "Notion Embedder nicht verfuegbar."
        return templates.TemplateResponse(
            request,
            "fragments/notion_status.html",
            ctx,
        )

    if _notion_sync_lock.locked():
        ctx = await _notion_status_ctx(request)
        ctx["notion_error"] = "Sync laeuft bereits."
        return templates.TemplateResponse(
            request,
            "fragments/notion_status.html",
            ctx,
        )

    async def _run_reembed():
        async with _notion_sync_lock:
            try:
                count = await notion_embedder.force_reembed()
                logger.info("Force re-embed: marked %d pages", count)
                await notion_embedder.embed_pending()
            except Exception:
                logger.exception("Force re-embed failed")

    asyncio.create_task(_run_reembed())

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
