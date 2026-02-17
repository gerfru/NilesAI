"""Shared pytest fixtures."""

import os

import pytest


@pytest.fixture(autouse=True)
def _set_test_env(monkeypatch):
    """Set required environment variables for tests."""
    monkeypatch.setenv("POSTGRES_PASSWORD", "test-password")
    monkeypatch.setenv("EVOLUTION_API_KEY", "test-api-key")
