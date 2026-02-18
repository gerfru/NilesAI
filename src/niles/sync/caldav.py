"""CalDAV calendar sync from mailbox.org to PostgreSQL."""

import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import asyncpg
import httpx

from ..config import Settings

logger = logging.getLogger(__name__)

_TZ_VIENNA = ZoneInfo("Europe/Vienna")

# PROPFIND body to list iCalendar resources
_PROPFIND_BODY = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<D:propfind xmlns:D="DAV:">'
    "<D:prop><D:displayname/></D:prop>"
    "</D:propfind>"
)

# Namespace-agnostic regex for href elements containing .ics paths
_HREF_REGEX = re.compile(
    r"<(?:[dD]:)?href[^>]*>\s*([^<]*\.ics)\s*</(?:[dD]:)?href>", re.IGNORECASE
)

# Regex to parse DTSTART/DTEND lines with optional parameters
_DT_LINE_REGEX = re.compile(r"(DTSTART|DTEND)([^:]*):(.+)")


def _unfold_ics(text: str) -> str:
    """Unfold iCalendar line continuations (RFC 5545 section 3.1)."""
    return re.sub(r"\r?\n[ \t]", "", text)


def _parse_dt(line: str) -> tuple[datetime | None, bool]:
    """Parse a DTSTART or DTEND line. Returns (datetime_utc, is_all_day)."""
    match = _DT_LINE_REGEX.match(line)
    if not match:
        return None, False

    params = match.group(2)
    value = match.group(3).strip()

    # All-day event: VALUE=DATE
    if "VALUE=DATE" in params.upper():
        try:
            dt = datetime.strptime(value, "%Y%m%d").replace(tzinfo=timezone.utc)
            return dt, True
        except ValueError:
            return None, False

    # With timezone: TZID=...
    tzid_match = re.search(r"TZID=([^;:]+)", params)
    if tzid_match:
        tz_name = tzid_match.group(1).strip()
        try:
            tz = ZoneInfo(tz_name)
            dt = datetime.strptime(value, "%Y%m%dT%H%M%S").replace(tzinfo=tz)
            return dt, False
        except (ValueError, KeyError):
            logger.warning("Failed to parse datetime with TZID=%s: %s", tz_name, value)
            return None, False

    # UTC (trailing Z)
    if value.endswith("Z"):
        try:
            dt = datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
            return dt, False
        except ValueError:
            return None, False

    # Naive datetime (assume UTC)
    try:
        dt = datetime.strptime(value, "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
        return dt, False
    except ValueError:
        return None, False


class CalDAVSync:
    """Syncs calendar events from a CalDAV server to PostgreSQL."""

    def __init__(self, pool: asyncpg.Pool, config: Settings):
        self.pool = pool
        self.caldav_url = config.caldav_url
        self.auth = (config.caldav_user, config.caldav_password)
        # Base URL for fetching individual .ics files (scheme + host)
        self._base_url = re.match(r"https?://[^/]+", config.caldav_url)
        self._base_url = self._base_url.group(0) if self._base_url else ""

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
        """Run a full CalDAV sync. Returns number of synced events."""
        logger.info("Starting CalDAV event sync...")

        try:
            ics_urls = await self._propfind()
        except Exception:
            logger.exception("PROPFIND failed")
            return 0

        if not ics_urls:
            logger.warning("No iCalendar URLs found")
            return 0

        logger.info("Found %d iCalendar URLs", len(ics_urls))

        count = 0
        for url in ics_urls:
            try:
                ics_text = await self._fetch_ics(url)
                if not ics_text:
                    continue

                event = self._parse_icalendar(ics_text, url)
                if not event:
                    continue

                await self._upsert_event(event)
                count += 1
            except Exception:
                logger.exception("Failed to sync event: %s", url)

        logger.info("Synced %d events", count)
        return count

    async def _propfind(self) -> list[str]:
        """Send PROPFIND request and extract .ics URLs from response."""
        async with httpx.AsyncClient() as client:
            response = await client.request(
                "PROPFIND",
                self.caldav_url,
                content=_PROPFIND_BODY,
                headers={
                    "Depth": "1",
                    "Content-Type": "application/xml; charset=utf-8",
                },
                auth=self.auth,
                timeout=30,
            )
            response.raise_for_status()

        xml = response.text
        if not xml or len(xml) < 100:
            logger.warning("Empty or too short PROPFIND response")
            return []

        urls = _HREF_REGEX.findall(xml)
        return [u.strip() for u in urls if u.strip()]

    async def _fetch_ics(self, url: str) -> str | None:
        """Fetch a single iCalendar resource by URL."""
        full_url = self._base_url + url if not url.startswith("http") else url

        async with httpx.AsyncClient() as client:
            response = await client.get(
                full_url,
                auth=self.auth,
                timeout=30,
            )
            response.raise_for_status()

        text = response.text
        if "BEGIN:VCALENDAR" not in text:
            return None
        return text

    def _parse_icalendar(self, ics_text: str, url: str) -> dict | None:
        """Parse iCalendar text into an event dict. Returns None if invalid."""
        unfolded = _unfold_ics(ics_text)
        lines = unfolded.split("\n")

        event = {
            "summary": "",
            "dtstart": None,
            "dtend": None,
            "all_day": False,
            "description": "",
            "location": "",
            "caldav_uid": "",
            "caldav_url": url,
        }

        in_vevent = False
        for raw_line in lines:
            line = raw_line.strip()

            if line == "BEGIN:VEVENT":
                in_vevent = True
                continue
            if line == "END:VEVENT":
                break
            if not in_vevent:
                continue

            if line.startswith("SUMMARY:"):
                event["summary"] = line[8:].strip()
            elif line.startswith("DESCRIPTION:"):
                event["description"] = line[12:].strip()
            elif line.startswith("LOCATION:"):
                event["location"] = line[9:].strip()
            elif line.startswith("UID:"):
                event["caldav_uid"] = line[4:].strip()
            elif line.startswith("DTSTART"):
                dt, all_day = _parse_dt(line)
                if dt:
                    event["dtstart"] = dt
                    event["all_day"] = all_day
            elif line.startswith("DTEND"):
                dt, _ = _parse_dt(line)
                if dt:
                    event["dtend"] = dt

        # Skip events without summary
        if not event["summary"]:
            return None

        # Skip events without start time
        if not event["dtstart"]:
            return None

        # Fallback UID from URL
        if not event["caldav_uid"]:
            event["caldav_uid"] = url.rsplit("/", 1)[-1].replace(".ics", "")

        return event

    async def _upsert_event(self, event: dict) -> None:
        """Insert or update an event by caldav_uid."""
        await self.pool.execute(
            """
            INSERT INTO events (
                summary, dtstart, dtend, all_day,
                description, location, caldav_uid, caldav_url, updated_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
            ON CONFLICT (caldav_uid) DO UPDATE SET
                summary = EXCLUDED.summary,
                dtstart = EXCLUDED.dtstart,
                dtend = EXCLUDED.dtend,
                all_day = EXCLUDED.all_day,
                description = EXCLUDED.description,
                location = EXCLUDED.location,
                caldav_url = EXCLUDED.caldav_url,
                updated_at = NOW()
            """,
            event["summary"],
            event["dtstart"],
            event["dtend"],
            event["all_day"],
            event["description"],
            event["location"],
            event["caldav_uid"],
            event["caldav_url"],
        )

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
            dtstart = dtstart.replace(tzinfo=_TZ_VIENNA)

        # Parse or default end time
        if dtend_str:
            dtend = datetime.fromisoformat(dtend_str)
            if dtend.tzinfo is None:
                dtend = dtend.replace(tzinfo=_TZ_VIENNA)
        else:
            dtend = dtstart + timedelta(hours=1)

        # Format for iCalendar (local time with TZID)
        dt_fmt = "%Y%m%dT%H%M%S"
        start_local = dtstart.astimezone(_TZ_VIENNA).strftime(dt_fmt)
        end_local = dtend.astimezone(_TZ_VIENNA).strftime(dt_fmt)

        # Build iCalendar body
        ics_body = (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//Niles AI//CalDAV//EN\r\n"
            "BEGIN:VEVENT\r\n"
            f"UID:{uid}\r\n"
            f"DTSTAMP:{now_utc}\r\n"
            f"DTSTART;TZID=Europe/Vienna:{start_local}\r\n"
            f"DTEND;TZID=Europe/Vienna:{end_local}\r\n"
            f"SUMMARY:{summary}\r\n"
        )
        if description:
            ics_body += f"DESCRIPTION:{description}\r\n"
        if location:
            ics_body += f"LOCATION:{location}\r\n"
        ics_body += "END:VEVENT\r\n" "END:VCALENDAR\r\n"

        # PUT to CalDAV server
        put_url = f"{self.caldav_url.rstrip('/')}/{uid}.ics"

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
            "start": dtstart.astimezone(_TZ_VIENNA).isoformat(),
            "end": dtend.astimezone(_TZ_VIENNA).isoformat(),
            "uid": uid,
        }
