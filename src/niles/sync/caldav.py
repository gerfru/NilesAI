"""CalDAV calendar sync from mailbox.org to PostgreSQL."""

import logging
import re
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import asyncpg
import httpx

from .ical_parser import expand_recurring_event, parse_icalendar

logger = logging.getLogger(__name__)

# PROPFIND body to list iCalendar resources
_PROPFIND_BODY = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<D:propfind xmlns:D="DAV:">'
    "<D:prop><D:displayname/></D:prop>"
    "</D:propfind>"
)

# XML namespaces used in CalDAV responses
_NS = {
    "D": "DAV:",
    "C": "urn:ietf:params:xml:ns:caldav",
}

# Sync window: 30 days past, 365 days future
_SYNC_DAYS_PAST = 30
_SYNC_DAYS_FUTURE = 365

# Maximum response size from CalDAV server (10 MB)
_MAX_RESPONSE_BYTES = 10 * 1024 * 1024

# Cache TTL for discover_collections (seconds)
_DISCOVERY_CACHE_TTL = 60


def _escape_ical_text(text: str) -> str:
    """Escape special characters for iCalendar TEXT values (RFC 5545 section 3.3.11)."""
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "")
    )


_UPSERT_EVENT_SQL = """
    INSERT INTO events (
        summary, dtstart, dtend, all_day,
        description, location, caldav_uid, caldav_url,
        source_id, updated_at
    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW())
    ON CONFLICT (caldav_uid) DO UPDATE SET
        summary = EXCLUDED.summary,
        dtstart = EXCLUDED.dtstart,
        dtend = EXCLUDED.dtend,
        all_day = EXCLUDED.all_day,
        description = EXCLUDED.description,
        location = EXCLUDED.location,
        caldav_url = EXCLUDED.caldav_url,
        source_id = EXCLUDED.source_id,
        updated_at = NOW()
"""


async def upsert_event(pool: asyncpg.Pool, event: dict, source_id: int | None) -> None:
    """Insert or update an event by caldav_uid (shared by CalDAVSync + CalendarSourceManager)."""
    await pool.execute(
        _UPSERT_EVENT_SQL,
        event["summary"],
        event["dtstart"],
        event["dtend"],
        event["all_day"],
        event["description"],
        event["location"],
        event["caldav_uid"],
        event["caldav_url"],
        source_id,
    )


async def cleanup_recurring_occurrences(
    pool: asyncpg.Pool, master_uid: str, source_id: int | None = None,
) -> int:
    """Delete old expanded occurrences and the master row for a recurring event.

    Returns number of rows deleted. Uses master_uid to match:
    - The master event row (caldav_uid = master_uid)
    - All expanded occurrence rows (caldav_uid LIKE 'master_uid@%')
    """
    if source_id is not None:
        result = await pool.execute(
            "DELETE FROM events WHERE source_id = $1 AND "
            "(caldav_uid = $2 OR caldav_uid LIKE $3)",
            source_id, master_uid, f"{master_uid}@%",
        )
    else:
        result = await pool.execute(
            "DELETE FROM events WHERE caldav_uid = $1 OR caldav_uid LIKE $2",
            master_uid, f"{master_uid}@%",
        )
    # asyncpg returns "DELETE N"
    deleted = int(result.split()[-1]) if result else 0
    if deleted:
        logger.debug("Cleaned up %d old occurrences for %s", deleted, master_uid)
    return deleted


class CalDAVSync:
    """Syncs calendar events from a CalDAV server to PostgreSQL.

    Recurring events (RRULE) are expanded into individual occurrences within
    the sync window (30 days past to 365 days future).

    Known limitations:
    - Only first VEVENT per .ics file is parsed
    - RECURRENCE-ID overrides are not supported (modified occurrences ignored)
    - VTIMEZONE blocks are ignored (uses ZoneInfo from TZID parameter)
    - No VALARM (reminder) support
    - No ATTENDEE support
    """

    def __init__(
        self,
        pool: asyncpg.Pool,
        caldav_url: str,
        auth: httpx.Auth,
        timezone: str,
        caldav_calendars: str = "",
        source_id: int | None = None,
    ):
        self.pool = pool
        self.caldav_url = caldav_url
        self.auth = auth
        self.tz = ZoneInfo(timezone)
        self.source_id = source_id
        self._caldav_calendars = caldav_calendars
        # Base URL for fetching individual .ics files (scheme + host)
        self._base_url = re.match(r"https?://[^/]+", caldav_url)
        self._base_url = self._base_url.group(0) if self._base_url else ""
        # Cache for discover_collections (avoids PROPFIND on every settings page load)
        self._collections_cache: list[dict] | None = None
        self._collections_cache_time: float = 0

    async def initialize(self) -> None:
        """Create events table and indexes if they don't exist."""
        await self.pool.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id SERIAL PRIMARY KEY,
                summary TEXT NOT NULL,
                dtstart TIMESTAMP WITH TIME ZONE NOT NULL,
                dtend TIMESTAMP WITH TIME ZONE,
                all_day BOOLEAN DEFAULT FALSE,
                description TEXT,
                location TEXT,
                caldav_uid TEXT UNIQUE,
                caldav_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await self.pool.execute("""
            CREATE INDEX IF NOT EXISTS idx_events_dtstart ON events (dtstart)
        """)
        await self.pool.execute("""
            CREATE INDEX IF NOT EXISTS idx_events_summary ON events (summary)
        """)
        logger.info("Events table initialized")

    async def sync_events(self) -> int:
        """Run a CalDAV sync using REPORT with time-range filter.

        Only syncs events from 30 days ago to 365 days in the future.
        Recurring events (RRULE) are expanded into individual occurrences.
        Uses CalDAV REPORT (RFC 4791) to fetch matching events inline,
        avoiding thousands of individual GET requests.
        """
        logger.info("Starting CalDAV event sync...")

        now = datetime.now(timezone.utc)
        window_start = now - timedelta(days=_SYNC_DAYS_PAST)
        window_end = now + timedelta(days=_SYNC_DAYS_FUTURE)
        start_str = window_start.strftime("%Y%m%dT%H%M%SZ")
        end_str = window_end.strftime("%Y%m%dT%H%M%SZ")

        # Discover collections
        try:
            collections = await self._get_sync_collections()
        except Exception:
            logger.exception("Collection discovery failed")
            return 0

        if not collections:
            logger.warning("No calendar collections found")
            return 0

        count = 0
        for col_url in collections:
            try:
                events = await self._report_time_range(col_url, start_str, end_str)
                for ics_text, href in events:
                    event = parse_icalendar(ics_text, href)
                    if event:
                        expanded = expand_recurring_event(
                            event, window_start, window_end,
                        )
                        if event.get("rrule"):
                            await cleanup_recurring_occurrences(
                                self.pool, event["caldav_uid"], self.source_id,
                            )
                        for occ in expanded:
                            await self._upsert_event(occ)
                            count += 1
            except Exception:
                logger.exception("REPORT failed for %s", col_url)

        logger.info("Synced %d events (range: %s to %s)", count, start_str, end_str)
        return count

    async def _report_time_range(
        self, collection_url: str, start: str, end: str,
    ) -> list[tuple[str, str]]:
        """Send CalDAV REPORT with time-range filter. Returns [(ics_text, href), ...]."""
        body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<C:calendar-query xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">'
            "<D:prop><D:getetag/><C:calendar-data/></D:prop>"
            "<C:filter><C:comp-filter name=\"VCALENDAR\">"
            "<C:comp-filter name=\"VEVENT\">"
            f'<C:time-range start="{start}" end="{end}"/>'
            "</C:comp-filter></C:comp-filter></C:filter>"
            "</C:calendar-query>"
        )

        async with httpx.AsyncClient() as client:
            response = await client.request(
                "REPORT",
                collection_url,
                content=body,
                headers={
                    "Depth": "1",
                    "Content-Type": "application/xml; charset=utf-8",
                },
                auth=self.auth,
                timeout=60,
            )
            response.raise_for_status()
            if len(response.content) > _MAX_RESPONSE_BYTES:
                raise ValueError(
                    f"CalDAV REPORT response too large: {len(response.content)} bytes"
                )

        xml_text = response.text
        results: list[tuple[str, str]] = []

        root = ET.fromstring(xml_text)
        for resp_el in root.findall("D:response", _NS):
            href_el = resp_el.find("D:href", _NS)
            href = (href_el.text or "").strip() if href_el is not None else ""
            cal_el = resp_el.find(".//C:calendar-data", _NS)
            if cal_el is not None and cal_el.text:
                ics_text = cal_el.text.strip()
                if "BEGIN:VCALENDAR" in ics_text:
                    results.append((ics_text, href))

        logger.info("  %s: %d events in time range", collection_url, len(results))
        return results

    async def _get_sync_collections(self) -> list[str]:
        """Get collection URLs to sync, respecting caldav_calendars filter."""
        xml_text = await self._propfind_request(self.caldav_url)
        if not xml_text:
            return []

        root = ET.fromstring(xml_text)
        hrefs = [
            (el.text or "").strip()
            for el in root.findall(".//D:response/D:href", _NS)
            if el.text
        ]

        # Direct calendar URL? (has .ics files directly)
        if any(h.endswith(".ics") for h in hrefs):
            return [self.caldav_url]

        # Discover sub-collections (hrefs ending with /)
        root_path = self.caldav_url.replace(self._base_url, "").rstrip("/") + "/"
        collections = [
            h for h in hrefs
            if h.endswith("/") and h != root_path and "schedule-" not in h
        ]

        allowed = self.allowed_collections()
        if allowed:
            collections = [h for h in collections if h in allowed]

        logger.info("Syncing %d calendar collections", len(collections))

        # Build full URLs; reject absolute hrefs that don't match our origin (SSRF protection)
        urls: list[str] = []
        for h in collections:
            if h.startswith("http"):
                if not h.startswith(self._base_url):
                    logger.warning("Ignoring href with foreign origin: %s", h)
                    continue
                urls.append(h)
            else:
                urls.append(self._base_url + h)
        return urls

    async def discover_collections(self) -> list[dict]:
        """Discover available calendar collections from the CalDAV root.

        Returns list of {"href": "/caldav/abc/", "name": "Kalender"} dicts.
        Results are cached for 60 seconds to avoid repeated PROPFIND requests.
        """
        now = time.monotonic()
        if self._collections_cache is not None and (now - self._collections_cache_time) < _DISCOVERY_CACHE_TTL:
            return self._collections_cache

        xml_text = await self._propfind_request(self.caldav_url)
        if not xml_text:
            return []

        root_path = self.caldav_url.replace(self._base_url, "").rstrip("/") + "/"
        collections: list[dict] = []

        root = ET.fromstring(xml_text)
        for resp_el in root.findall("D:response", _NS):
            href_el = resp_el.find("D:href", _NS)
            if href_el is None or not href_el.text:
                continue
            href = href_el.text.strip()
            if not href.endswith("/") or href == root_path or "schedule-" in href:
                continue

            name_el = resp_el.find(".//D:displayname", _NS)
            name = (name_el.text or "").strip() if name_el is not None else ""
            collections.append({"href": href, "name": name or href})

        self._collections_cache = collections
        self._collections_cache_time = time.monotonic()
        return collections

    def allowed_collections(self) -> set[str] | None:
        """Parse caldav_calendars setting into a set of allowed hrefs, or None for all."""
        raw = self._caldav_calendars
        if not raw or not raw.strip():
            return None
        return {h.strip() for h in raw.split(",") if h.strip()}

    async def _propfind_request(self, url: str) -> str | None:
        """Send a single PROPFIND Depth:1 request, return XML or None."""
        async with httpx.AsyncClient() as client:
            response = await client.request(
                "PROPFIND",
                url,
                content=_PROPFIND_BODY,
                headers={
                    "Depth": "1",
                    "Content-Type": "application/xml; charset=utf-8",
                },
                auth=self.auth,
                timeout=30,
            )
            response.raise_for_status()
            if len(response.content) > _MAX_RESPONSE_BYTES:
                raise ValueError(
                    f"CalDAV PROPFIND response too large: {len(response.content)} bytes"
                )

        xml = response.text
        if not xml or len(xml) < 100:
            logger.warning("Empty or too short PROPFIND response for %s", url)
            return None
        return xml

    async def _upsert_event(self, event: dict) -> None:
        """Insert or update an event by caldav_uid."""
        await upsert_event(self.pool, event, self.source_id)

    async def _resolve_write_collection(self) -> str:
        """Return a collection URL suitable for creating events.

        Delegates to _get_sync_collections() which handles both direct
        collection URLs and root-level discovery. Returns the first
        discovered collection.
        """
        collections = await self._get_sync_collections()
        if not collections:
            raise RuntimeError("No writable calendar collection found")
        return collections[0]

    async def create_event(
        self,
        summary: str,
        dtstart_str: str,
        dtend_str: str | None = None,
        description: str = "",
        location: str = "",
    ) -> dict:
        """Create a new calendar event via CalDAV PUT and store locally."""
        uid = str(uuid.uuid4())
        now_utc = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

        # Parse start time
        dtstart = datetime.fromisoformat(dtstart_str)
        if dtstart.tzinfo is None:
            dtstart = dtstart.replace(tzinfo=self.tz)

        # Parse or default end time
        if dtend_str:
            dtend = datetime.fromisoformat(dtend_str)
            if dtend.tzinfo is None:
                dtend = dtend.replace(tzinfo=self.tz)
        else:
            dtend = dtstart + timedelta(hours=1)

        # Format for iCalendar (local time with TZID)
        dt_fmt = "%Y%m%dT%H%M%S"
        start_local = dtstart.astimezone(self.tz).strftime(dt_fmt)
        end_local = dtend.astimezone(self.tz).strftime(dt_fmt)

        # Build iCalendar body
        ics_body = (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//Niles AI//CalDAV//EN\r\n"
            "BEGIN:VEVENT\r\n"
            f"UID:{uid}\r\n"
            f"DTSTAMP:{now_utc}\r\n"
            f"DTSTART;TZID={self.tz.key}:{start_local}\r\n"
            f"DTEND;TZID={self.tz.key}:{end_local}\r\n"
            f"SUMMARY:{_escape_ical_text(summary)}\r\n"
        )
        if description:
            ics_body += f"DESCRIPTION:{_escape_ical_text(description)}\r\n"
        if location:
            ics_body += f"LOCATION:{_escape_ical_text(location)}\r\n"
        ics_body += "END:VEVENT\r\n" "END:VCALENDAR\r\n"

        # Resolve target collection (root URL requires discovery)
        target_url = await self._resolve_write_collection()
        put_url = f"{target_url.rstrip('/')}/{uid}.ics"

        async with httpx.AsyncClient() as client:
            response = await client.put(
                put_url,
                content=ics_body,
                headers={
                    "Content-Type": "text/calendar; charset=utf-8",
                    "If-None-Match": "*",
                },
                auth=self.auth,
                timeout=30,
            )
            response.raise_for_status()

        # Store locally
        event_data = {
            "summary": summary,
            "dtstart": dtstart,
            "dtend": dtend,
            "all_day": False,
            "description": description,
            "location": location,
            "caldav_uid": uid,
            "caldav_url": put_url,
        }
        await self._upsert_event(event_data)

        logger.info("Created event '%s' at %s", summary, dtstart_str)
        return {
            "status": "created",
            "summary": summary,
            "start": dtstart.astimezone(self.tz).isoformat(),
            "end": dtend.astimezone(self.tz).isoformat(),
            "uid": uid,
        }
