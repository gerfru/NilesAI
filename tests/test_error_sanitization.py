"""Tests for error message sanitization."""

import httpx

from niles.errors import sanitize_error


class TestSanitizeError:
    def test_strips_http_url(self):
        exc = httpx.ConnectError("Connection refused: http://evolution_api:8080/message/send")
        result = sanitize_error(exc)
        assert "evolution_api" not in result
        assert "<internal-service>" in result

    def test_strips_https_url(self):
        exc = httpx.ConnectError("Failed: https://signal_api:8080/v1/send")
        result = sanitize_error(exc)
        assert "signal_api" not in result

    def test_preserves_non_url_message(self):
        exc = ValueError("Invalid phone number format")
        result = sanitize_error(exc)
        assert result == "Invalid phone number format"

    def test_strips_multiple_urls(self):
        exc = httpx.HTTPError("Redirect from http://a:80/x to http://b:80/y")
        result = sanitize_error(exc)
        assert "a:80" not in result
        assert "b:80" not in result
