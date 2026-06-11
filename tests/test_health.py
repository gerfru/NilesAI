"""Tests for the health endpoint."""

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from niles.main import app


def _make_mock_pool():
    """Create a mock pool with sync pool-info methods and async DB methods."""
    pool = MagicMock()
    pool.execute = AsyncMock()
    pool.fetch = AsyncMock(return_value=[])
    pool.fetchrow = AsyncMock(return_value=None)
    pool.fetchval = AsyncMock(return_value=0)
    pool.close = AsyncMock()
    pool.get_size.return_value = 2
    pool.get_idle_size.return_value = 2
    pool.get_min_size.return_value = 2
    pool.get_max_size.return_value = 10
    return pool


@patch("niles.startup.asyncpg.create_pool", new_callable=AsyncMock)
def test_health_returns_ok(mock_create_pool):
    """GET /health returns status ok with DB pool info."""
    mock_create_pool.return_value = _make_mock_pool()

    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["db_pool"]["size"] == 2
        assert data["db_pool"]["max"] == 10
