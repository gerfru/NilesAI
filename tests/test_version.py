"""Tests for app version wiring (W20).

The FastAPI app version must be sourced from the installed package metadata
(`importlib.metadata.version("niles-core")`) rather than a hardcoded literal,
so the OpenAPI/docs version never drifts from pyproject again.
"""

from importlib.metadata import version

from niles.main import app


def test_app_version_matches_package_metadata():
    """app.version is read from the installed niles-core distribution."""
    assert app.version == version("niles-core")


def test_app_version_is_not_the_stale_placeholder():
    """Regression guard: the old hardcoded '0.1.0' must not come back."""
    assert app.version not in ("0.1.0", "dev")
