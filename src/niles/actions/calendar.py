"""Calendar event lookup in PostgreSQL."""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import asyncpg

logger = logging.getLogger(__name__)


class CalendarAction:
    """Search calendar events by keyword and/or date range."""

    def __init__(self, pool: asyncpg.Pool, timezone: str = "Europe/Vienna"):
        self.pool = pool
        self.tz = ZoneInfo(timezone)

    async def find_by_query(
        self,
        query: str = "",
        date_from: str = "",
        date_to: str = "",
    ) -> list[dict]:
        """
        Search events by keyword and/or date range.

        Args:
            query: Search term (matches summary, description, location)
            date_from: Start date (ISO format, e.g. '2026-02-20')
            date_to: End date (ISO format, e.g. '2026-02-28')

        Returns:
            List of event dicts (max 10), sorted by dtstart ascending.
        """
        # Parse date parameters; default to "from now" when no range given
        if date_from:
            ts_from = self._parse_date(date_from)
        elif not date_to:
            ts_from = datetime.now(tz=self.tz)
        else:
            ts_from = None
        ts_to = self._parse_date(date_to, end_of_day=True) if date_to else None

        rows = await self.pool.fetch(
            """
            SELECT summary, dtstart, dtend, all_day, description, location
            FROM events
            WHERE ($1 = '' OR summary ILIKE '%' || $1 || '%'
                   OR description ILIKE '%' || $1 || '%'
                   OR location ILIKE '%' || $1 || '%')
              AND ($2::timestamptz IS NULL OR dtstart >= $2)
              AND ($3::timestamptz IS NULL OR dtstart <= $3)
            ORDER BY dtstart ASC
            LIMIT 10
            """,
            query,
            ts_from,
            ts_to,
        )

        return [self._row_to_dict(row) for row in rows]

    def _parse_date(self, value: str, end_of_day: bool = False) -> datetime | None:
        """Parse an ISO date string to a timezone-aware datetime."""
        try:
            dt = datetime.fromisoformat(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=self.tz)
            if end_of_day and dt.hour == 0 and dt.minute == 0 and dt.second == 0:
                dt = dt.replace(hour=23, minute=59, second=59)
            return dt
        except ValueError:
            logger.warning("Failed to parse date: %s", value)
            return None

    def _row_to_dict(self, row: asyncpg.Record) -> dict:
        """Convert a database row to a formatted dict."""
        dtstart = row["dtstart"]
        dtend = row["dtend"]

        result = {
            "summary": row["summary"],
            "start": dtstart.astimezone(self.tz).isoformat() if dtstart else None,
            "all_day": row["all_day"],
        }

        if dtend:
            result["end"] = dtend.astimezone(self.tz).isoformat()
        if row["description"]:
            result["description"] = row["description"]
        if row["location"]:
            result["location"] = row["location"]

        return result
