"""Shared iCalendar parsing utilities (RFC 5545).

Used by both CalDAV sync and ICS subscription sync.
"""

import logging
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# Regex to parse DTSTART/DTEND lines with optional parameters
_DT_LINE_REGEX = re.compile(r"(DTSTART|DTEND)([^:]*):(.+)")


def unfold_ics(text: str) -> str:
    """Unfold iCalendar line continuations (RFC 5545 section 3.1)."""
    return re.sub(r"\r?\n[ \t]", "", text)


def parse_dt(line: str) -> tuple[datetime | None, bool]:
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


def parse_icalendar(ics_text: str, url: str) -> dict | None:
    """Parse iCalendar text into an event dict. Returns None if invalid.

    Extracts the first VEVENT from the given iCalendar text.
    """
    unfolded = unfold_ics(ics_text)
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
            dt, all_day = parse_dt(line)
            if dt:
                event["dtstart"] = dt
                event["all_day"] = all_day
        elif line.startswith("DTEND"):
            dt, _ = parse_dt(line)
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
