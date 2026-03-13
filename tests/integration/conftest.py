"""Integration test fixtures — real services, no mocking.

These fixtures connect to real PostgreSQL, Ollama, Evolution API, Vikunja,
Signal API, and SearXNG instances.  Tests skip gracefully when a required
service is not reachable.
"""

from __future__ import annotations

import asyncio
import os
import warnings
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import asyncpg
import httpx
import pytest
import pytest_asyncio

# Suppress InsecureRequestWarning from verify=False (self-signed Caddy certs)
warnings.filterwarnings("ignore", message="Unverified HTTPS request")


# ---------------------------------------------------------------------------
# Environment helpers
# ---------------------------------------------------------------------------


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


POSTGRES_HOST = _env("POSTGRES_HOST", "127.0.0.1")
POSTGRES_PORT = int(_env("POSTGRES_HOST_PORT", "5432"))
POSTGRES_DB = _env("POSTGRES_DB", "evolution_db")
POSTGRES_USER = _env("POSTGRES_USER", "evolution")
POSTGRES_PASSWORD = _env("EVOLUTION_POSTGRES_PASSWORD", "")

EVOLUTION_API_URL = _env("EVOLUTION_API_URL", "http://127.0.0.1:8080")
EVOLUTION_API_KEY = _env("EVOLUTION_API_KEY", "")
EVOLUTION_INSTANCE = _env("EVOLUTION_INSTANCE", "niles-whatsapp")

VIKUNJA_API_URL = _env("VIKUNJA_API_URL", "")
VIKUNJA_API_TOKEN = _env("VIKUNJA_API_TOKEN", "")

SIGNAL_API_URL = _env("SIGNAL_API_URL", "http://127.0.0.1:8080")
SIGNAL_PHONE = _env("SIGNAL_PHONE_NUMBER", "")

OLLAMA_BASE_URL = _env("LLM_BASE_URL", "http://127.0.0.1:11434/v1")

SEARXNG_URL = _env("SEARXNG_URL", "http://127.0.0.1:8888")


# ---------------------------------------------------------------------------
# SingleConnectionPool — wraps a Connection to satisfy the Pool interface
# ---------------------------------------------------------------------------


class SingleConnectionPool:
    """Adapter: makes a single asyncpg.Connection look like a Pool.

    Used for transaction-rollback test isolation.  All queries run on
    the same connection (inside an outer transaction that will be
    rolled back after the test).
    """

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
        """Yield the wrapped connection (no actual acquire/release)."""
        yield self._conn


# ---------------------------------------------------------------------------
# Database fixtures — all use session loop_scope so they share one event loop
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def db_pool():
    """Session-scoped asyncpg pool to real PostgreSQL.

    Skips all integration tests if the database is unreachable.
    """
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

    # Verify migrations are applied
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
# Service availability fixtures (session-scoped probes)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def evolution_client():
    """httpx client for Evolution API. Skips if unreachable."""
    if not EVOLUTION_API_KEY:
        pytest.skip("EVOLUTION_API_KEY not set")
    client = httpx.AsyncClient(
        headers={"apikey": EVOLUTION_API_KEY},
        timeout=10,
        verify=False,
    )
    try:
        resp = await client.get(f"{EVOLUTION_API_URL}/")
        resp.raise_for_status()
    except (httpx.ConnectError, httpx.HTTPError):
        await client.aclose()
        pytest.skip(f"Evolution API not reachable at {EVOLUTION_API_URL}")
        return
    yield client
    await client.aclose()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def vikunja_available():
    """Check Vikunja API reachability."""
    if not VIKUNJA_API_URL or not VIKUNJA_API_TOKEN:
        pytest.skip("VIKUNJA_API_URL or VIKUNJA_API_TOKEN not set")
    async with httpx.AsyncClient(timeout=5, verify=False) as client:
        try:
            resp = await client.get(
                f"{VIKUNJA_API_URL}/info",
                headers={"Authorization": f"Bearer {VIKUNJA_API_TOKEN}"},
            )
            resp.raise_for_status()
            # Verify we get actual JSON (not an empty proxy response)
            data = resp.json()
            if not data:
                pytest.skip(f"Vikunja returned empty response at {VIKUNJA_API_URL}")
        except (httpx.ConnectError, httpx.HTTPError, ValueError):
            pytest.skip(f"Vikunja not reachable at {VIKUNJA_API_URL}")


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def signal_available():
    """Check Signal API reachability."""
    if not SIGNAL_PHONE:
        pytest.skip("SIGNAL_PHONE_NUMBER not set")
    async with httpx.AsyncClient(timeout=5) as client:
        try:
            resp = await client.get(f"{SIGNAL_API_URL}/v1/about")
            resp.raise_for_status()
        except (httpx.ConnectError, httpx.HTTPError):
            pytest.skip(f"Signal API not reachable at {SIGNAL_API_URL}")


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def ollama_available():
    """Check Ollama reachability."""
    ollama_url = OLLAMA_BASE_URL.removesuffix("/v1")
    async with httpx.AsyncClient(timeout=5) as client:
        try:
            resp = await client.get(f"{ollama_url}/api/tags")
            resp.raise_for_status()
        except (httpx.ConnectError, httpx.HTTPError):
            pytest.skip(f"Ollama not reachable at {ollama_url}")


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def searxng_available():
    """Check SearXNG reachability."""
    async with httpx.AsyncClient(timeout=5) as client:
        try:
            resp = await client.get(f"{SEARXNG_URL}/")
            resp.raise_for_status()
        except (httpx.ConnectError, httpx.HTTPError):
            pytest.skip(f"SearXNG not reachable at {SEARXNG_URL}")


# ---------------------------------------------------------------------------
# Test data seeding fixtures
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
    return {"id": contact_id, "full_name": "Max Mustermann", "phone": "436601234567"}


@pytest_asyncio.fixture(loop_scope="session")
async def seed_calendar_source(db_conn, seed_user):
    """Insert a test calendar source owned by the test user."""
    source_id = await db_conn.fetchval(
        """
        INSERT INTO calendar_sources (name, url, source_type, writable, enabled, user_id)
        VALUES ('Test Calendar', 'https://example.com/cal.ics', 'ics', false, true, $1)
        RETURNING id
        """,
        seed_user,
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


@pytest_asyncio.fixture(loop_scope="session")
async def seed_user(db_conn):
    """Insert a test user."""
    user_id = await db_conn.fetchval(
        """
        INSERT INTO users (email, display_name, auth_method, is_admin)
        VALUES ('test@example.com', 'Test User', 'password', true)
        RETURNING id
        """,
    )
    return user_id
