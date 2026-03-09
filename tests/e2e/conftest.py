"""E2E test fixtures — FakeLLM + real DB, no external HTTP services.

Pipeline tests use FakeLLM for deterministic tool-call sequences while
running real DB queries through ContactsAction, MemoryStore, etc.
"""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import asyncpg
import pytest
import pytest_asyncio

from niles.actions.calendar import CalendarAction
from niles.actions.contacts import ContactsAction
from niles.agent.core import NilesAgent
from niles.config import Settings
from niles.memory.history import ConversationHistory
from niles.memory.store import MemoryStore

from .fake_llm import FakeLLM


# ---------------------------------------------------------------------------
# Score collection for benchmark
# ---------------------------------------------------------------------------

_score_results: list[dict] = []


def record_score(test_name: str, scores: dict) -> None:
    """Record judge scores for benchmark output."""
    _score_results.append(
        {
            "test": test_name,
            "model": os.environ.get("LLM_MODEL", "unknown"),
            "scores": scores,
        }
    )


def pytest_sessionfinish(session, exitstatus):
    """Write collected scores to JSON if SCORE_OUTPUT is set."""
    output = os.environ.get("SCORE_OUTPUT")
    if output and _score_results:
        Path(output).write_text(json.dumps(_score_results, indent=2))


# ---------------------------------------------------------------------------
# Environment helpers (reuse integration test defaults)
# ---------------------------------------------------------------------------


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


POSTGRES_HOST = _env("POSTGRES_HOST", "127.0.0.1")
# POSTGRES_HOST_PORT: Docker Compose exposed port on the host (matches docker-compose.yml)
POSTGRES_PORT = int(_env("POSTGRES_HOST_PORT", "5432") or "5432")
POSTGRES_DB = _env("POSTGRES_DB", "evolution_db")
POSTGRES_USER = _env("POSTGRES_USER", "evolution")
POSTGRES_PASSWORD = _env("EVOLUTION_POSTGRES_PASSWORD", "")


# ---------------------------------------------------------------------------
# SingleConnectionPool — transaction-rollback isolation
# ---------------------------------------------------------------------------


class SingleConnectionPool:
    """Adapter: makes a single asyncpg.Connection look like a Pool."""

    def __init__(self, conn: asyncpg.Connection):
        self._conn = conn

    async def fetch(self, query: str, *args, **kwargs):
        return await self._conn.fetch(query, *args, **kwargs)

    async def fetchrow(self, query: str, *args, **kwargs):
        return await self._conn.fetchrow(query, *args, **kwargs)

    async def fetchval(self, query: str, *args, **kwargs):
        return await self._conn.fetchval(query, *args, **kwargs)

    async def execute(self, query: str, *args, **kwargs):
        return await self._conn.execute(query, *args, **kwargs)

    @asynccontextmanager
    async def acquire(self):
        yield self._conn


# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def db_pool():
    """Session-scoped asyncpg pool. Skips if PostgreSQL unreachable."""
    if not POSTGRES_PASSWORD:
        pytest.skip("EVOLUTION_POSTGRES_PASSWORD not set")

    try:
        pool = await asyncpg.create_pool(
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            database=POSTGRES_DB,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            min_size=1,
            max_size=5,
            timeout=5,
        )
    except (OSError, asyncpg.PostgresError, asyncio.TimeoutError):
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_HOST}:{POSTGRES_PORT}")
        return

    try:
        version = await pool.fetchval("SELECT version_num FROM alembic_version LIMIT 1")
        assert version is not None, "Alembic migrations not applied"
    except Exception:
        await pool.close()
        pytest.skip("Database not migrated")
        return

    yield pool
    await pool.close()


@pytest_asyncio.fixture(scope="function", loop_scope="session")
async def db_conn(db_pool):
    """Per-test connection inside a transaction (rolled back after test)."""
    conn = await db_pool.acquire()
    tx = conn.transaction()
    await tx.start()
    yield conn
    await tx.rollback()
    await db_pool.release(conn)


@pytest_asyncio.fixture(loop_scope="session")
async def pool_in_tx(db_conn):
    """Pool-like adapter over the transactional connection."""
    return SingleConnectionPool(db_conn)


# ---------------------------------------------------------------------------
# Agent factory
# ---------------------------------------------------------------------------


def _make_settings(**overrides):
    defaults = dict(
        _env_file=None,
        postgres_password="test",
        evolution_api_key="test",
        niles_api_key="test",
    )
    defaults.update(overrides)
    return Settings(**defaults)


def _make_agent_core(pool) -> NilesAgent:
    """Build a NilesAgent with real DB stores (no LLM assigned)."""
    config = _make_settings()
    contacts = ContactsAction(pool)
    memory = MemoryStore(pool)
    history = ConversationHistory(pool)
    calendar = CalendarAction(pool, timezone="Europe/Vienna")
    whatsapp = AsyncMock()

    with patch("niles.agent.core.load_system_prompt", return_value="Du bist Niles."):
        agent = NilesAgent(
            config=config,
            contacts=contacts,
            whatsapp=whatsapp,
            memory=memory,
            history=history,
            calendar=calendar,
        )
    return agent


def make_real_agent(pool) -> NilesAgent:
    """Build a NilesAgent with real DB stores and the real (Ollama) LLM."""
    return _make_agent_core(pool)


def make_e2e_agent(pool, fake_llm: FakeLLM) -> NilesAgent:
    """Build a NilesAgent with real DB stores but a scripted FakeLLM."""
    agent = _make_agent_core(pool)
    agent.llm = fake_llm
    return agent


# ---------------------------------------------------------------------------
# Event collection helper
# ---------------------------------------------------------------------------


async def collect_events(agent: NilesAgent, message: str, chat_id: str = "e2e-test"):
    """Run agent.process_event_stream and collect all yielded events."""
    event = {"type": "web", "from": chat_id, "content": message}
    events = []
    async for item in agent.process_event_stream(event):
        events.append(item)
    return events


def full_text(events: list[dict]) -> str:
    """Extract the full response text from collected SSE events."""
    return "".join(e["text"] for e in events if e.get("type") == "chunk")


# ---------------------------------------------------------------------------
# Test data seeding
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(loop_scope="session")
async def seed_contact(db_conn):
    """Insert a test contact with phone number."""
    contact_id = await db_conn.fetchval(
        """
        INSERT INTO contacts (full_name, first_name, last_name, email)
        VALUES ('Max Mustermann', 'Max', 'Mustermann', 'max@example.com')
        RETURNING id
        """,
    )
    await db_conn.execute(
        """
        INSERT INTO contact_phones (contact_id, type, number)
        VALUES ($1, 'mobile', '+43 660 1234567')
        """,
        contact_id,
    )
    return {"id": contact_id, "full_name": "Max Mustermann", "phone": "+43 660 1234567"}


@pytest_asyncio.fixture(loop_scope="session")
async def seed_calendar_source(db_conn):
    """Insert a test calendar source."""
    source_id = await db_conn.fetchval(
        """
        INSERT INTO calendar_sources (name, url, source_type, writable, enabled)
        VALUES ('Test Calendar', 'https://example.com/cal.ics', 'ics', false, true)
        RETURNING id
        """,
    )
    return source_id


@pytest_asyncio.fixture(loop_scope="session")
async def seed_events(db_conn, seed_calendar_source):
    """Insert test calendar events (today + tomorrow)."""
    now = datetime.now(timezone.utc)
    tomorrow = now + timedelta(days=1)
    await db_conn.execute(
        """
        INSERT INTO events (summary, dtstart, dtend, all_day, description, location, source_id)
        VALUES
            ('Team Meeting', $1, $2, false, 'Weekly standup', 'Office', $5),
            ('Dentist Appointment', $3, $4, false, '', '', $5)
        """,
        now + timedelta(hours=2),
        now + timedelta(hours=3),
        tomorrow.replace(hour=10, minute=0, second=0, microsecond=0),
        tomorrow.replace(hour=11, minute=0, second=0, microsecond=0),
        seed_calendar_source,
    )
