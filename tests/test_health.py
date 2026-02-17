"""Tests for the health endpoint."""

from fastapi.testclient import TestClient

from niles.main import app

client = TestClient(app)


def test_health_returns_ok():
    """GET /health returns status ok."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
