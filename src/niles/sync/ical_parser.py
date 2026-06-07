"""Shared iCalendar parsing utilities (RFC 5545).

Used by both CalDAV sync and ICS subscription sync.
"""

import logging
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# Regex to parse DTSTART/DTEND lines with optional parameters
_DT_LINE_REGEX = re.compile(r"(DTSTART|DTEND)([^:]*):(.+)")

# Safety cap: max expanded occurrences per recurring event
_MAX_OCCURRENCES = 500

# Windows → IANA timezone mapping (common Exchange/Outlook ICS exports)
_WINDOWS_TZ_MAP: dict[str, str] = {
    "W. Europe Standard Time": "Europe/Berlin",
    "Central European Standard Time": "Europe/Budapest",
    "Central Europe Standard Time": "Europe/Budapest",
    "Romance Standard Time": "Europe/Paris",
    "GMT Standard Time": "Europe/London",
    "Greenwich Standard Time": "Atlantic/Reykjavik",
    "Eastern Standard Time": "America/New_York",
    "Central Standard Time": "America/Chicago",
    "Mountain Standard Time": "America/Denver",
    "Pacific Standard Time": "America/Los_Angeles",
    "AUS Eastern Standard Time": "Australia/Sydney",
    "Tokyo Standard Time": "Asia/Tokyo",
    "China Standard Time": "Asia/Shanghai",
    "India Standard Time": "Asia/Kolkata",
    "FLE Standard Time": "Europe/Helsinki",
    "GTB Standard Time": "Europe/Bucharest",
    "E. Europe Standard Time": "Europe/Chisinau",
    "Russian Standard Time": "Europe/Moscow",
    "Turkey Standard Time": "Europe/Istanbul",
    "Israel Standard Time": "Asia/Jerusalem",
    "Arabic Standard Time": "Asia/Baghdad",
    "Singapore Standard Time": "Asia/Singapore",
    "Korea Standard Time": "Asia/Seoul",
    "New Zealand Standard Time": "Pacific/Auckland",
    "UTC": "UTC",
}


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
        tz_name = tzid_match.group(1).strip().strip('"')  # Strip quotes
        # Try Windows timezone name mapping first
        iana_name = _WINDOWS_TZ_MAP.get(tz_name, tz_name)
        try:
            tz = ZoneInfo(iana_name)
            dt = datetime.strptime(value, "%Y%m%dT%H%M%S").replace(tzinfo=tz)
            return dt, False
        except ValueError, KeyError:
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


def _parse_exdate_line(line: str) -> list[datetime]:
    """Parse an EXDATE line into datetime values.

    Handles formats: VALUE=DATE, UTC (Z suffix), TZID=..., and comma-separated values.
    """
    colon_idx = line.index(":")
    params = line[:colon_idx]
    values_str = line[colon_idx + 1 :].strip()

    is_date = "VALUE=DATE" in params.upper()

    tzid = None
    tzid_match = re.search(r"TZID=([^;:]+)", params)
    if tzid_match:
        tz_name = tzid_match.group(1).strip().strip('"')
        iana_name = _WINDOWS_TZ_MAP.get(tz_name, tz_name)
        try:
            tzid = ZoneInfo(iana_name)
        except KeyError, ValueError:
            pass

    results: list[datetime] = []
    for val in values_str.split(","):
        val = val.strip()
        if not val:
            continue
        try:
            if is_date:
                dt = datetime.strptime(val, "%Y%m%d").replace(tzinfo=timezone.utc)
            elif val.endswith("Z"):
                dt = datetime.strptime(val, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
            elif tzid:
                dt = datetime.strptime(val, "%Y%m%dT%H%M%S").replace(tzinfo=tzid)
            else:
                dt = datetime.strptime(val, "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
            results.append(dt)
        except ValueError:
            logger.warning("Failed to parse EXDATE value: %s", val)
    return results


def _extract_value(line: str) -> str:
    """Extract the value from a property line, skipping parameters.

    Handles both ``SUMMARY:text`` and ``SUMMARY;LANGUAGE=de:text``.
    """
    colon_idx = line.find(":")
    if colon_idx < 0:
        return ""
    return line[colon_idx + 1 :].strip()


def parse_icalendar(ics_text: str, url: str) -> dict | None:
    """Parse iCalendar text into an event dict. Returns None if invalid.

    Extracts the first VEVENT from the given iCalendar text.
    Also extracts RRULE and EXDATE for recurring event expansion.
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
        "transp": "OPAQUE",
        "caldav_uid": "",
        "caldav_url": url,
        "rrule": "",
        "exdates": [],
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

        if line.startswith("SUMMARY"):
            event["summary"] = _extract_value(line)
        elif line.startswith("DESCRIPTION"):
            event["description"] = _extract_value(line)
        elif line.startswith("LOCATION"):
            event["location"] = _extract_value(line)
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
        elif line.startswith("TRANSP"):
            event["transp"] = _extract_value(line)
        elif line.startswith("RRULE:"):
            event["rrule"] = line
        elif line.startswith("EXDATE"):
            try:
                event["exdates"].extend(_parse_exdate_line(line))
            except ValueError, IndexError:
                logger.warning("Failed to parse EXDATE line: %s", line)

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


def expand_recurring_event(
    event: dict,
    window_start: datetime,
    window_end: datetime,
) -> list[dict]:
    """Expand a recurring event into individual occurrences within the window.

    If the event has no RRULE, returns [event] unchanged (without rrule/exdates keys).
    Otherwise returns a list of expanded occurrence dicts with unique caldav_uids.
    Each occurrence uid is formatted as "{original_uid}@{date_or_datetime}".
    """
    rrule_str = event.get("rrule", "")

    # Non-recurring: strip internal fields and return as-is
    if not rrule_str:
        clean = {k: v for k, v in event.items() if k not in ("rrule", "exdates")}
        return [clean]

    try:
        from dateutil.rrule import rrulestr
    except ImportError:
        logger.warning("python-dateutil not installed, skipping RRULE expansion")
        clean = {k: v for k, v in event.items() if k not in ("rrule", "exdates")}
        return [clean]

    dtstart = event["dtstart"]
    dtend = event.get("dtend")
    if dtend:
        duration = dtend - dtstart
    elif event["all_day"]:
        duration = timedelta(days=1)
    else:
        duration = timedelta(hours=1)

    # Parse RRULE (strip "RRULE:" prefix)
    rule_value = rrule_str
    if rule_value.upper().startswith("RRULE:"):
        rule_value = rule_value[6:]

    try:
        rule = rrulestr(rule_value, dtstart=dtstart)
    except ValueError, TypeError:
        logger.warning(
            "Failed to parse RRULE for '%s': %s",
            event.get("summary", ""),
            rrule_str,
        )
        clean = {k: v for k, v in event.items() if k not in ("rrule", "exdates")}
        return [clean]

    # Build EXDATE set — compare by date for all-day, by UTC datetime otherwise
    exdates = event.get("exdates", [])
    if event["all_day"]:
        exdate_dates = {d.date() for d in exdates}
    else:
        exdate_dates = {d.astimezone(timezone.utc).replace(microsecond=0) for d in exdates}

    # Generate occurrences within window
    occurrences = rule.between(window_start, window_end, inc=True)

    original_uid = event["caldav_uid"]
    results: list[dict] = []

    for occ_start in occurrences:
        if len(results) >= _MAX_OCCURRENCES:
            logger.warning(
                "Capped RRULE expansion at %d for '%s'",
                _MAX_OCCURRENCES,
                event.get("summary", ""),
            )
            break

        # Check EXDATE exclusion
        if event["all_day"]:
            if occ_start.date() in exdate_dates:
                continue
        else:
            occ_utc = occ_start.astimezone(timezone.utc).replace(microsecond=0)
            if occ_utc in exdate_dates:
                continue

        occ_end = occ_start + duration

        if event["all_day"]:
            uid_suffix = occ_start.strftime("%Y%m%d")
        else:
            uid_suffix = occ_start.strftime("%Y%m%dT%H%M%S")

        results.append(
            {
                "summary": event["summary"],
                "dtstart": occ_start,
                "dtend": occ_end,
                "all_day": event["all_day"],
                "description": event["description"],
                "location": event["location"],
                "transp": event.get("transp", "OPAQUE"),
                "caldav_uid": f"{original_uid}@{uid_suffix}",
                "caldav_url": event["caldav_url"],
            }
        )

    if not results:
        logger.debug(
            "No occurrences in window for recurring event '%s'",
            event.get("summary", ""),
        )

    return results
