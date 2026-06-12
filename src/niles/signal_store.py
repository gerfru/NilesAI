# SPDX-License-Identifier: AGPL-3.0-only
"""Signal message storage backed by PostgreSQL.

signal-cli-rest-api has no message history API (unlike Evolution API's findMessages),
so incoming and outgoing messages are stored locally.
"""

import logging
from datetime import datetime, timedelta, timezone

import asyncpg

from niles.types import SignalMessage

logger = logging.getLogger(__name__)

_MAX_AGE_DAYS = 30


class SignalMessageStore:
    """Store and retrieve Signal messages in PostgreSQL."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def store(
        self,
        phone: str,
        text: str,
        from_me: bool,
        chat_id: str = "",
    ) -> None:
        """Store a single message."""
        await self.pool.execute(
            "INSERT INTO signal_messages (phone, text, from_me, timestamp, chat_id) VALUES ($1, $2, $3, NOW(), $4)",
            phone,
            text,
            from_me,
            chat_id,
        )

    async def get_messages(
        self,
        phone: str,
        days: int = _MAX_AGE_DAYS,
        limit: int = 200,
    ) -> list[SignalMessage]:
        """Fetch messages for a phone number (last N days).

        Returns list of dicts with keys: from_me, text, timestamp, phone.
        Sorted by timestamp ascending (oldest first).
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        rows = await self.pool.fetch(
            "SELECT phone, text, from_me, timestamp "
            "FROM signal_messages "
            "WHERE phone = $1 AND timestamp >= $2 "
            "ORDER BY timestamp ASC "
            "LIMIT $3",
            phone,
            cutoff,
            limit,
        )
        return [
            {
                "from_me": r["from_me"],
                "text": r["text"],
                "timestamp": int(r["timestamp"].timestamp()),
                "phone": r["phone"],
            }
            for r in rows
        ]
