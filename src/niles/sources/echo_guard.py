# SPDX-License-Identifier: AGPL-3.0-only
"""TTL-based echo-loop guard for messaging sources.

Prevents infinite loops when outgoing messages are echoed back by the
messaging platform. Each source uses its own EchoGuard instance with
an appropriate key (message ID for WhatsApp, text prefix for Signal).
"""

import time


class EchoGuard:
    """Track recently sent keys to detect echoes."""

    def __init__(self, ttl: float = 10.0):
        self._cache: dict[str, float] = {}
        self._ttl = ttl

    def record(self, key: str) -> None:
        """Record a key we just sent (with TTL-based pruning)."""
        now = time.monotonic()
        self._cache[key] = now
        expired = [k for k, v in self._cache.items() if now - v > self._ttl]
        for k in expired:
            del self._cache[k]

    def is_echo(self, key: str) -> bool:
        """Check if a key matches something we recently sent."""
        ts = self._cache.get(key)
        if ts is None:
            return False
        return (time.monotonic() - ts) <= self._ttl
