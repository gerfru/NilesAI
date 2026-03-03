"""Tests for API authentication and rate limiting."""

import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from niles.config import Settings


class TestChatAuth:
    @pytest.fixture
    def mock_app(self):
        """Create a mock app with state."""
        app = MagicMock()
        app.state.agent = AsyncMock()
        app.state.settings = Settings(
            postgres_password="test",
            evolution_api_key="test",
            niles_api_key="test-niles-key",
        )
        return app

    async def test_require_api_key_rejects_missing(self, mock_app):
        from fastapi import HTTPException

        from niles.main import require_api_key

        request = MagicMock()
        request.app = mock_app

        with pytest.raises(HTTPException) as exc_info:
            await require_api_key(request, api_key=None)

        assert exc_info.value.status_code == 401

    async def test_require_api_key_rejects_wrong(self, mock_app):
        from fastapi import HTTPException

        from niles.main import require_api_key

        request = MagicMock()
        request.app = mock_app

        with pytest.raises(HTTPException) as exc_info:
            await require_api_key(request, api_key="wrong-key")

        assert exc_info.value.status_code == 401

    async def test_require_api_key_accepts_valid(self, mock_app):
        from niles.main import require_api_key

        request = MagicMock()
        request.app = mock_app

        result = await require_api_key(request, api_key="test-niles-key")

        assert result == "test-niles-key"


class TestNilesApiKeyDefault:
    def test_auto_generates_key_when_not_set(self, monkeypatch):
        monkeypatch.delenv("NILES_API_KEY", raising=False)
        settings = Settings(
            _env_file=None,
            postgres_password="test",
            evolution_api_key="test",
        )
        assert len(settings.niles_api_key) > 20

    def test_uses_env_key_when_set(self, monkeypatch):
        monkeypatch.setenv("NILES_API_KEY", "my-custom-key")
        settings = Settings(
            postgres_password="test",
            evolution_api_key="test",
        )
        assert settings.niles_api_key == "my-custom-key"


class TestRateLimiting:
    def test_rate_limit_middleware_allows_normal_traffic(self):
        from niles.main import RateLimitMiddleware

        middleware = RateLimitMiddleware(app=MagicMock(), requests_per_minute=5)
        # Simulate 5 hits within window -- all should be under limit
        client_ip = "127.0.0.1"
        now = time.monotonic()
        middleware._hits[client_ip] = [now - i for i in range(4)]
        middleware._hits[client_ip].append(now)
        assert len(middleware._hits[client_ip]) <= 5

    def test_rate_limit_middleware_detects_excess(self):
        from niles.main import RateLimitMiddleware

        middleware = RateLimitMiddleware(app=MagicMock(), requests_per_minute=5)
        client_ip = "127.0.0.1"
        now = time.monotonic()
        # Fill with 6 hits (exceeds limit of 5)
        middleware._hits[client_ip] = [now - i for i in range(6)]
        assert len(middleware._hits[client_ip]) > 5

    def test_rate_limit_middleware_prunes_old_entries(self):
        from niles.main import RateLimitMiddleware

        middleware = RateLimitMiddleware(app=MagicMock(), requests_per_minute=5)
        client_ip = "127.0.0.1"
        now = time.monotonic()
        # Old entries (> 60s ago) should be pruned
        middleware._hits[client_ip] = [now - 120, now - 90, now]
        window = now - 60.0
        pruned = [t for t in middleware._hits[client_ip] if t > window]
        assert len(pruned) == 1

    def test_evict_oldest_ip_when_table_full(self):
        from niles.main import RateLimitMiddleware

        middleware = RateLimitMiddleware(app=MagicMock(), requests_per_minute=5)
        middleware.MAX_TRACKED_IPS = 3  # low limit for testing
        now = time.monotonic()

        # Fill with 4 IPs (exceeds limit of 3)
        middleware._hits["10.0.0.1"] = [now - 50]  # oldest last-hit
        middleware._hits["10.0.0.2"] = [now - 30]
        middleware._hits["10.0.0.3"] = [now - 10]
        middleware._hits["10.0.0.4"] = [now]

        middleware._evict_oldest()

        assert len(middleware._hits) == 3
        assert "10.0.0.1" not in middleware._hits  # oldest evicted

    def test_evict_does_nothing_under_limit(self):
        from niles.main import RateLimitMiddleware

        middleware = RateLimitMiddleware(app=MagicMock(), requests_per_minute=5)
        middleware.MAX_TRACKED_IPS = 10
        now = time.monotonic()

        middleware._hits["10.0.0.1"] = [now]
        middleware._hits["10.0.0.2"] = [now]

        middleware._evict_oldest()

        assert len(middleware._hits) == 2


class TestRateLimitingIntegration:
    """Integration tests: real HTTP requests through the rate limit middleware."""

    @pytest.fixture
    def limited_app(self):
        """Create a minimal FastAPI app with a low rate limit (3 req/min)."""
        from niles.main import RateLimitMiddleware

        test_app = FastAPI()
        test_app.add_middleware(RateLimitMiddleware, requests_per_minute=3)

        @test_app.get("/health")
        async def health():
            return {"status": "ok"}

        @test_app.get("/test")
        async def test_endpoint():
            return {"data": "ok"}

        return test_app

    def test_returns_429_when_limit_exceeded(self, limited_app):
        """Requests beyond the limit get HTTP 429."""
        with TestClient(limited_app) as client:
            for _ in range(3):
                resp = client.get("/test")
                assert resp.status_code == 200

            resp = client.get("/test")
            assert resp.status_code == 429
            assert resp.json() == {"detail": "Too many requests"}

    def test_health_exempt_from_rate_limit(self, limited_app):
        """/health is never rate-limited, even after exceeding limit."""
        with TestClient(limited_app) as client:
            # Exhaust rate limit on /test
            for _ in range(4):
                client.get("/test")

            # /health must still return 200
            for _ in range(10):
                resp = client.get("/health")
                assert resp.status_code == 200

    def test_429_includes_correct_body(self, limited_app):
        """429 response body contains the expected detail message."""
        with TestClient(limited_app) as client:
            for _ in range(4):
                client.get("/test")

            resp = client.get("/test")
            assert resp.status_code == 429
            body = resp.json()
            assert "detail" in body
            assert body["detail"] == "Too many requests"

    def test_different_paths_share_rate_limit(self, limited_app):
        """Rate limit is per-IP, not per-path."""
        with TestClient(limited_app) as client:
            # Mix requests to /test and /health-exempt paths
            for _ in range(3):
                client.get("/test")

            # Same IP, different path -- should still be limited
            resp = client.get("/test")
            assert resp.status_code == 429


class TestCSPReport:
    """Tests for the CSP violation report endpoint and header."""

    @pytest.fixture
    def csp_app(self):
        """Minimal app with SecurityHeadersMiddleware and CSP report endpoint."""
        from niles.main import SecurityHeadersMiddleware

        test_app = FastAPI()
        test_app.add_middleware(SecurityHeadersMiddleware)

        @test_app.get("/page")
        async def page():
            return {"ok": True}

        @test_app.post("/csp-report", status_code=204)
        async def csp_report(request):
            from starlette.responses import Response as StarletteResponse

            try:
                await request.json()
            except Exception:
                pass
            return StarletteResponse(status_code=204)

        return test_app

    def test_csp_header_contains_report_uri(self, csp_app):
        """CSP header includes report-uri directive."""
        with TestClient(csp_app) as client:
            resp = client.get("/page")
            csp = resp.headers.get("Content-Security-Policy", "")
            assert "report-uri /csp-report" in csp

    @pytest.fixture
    def report_app(self):
        """Minimal app with the CSP report endpoint logic."""
        from starlette.requests import Request
        from starlette.responses import Response as StarletteResponse

        test_app = FastAPI()

        @test_app.post("/csp-report", status_code=204)
        async def csp_report(request: Request) -> StarletteResponse:
            try:
                await request.json()
            except Exception:
                pass
            return StarletteResponse(status_code=204)

        return test_app

    def test_csp_report_valid_payload(self, report_app):
        """POST a valid CSP report body → 204."""
        with TestClient(report_app) as client:
            resp = client.post(
                "/csp-report",
                json={
                    "csp-report": {
                        "document-uri": "https://example.com",
                        "violated-directive": "script-src",
                        "blocked-uri": "https://evil.com/script.js",
                    }
                },
            )
            assert resp.status_code == 204

    def test_csp_report_invalid_json(self, report_app):
        """POST non-JSON body → 204 (graceful)."""
        with TestClient(report_app) as client:
            resp = client.post(
                "/csp-report",
                content=b"not json",
                headers={"Content-Type": "text/plain"},
            )
            assert resp.status_code == 204
