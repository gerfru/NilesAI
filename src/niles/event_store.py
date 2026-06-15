# SPDX-License-Identifier: AGPL-3.0-only
"""Data-access for calendar events (events ⋈ calendar_sources reads).

Calendar *source* CRUD lives in CalendarSourceManager; this store covers the
read queries the agent (search) and briefing layers used to run inline.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime

import asyncpg


class EventStore:
    """Read queries over the events table, scoped by calendar-source ownership."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def resolve_source_id(self, name: str, user_id: int | None = None) -> int | None:
        """Resolve a calendar source name to its ID (optionally user-scoped)."""
        row = await self.pool.fetchrow(
            "SELECT id FROM calendar_sources WHERE LOWER(name) = LOWER($1) AND ($2::integer IS NULL OR user_id = $2)",
            name,
            user_id,
        )
        return row["id"] if row else None

    async def search(
        self,
        query: str,
        ts_from: datetime | None,
        ts_to: datetime | None,
        source_id: int | None,
        user_id: int | None,
    ) -> Sequence[Mapping]:
        """Search events by keyword and/or date range (max 10, dtstart ASC)."""
        return await self.pool.fetch(
            """
            SELECT e.summary, e.dtstart, e.dtend, e.all_day,
                   e.description, e.location, e.transp
            FROM events e
            LEFT JOIN calendar_sources cs ON e.source_id = cs.id
            WHERE ($1 = '' OR e.summary ILIKE '%' || $1 || '%'
                   OR e.description ILIKE '%' || $1 || '%'
                   OR e.location ILIKE '%' || $1 || '%')
              AND ($2::timestamptz IS NULL OR e.dtstart >= $2)
              AND ($3::timestamptz IS NULL OR e.dtstart <= $3)
              AND ($4::integer IS NULL OR e.source_id = $4)
              AND ($5::integer IS NULL OR cs.user_id = $5)
            ORDER BY e.dtstart ASC
            LIMIT 10
            """,
            query,
            ts_from,
            ts_to,
            source_id,
            user_id,
        )

    async def in_range(
        self,
        date_from: datetime,
        date_to: datetime,
        user_id: int | None = None,
    ) -> Sequence[Mapping]:
        """Fetch events in a date range with their calendar name (for briefings)."""
        return await self.pool.fetch(
            """
            SELECT e.summary, e.dtstart, e.dtend, e.all_day, e.location,
                   cs.name AS calendar_name
            FROM events e
            LEFT JOIN calendar_sources cs ON e.source_id = cs.id
            WHERE e.dtstart >= $1 AND e.dtstart <= $2
              AND ($3::integer IS NULL OR cs.user_id = $3)
            ORDER BY e.dtstart ASC
            """,
            date_from,
            date_to,
            user_id,
        )
