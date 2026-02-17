"""Tests for the health endpoint."""

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from niles.main import app


@patch("niles.main.asyncpg.create_pool", new_callable=AsyncMock)
def test_health_returns_ok(mock_pool):
    """GET /health returns status ok."""
    mock_pool.return_value = AsyncMock()
    mock_pool.return_value.close = AsyncMock()

    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
