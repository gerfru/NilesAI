"""Tests for Notion web routes (sources/web/_notion.py)."""

from unittest.mock import AsyncMock, MagicMock, patch

from itsdangerous import URLSafeTimedSerializer

from niles.config import Settings
from niles.sources.web import (
    CSRF_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    notion_connect,
    notion_disconnect,
    notion_search,
    notion_status,
    notion_sync_trigger,
)

_TEST_NILES_KEY = "test-niles-key"
_TEST_SESSION_SECRET = "test-session-secret"
CSRF_TOKEN = "test-csrf-token"
_TEST_USER = {
    "uid": 1,
    "email": "test@example.com",
    "display_name": "Test User",
    "avatar_url": "",
    "is_admin": True,
}


def _make_session_token(user=None, secret=_TEST_SESSION_SECRET):
    serializer = URLSafeTimedSerializer(secret)
    return serializer.dumps(user or _TEST_USER)


def _make_settings(**overrides):
    defaults = dict(
        _env_file=None,
        postgres_password="test",
        evolution_api_key="test",
        niles_api_key=_TEST_NILES_KEY,
        session_secret=_TEST_SESSION_SECRET,
    )
    defaults.update(overrides)
    return Settings(**defaults)


def _make_request(
    *,
    cookies=None,
    headers=None,
    settings=None,
    pool=None,
    settings_store=None,
    agent=None,
    scheduler=None,
    notion_sync=None,
    notion_embedder=None,
    notion_retriever=None,
    ollama_embedder=None,
    notion_summarizer=None,
):
    """Build a mock Request with app.state for Notion tests."""
    request = MagicMock()
    request.cookies = cookies or {}
    request.headers = headers or {}
    request.app.state.settings = settings or _make_settings()
    request.app.state.pool = pool or AsyncMock()
    request.app.state.settings_store = settings_store or AsyncMock()
    request.app.state.user_store = AsyncMock()
    request.app.state.agent = agent or AsyncMock()
    request.app.state.scheduler = scheduler
    request.app.state.notion_sync = notion_sync
    request.app.state.notion_embedder = notion_embedder
    request.app.state.notion_retriever = notion_retriever
    request.app.state.ollama_embedder = ollama_embedder
    request.app.state.notion_summarizer = notion_summarizer
    request.client.host = "127.0.0.1"
    request.url.scheme = "http"
    return request


def _auth_cookies():
    return {SESSION_COOKIE_NAME: _make_session_token(), CSRF_COOKIE_NAME: CSRF_TOKEN}


def _csrf_headers():
    return {"x-csrf-token": CSRF_TOKEN}


# ---------- notion_status ----------------------------------------------------


class TestNotionStatus:
    async def test_unauthenticated_returns_401(self):
        request = _make_request()
        response = await notion_status(request)
        assert response.status_code == 401

    async def test_authenticated_returns_html(self):
        request = _make_request(cookies=_auth_cookies())
        with patch("niles.sources.web._notion.templates") as mock_tpl:
            mock_tpl.TemplateResponse.return_value = MagicMock(status_code=200)
            response = await notion_status(request)
        assert response.status_code == 200

    async def test_connected_shows_page_count(self):
        settings = _make_settings(feature_notion=True, notion_token="ntn_test_12345678")
        pool = AsyncMock()
        pool.fetchrow.return_value = {"cnt": 42, "last_sync": None}
        pool.fetch.return_value = [
            {"chunk_level": 1, "cnt": 128},
            {"chunk_level": 0, "cnt": 10},
        ]
        request = _make_request(
            cookies=_auth_cookies(),
            settings=settings,
            pool=pool,
        )

        with patch("niles.sources.web._notion.templates") as mock_tpl:
            mock_tpl.TemplateResponse.return_value = MagicMock(status_code=200)
            await notion_status(request)

        ctx = mock_tpl.TemplateResponse.call_args[0][2]
        assert ctx["connected"] is True
        assert ctx["page_count"] == 42
        assert ctx["chunk_count"] == 128
        assert ctx["summary_count"] == 10


# ---------- notion_connect ---------------------------------------------------


class TestNotionConnect:
    async def test_empty_token_rejected(self):
        request = _make_request(
            cookies=_auth_cookies(),
            headers=_csrf_headers(),
        )
        with patch("niles.sources.web._notion.templates") as mock_tpl:
            mock_tpl.TemplateResponse.return_value = MagicMock(status_code=200)
            await notion_connect(request, token="   ")

        ctx = mock_tpl.TemplateResponse.call_args[0][2]
        assert ctx["connected"] is False
        assert "leer" in ctx["notion_error"]

    async def test_failed_connection_shows_error(self):
        request = _make_request(
            cookies=_auth_cookies(),
            headers=_csrf_headers(),
        )
        with (
            patch("niles.sync.notion.NotionSync") as MockSync,
            patch("niles.sources.web._notion.templates") as mock_tpl,
        ):
            mock_sync = MockSync.return_value
            mock_sync.test_connection = AsyncMock(
                return_value=(False, "Invalid API token")
            )
            mock_tpl.TemplateResponse.return_value = MagicMock(status_code=200)
            await notion_connect(request, token="ntn_invalid")

        ctx = mock_tpl.TemplateResponse.call_args[0][2]
        assert ctx["connected"] is False
        assert "Invalid API token" in ctx["notion_error"]

    async def test_successful_connect(self):
        pool = AsyncMock()
        pool.fetchrow.return_value = {"cnt": 5, "last_sync": None}
        pool.fetch.return_value = []  # no embeddings yet
        settings_store = AsyncMock()
        agent = MagicMock()
        agent._ctx = MagicMock()
        scheduler = MagicMock()
        scheduler.get_job.return_value = None

        request = _make_request(
            cookies=_auth_cookies(),
            headers=_csrf_headers(),
            pool=pool,
            settings_store=settings_store,
            agent=agent,
            scheduler=scheduler,
        )

        with (
            patch("niles.sync.notion.NotionSync") as MockSync,
            patch("niles.sync.notion_embeddings.NotionEmbeddingPipeline"),
            patch("niles.sync.ollama_embedder.OllamaEmbedder"),
            patch("niles.sync.notion_summarizer.NotionSummarizer"),
            patch("niles.actions.notion.NotionRetriever"),
            patch("niles.sources.web._notion.templates") as mock_tpl,
            patch("niles.sources.web._notion.asyncio") as mock_asyncio,
        ):
            mock_sync_inst = MockSync.return_value
            mock_sync_inst.test_connection = AsyncMock(
                return_value=(True, "Verbunden. 5+ Seiten zugaenglich.")
            )
            mock_tpl.TemplateResponse.return_value = MagicMock(status_code=200)

            await notion_connect(request, token="ntn_valid_token_here")

        # Should persist settings
        assert settings_store.set.call_count == 2

        # Should register scheduler job
        scheduler.add_job.assert_called_once()

        # Should fire initial sync task
        mock_asyncio.create_task.assert_called_once()

    async def test_requires_csrf(self):
        # No CSRF headers
        request = _make_request(cookies=_auth_cookies())
        response = await notion_connect(request, token="ntn_test")
        # _require_auth_and_csrf should reject
        assert response is not None


# ---------- notion_disconnect ------------------------------------------------


class TestNotionDisconnect:
    async def test_disconnect_clears_data(self):
        settings_store = AsyncMock()
        pool = AsyncMock()
        agent = MagicMock()
        agent._ctx = MagicMock()
        scheduler = MagicMock()
        scheduler.get_job.return_value = MagicMock()  # Job exists

        request = _make_request(
            cookies=_auth_cookies(),
            headers=_csrf_headers(),
            pool=pool,
            settings_store=settings_store,
            agent=agent,
            scheduler=scheduler,
            ollama_embedder=AsyncMock(),
            notion_summarizer=AsyncMock(),
        )

        with patch("niles.sources.web._notion.templates") as mock_tpl:
            mock_tpl.TemplateResponse.return_value = MagicMock(status_code=200)
            await notion_disconnect(request)

        # Should delete settings
        assert settings_store.delete.call_count == 2

        # Should remove scheduler job
        scheduler.remove_job.assert_called_once_with("notion_sync")

        # Should DELETE from both tables
        execute_calls = [c[0][0] for c in pool.execute.call_args_list]
        assert any("DELETE FROM notion_embeddings" in sql for sql in execute_calls)
        assert any("DELETE FROM notion_pages" in sql for sql in execute_calls)

        # Should set agent.notion_retriever = None
        assert agent.notion_retriever is None

        # Should set app.state to None
        assert request.app.state.notion_sync is None
        assert request.app.state.notion_retriever is None


# ---------- notion_sync_trigger ----------------------------------------------


class TestNotionSyncTrigger:
    async def test_no_sync_available(self):
        request = _make_request(
            cookies=_auth_cookies(),
            headers=_csrf_headers(),
        )

        with patch("niles.sources.web._notion.templates") as mock_tpl:
            mock_tpl.TemplateResponse.return_value = MagicMock(status_code=200)
            await notion_sync_trigger(request)

        ctx = mock_tpl.TemplateResponse.call_args[0][2]
        assert "nicht verfuegbar" in ctx["notion_error"]

    async def test_sync_creates_background_task(self):
        mock_sync = AsyncMock()
        mock_embedder = AsyncMock()
        pool = AsyncMock()
        pool.fetchrow.return_value = {"cnt": 10, "last_sync": None}
        pool.fetch.return_value = [
            {"chunk_level": 1, "cnt": 50},
            {"chunk_level": 0, "cnt": 5},
        ]

        settings = _make_settings(feature_notion=True, notion_token="ntn_tok")
        request = _make_request(
            cookies=_auth_cookies(),
            headers=_csrf_headers(),
            pool=pool,
            settings=settings,
            notion_sync=mock_sync,
            notion_embedder=mock_embedder,
        )

        with (
            patch("niles.sources.web._notion.templates") as mock_tpl,
            patch("niles.sources.web._notion.asyncio") as mock_asyncio,
        ):
            mock_tpl.TemplateResponse.return_value = MagicMock(status_code=200)
            await notion_sync_trigger(request)

        # Sync runs in background via create_task, not inline
        mock_asyncio.create_task.assert_called_once()


# ---------- notion_search ----------------------------------------------------


class TestNotionSearch:
    async def test_no_retriever_returns_404(self):
        request = _make_request(
            cookies=_auth_cookies(),
            headers=_csrf_headers(),
        )

        response = await notion_search(request, query="test")

        assert response.status_code == 404

    async def test_returns_results(self):
        retriever = AsyncMock()
        retriever.search.return_value = [
            {
                "chunk_text": "Niles info",
                "page_title": "About",
                "page_url": "https://notion.so",
                "similarity": 0.9,
            },
        ]
        request = _make_request(
            cookies=_auth_cookies(),
            headers=_csrf_headers(),
            notion_retriever=retriever,
        )

        result = await notion_search(request, query="Niles")

        assert len(result["results"]) == 1
        assert result["results"][0]["page_title"] == "About"
