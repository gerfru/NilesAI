"""Tests for EchoGuard — TTL-based echo-loop prevention."""

from unittest.mock import patch

from niles.sources.echo_guard import EchoGuard


class TestEchoGuard:
    def test_record_and_detect(self):
        guard = EchoGuard(ttl=5.0)
        guard.record("msg-123")
        assert guard.is_echo("msg-123") is True

    def test_unknown_key_is_not_echo(self):
        guard = EchoGuard(ttl=5.0)
        assert guard.is_echo("unknown") is False

    def test_expired_key_is_not_echo(self):
        guard = EchoGuard(ttl=1.0)
        with patch("niles.sources.echo_guard.time.monotonic", return_value=100.0):
            guard.record("msg-old")
        with patch("niles.sources.echo_guard.time.monotonic", return_value=102.0):
            assert guard.is_echo("msg-old") is False

    def test_pruning_removes_expired_keys(self):
        guard = EchoGuard(ttl=1.0)
        with patch("niles.sources.echo_guard.time.monotonic", return_value=100.0):
            guard.record("old-key")
        # Record a new key 2 seconds later — should prune old-key
        with patch("niles.sources.echo_guard.time.monotonic", return_value=102.0):
            guard.record("new-key")
        assert "old-key" not in guard._cache
        assert "new-key" in guard._cache

    def test_multiple_keys_tracked(self):
        guard = EchoGuard(ttl=10.0)
        guard.record("a")
        guard.record("b")
        assert guard.is_echo("a") is True
        assert guard.is_echo("b") is True
        assert guard.is_echo("c") is False
