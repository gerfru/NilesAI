"""HTTP E2E tests — FastAPI app with FakeLLM via ASGI transport.

Tests the full HTTP layer: auth, CSRF, SSE streaming, error handling.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from itsdangerous import URLSafeTimedSerializer

from niles.sources.web import router as web_router
from niles.sources.web._core import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME

from .conftest import FakeLLM, make_e2e_agent, _make_settings

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio(loop_scope="session")]


# ---------------------------------------------------------------------------
# Test app factory
# ---------------------------------------------------------------------------

_TEST_SESSION_SECRET = "test-secret-for-e2e"
_CSRF_TOKEN = "test-csrf-token-e2e"


def _create_test_app(agent, pool) -> FastAPI:
    """Minimal FastAPI app with web router and test app.state."""
    app = FastAPI()
    app.include_router(web_router)

    settings = _make_settings(session_secret=_TEST_SESSION_SECRET)
    app.state.settings = settings
    app.state.agent = agent
    app.state.history = agent.history
    app.state.settings_store = AsyncMock()
    # user_store.get_by_id returns a test user row
    user_store = AsyncMock()
    user_store.get_by_id = AsyncMock(
        return_value={"id": 1, "email": "test@test.com", "is_admin": True}
    )
    app.state.user_store = user_store
    app.state.wa_store = None
    app.state.vikunja_provisioner = None
    app.state.shutdown_event = asyncio.Event()
    app.state.http_clients = AsyncMock()
    app.state.notion_retriever = None
    app.state.pool = pool

    return app


def _make_session_cookie(uid: int = 1) -> str:
    """Create a signed session cookie for the test user."""
    serializer = URLSafeTimedSerializer(_TEST_SESSION_SECRET)
    return serializer.dumps(
        {
            "uid": uid,
            "email": "test@test.com",
            "display_name": "Test User",
            "avatar_url": "",
        }
    )


def _auth_cookies() -> dict[str, str]:
    """Session + CSRF cookies for authenticated requests."""
    return {
        SESSION_COOKIE_NAME: _make_session_cookie(),
        CSRF_COOKIE_NAME: _CSRF_TOKEN,
    }


def _csrf_headers() -> dict[str, str]:
    """CSRF header matching the cookie."""
    return {"x-csrf-token": _CSRF_TOKEN}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(loop_scope="session")
async def app_client(pool_in_tx):
    """httpx.AsyncClient with ASGI transport against the test app."""
    fake = FakeLLM([{"content": "Standard-Antwort."}])
    agent = make_e2e_agent(pool_in_tx, fake)
    app = _create_test_app(agent, pool_in_tx)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


# ---------------------------------------------------------------------------
# Auth tests
# ---------------------------------------------------------------------------


class TestAuthFlow:
    async def test_no_auth_returns_401(self, app_client):
        """POST without session cookie → 401."""
        resp = await app_client.post(
            "/ui/api/chat/stream",
            data={"message": "hi"},
        )
        assert resp.status_code == 401

    async def test_no_csrf_returns_403(self, app_client):
        """POST with session but no CSRF → 403."""
        resp = await app_client.post(
            "/ui/api/chat/stream",
            data={"message": "hi"},
            cookies={SESSION_COOKIE_NAME: _make_session_cookie()},
        )
        assert resp.status_code == 403

    async def test_valid_auth_returns_sse(self, pool_in_tx):
        """POST with valid auth → 200 text/event-stream."""
        fake = FakeLLM([{"content": "Hallo!"}])
        agent = make_e2e_agent(pool_in_tx, fake)
        app = _create_test_app(agent, pool_in_tx)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            resp = await client.post(
                "/ui/api/chat/stream",
                data={"message": "Hallo"},
                cookies=_auth_cookies(),
                headers=_csrf_headers(),
            )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")


# ---------------------------------------------------------------------------
# SSE streaming tests
# ---------------------------------------------------------------------------


class TestSSEStreaming:
    async def test_sse_format(self, pool_in_tx):
        """SSE events follow 'data: {json}\\n\\n' format."""
        fake = FakeLLM([{"content": "Antwort vom Butler."}])
        agent = make_e2e_agent(pool_in_tx, fake)
        app = _create_test_app(agent, pool_in_tx)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            resp = await client.post(
                "/ui/api/chat/stream",
                data={"message": "Test"},
                cookies=_auth_cookies(),
                headers=_csrf_headers(),
            )
        body = resp.text
        # Each SSE line starts with "data: " and is valid JSON
        lines = [ln for ln in body.strip().split("\n") if ln.startswith("data: ")]
        assert len(lines) >= 2  # At least one chunk + done
        for line in lines:
            payload = json.loads(line.removeprefix("data: "))
            assert "type" in payload

    async def test_sse_ends_with_done(self, pool_in_tx):
        """Last SSE event is always {"type": "done"}."""
        fake = FakeLLM([{"content": "Fertig."}])
        agent = make_e2e_agent(pool_in_tx, fake)
        app = _create_test_app(agent, pool_in_tx)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            resp = await client.post(
                "/ui/api/chat/stream",
                data={"message": "Test"},
                cookies=_auth_cookies(),
                headers=_csrf_headers(),
            )
        lines = [ln for ln in resp.text.strip().split("\n") if ln.startswith("data: ")]
        last_event = json.loads(lines[-1].removeprefix("data: "))
        assert last_event == {"type": "done"}

    async def test_sse_tool_status_events(self, pool_in_tx, seed_contact):
        """Tool execution emits status events in the SSE stream."""
        fake = FakeLLM(
            [
                {
                    "tool_calls": [
                        {
                            "name": "find_contact",
                            "arguments": {"name": "Max Mustermann"},
                        }
                    ]
                },
                {"content": "Max gefunden."},
            ]
        )
        agent = make_e2e_agent(pool_in_tx, fake)
        app = _create_test_app(agent, pool_in_tx)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            resp = await client.post(
                "/ui/api/chat/stream",
                data={"message": "Nummer von Max?"},
                cookies=_auth_cookies(),
                headers=_csrf_headers(),
            )
        lines = [ln for ln in resp.text.strip().split("\n") if ln.startswith("data: ")]
        events = [json.loads(ln.removeprefix("data: ")) for ln in lines]
        types = [e["type"] for e in events]
        assert "status" in types
        assert "chunk" in types
        assert types[-1] == "done"


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


class TestInputValidation:
    async def test_message_too_long(self, pool_in_tx):
        """Message over 2000 chars → 400."""
        fake = FakeLLM([{"content": "nope"}])
        agent = make_e2e_agent(pool_in_tx, fake)
        app = _create_test_app(agent, pool_in_tx)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            resp = await client.post(
                "/ui/api/chat/stream",
                data={"message": "x" * 2001},
                cookies=_auth_cookies(),
                headers=_csrf_headers(),
            )
        assert resp.status_code == 400
