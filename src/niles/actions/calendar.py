"""Calendar event lookup in PostgreSQL."""

import logging
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import asyncpg

logger = logging.getLogger(__name__)

# Strip control characters except common whitespace (space, tab)
_CONTROL_CHAR_REGEX = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MAX_FIELD_LENGTH = 500


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
        explicit_from = bool(date_from)
        if date_from:
            ts_from = self._parse_date(date_from)
        elif not date_to:
            ts_from = datetime.now(tz=self.tz)
        else:
            ts_from = None

        if date_to:
            ts_to = self._parse_date(date_to, end_of_day=True)
        elif explicit_from and ts_from:
            # LLM asked for a specific date without date_to: cap at end of
            # that day so only relevant events are returned.  Without this,
            # LIMIT 10 pulls events weeks ahead and small models hallucinate.
            ts_to = ts_from.replace(hour=23, minute=59, second=59)
        else:
            ts_to = None

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
        """Parse an ISO date string or relative term to a timezone-aware datetime."""
        # Handle relative date terms (small LLMs sometimes send these)
        now = datetime.now(tz=self.tz)
        relative = value.strip().lower()
        if relative in ("heute", "today"):
            dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
            if end_of_day:
                dt = dt.replace(hour=23, minute=59, second=59)
            return dt
        if relative in ("morgen", "tomorrow"):
            dt = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            if end_of_day:
                dt = dt.replace(hour=23, minute=59, second=59)
            return dt
        if relative in ("übermorgen", "uebermorgen"):
            dt = (now + timedelta(days=2)).replace(hour=0, minute=0, second=0, microsecond=0)
            if end_of_day:
                dt = dt.replace(hour=23, minute=59, second=59)
            return dt

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

    @staticmethod
    def _sanitize_field(value: str) -> str:
        """Sanitize a text field from external calendar data.

        Strips control characters and truncates to prevent prompt injection
        when event data is passed to the LLM context.
        """
        clean = _CONTROL_CHAR_REGEX.sub("", value)
        if len(clean) > _MAX_FIELD_LENGTH:
            clean = clean[:_MAX_FIELD_LENGTH] + "..."
        return clean

    def _row_to_dict(self, row: asyncpg.Record) -> dict:
        """Convert a database row to a formatted dict."""
        dtstart = row["dtstart"]
        dtend = row["dtend"]

        result = {
            "summary": self._sanitize_field(row["summary"]),
            "start": dtstart.astimezone(self.tz).isoformat() if dtstart else None,
            "all_day": row["all_day"],
        }

        if dtend:
            result["end"] = dtend.astimezone(self.tz).isoformat()
        if row["description"]:
            result["description"] = self._sanitize_field(row["description"])
        if row["location"]:
            result["location"] = self._sanitize_field(row["location"])

        return result
