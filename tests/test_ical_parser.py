"""Tests for shared iCalendar parser (ical_parser.py).

Migrated from test_caldav.py — these are the parser-level tests
that don't depend on CalDAVSync.
"""

from datetime import timezone
from zoneinfo import ZoneInfo

from niles.sync.ical_parser import _extract_value, parse_dt, parse_icalendar, unfold_ics

_TZ_VIENNA = ZoneInfo("Europe/Vienna")

SAMPLE_ICS_FULL = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:abc-123-event
DTSTART;TZID=Europe/Vienna:20260220T140000
DTEND;TZID=Europe/Vienna:20260220T153000
SUMMARY:Zahnarzt Dr. Mueller
DESCRIPTION:Kontrolle und Reinigung
LOCATION:Wiedner Hauptstrasse 10, Wien
END:VEVENT
END:VCALENDAR"""

SAMPLE_ICS_UTC = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:def-456-event
DTSTART:20260301T100000Z
DTEND:20260301T110000Z
SUMMARY:Team Meeting
END:VEVENT
END:VCALENDAR"""

SAMPLE_ICS_ALL_DAY = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:ghi-789-event
DTSTART;VALUE=DATE:20260401
DTEND;VALUE=DATE:20260402
SUMMARY:Urlaub
END:VEVENT
END:VCALENDAR"""

SAMPLE_ICS_MINIMAL = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
DTSTART:20260515T090000Z
SUMMARY:Quick Note
END:VEVENT
END:VCALENDAR"""

SAMPLE_ICS_NO_SUMMARY = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:bad-event
DTSTART:20260515T090000Z
END:VEVENT
END:VCALENDAR"""

SAMPLE_ICS_FOLDED = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:folded-event
DTSTART:20260601T100000Z
SUMMARY:Long event with a very
 long summary that is folded
DESCRIPTION:Also a
 folded description
END:VEVENT
END:VCALENDAR"""


class TestUnfoldIcs:
    def test_unfolds_space_continuation(self):
        text = "SUMMARY:Long\n summary here"
        assert unfold_ics(text) == "SUMMARY:Longsummary here"

    def test_unfolds_tab_continuation(self):
        text = "SUMMARY:Long\n\tsummary here"
        assert unfold_ics(text) == "SUMMARY:Longsummary here"

    def test_leaves_normal_lines(self):
        text = "SUMMARY:Short\nDTSTART:20260101"
        assert unfold_ics(text) == "SUMMARY:Short\nDTSTART:20260101"

    def test_unfolds_crlf(self):
        text = "SUMMARY:Long\r\n summary"
        assert unfold_ics(text) == "SUMMARY:Longsummary"


class TestParseDt:
    def test_utc_format(self):
        dt, all_day = parse_dt("DTSTART:20260714T170000Z")
        assert dt is not None
        assert dt.tzinfo == timezone.utc
        assert dt.year == 2026
        assert dt.month == 7
        assert dt.hour == 17
        assert all_day is False

    def test_tzid_format(self):
        dt, all_day = parse_dt("DTSTART;TZID=Europe/Vienna:20260714T170000")
        assert dt is not None
        assert dt.tzinfo == _TZ_VIENNA
        assert dt.hour == 17
        assert all_day is False

    def test_all_day_format(self):
        dt, all_day = parse_dt("DTSTART;VALUE=DATE:20260714")
        assert dt is not None
        assert all_day is True
        assert dt.year == 2026
        assert dt.month == 7
        assert dt.day == 14

    def test_dtend_utc(self):
        dt, all_day = parse_dt("DTEND:20260714T180000Z")
        assert dt is not None
        assert dt.hour == 18

    def test_invalid_line(self):
        dt, all_day = parse_dt("SUMMARY:Not a datetime")
        assert dt is None
        assert all_day is False

    def test_naive_datetime(self):
        dt, all_day = parse_dt("DTSTART:20260714T170000")
        assert dt is not None
        assert dt.tzinfo == timezone.utc
        assert all_day is False

    def test_invalid_date_value(self):
        dt, all_day = parse_dt("DTSTART:not-a-date")
        assert dt is None
        assert all_day is False

    def test_invalid_all_day_value(self):
        dt, all_day = parse_dt("DTSTART;VALUE=DATE:baddate")
        assert dt is None
        assert all_day is False


class TestParseICalendar:
    def test_full_event(self):
        event = parse_icalendar(SAMPLE_ICS_FULL, "/caldav/123/event1.ics")

        assert event is not None
        assert event["summary"] == "Zahnarzt Dr. Mueller"
        assert event["description"] == "Kontrolle und Reinigung"
        assert event["location"] == "Wiedner Hauptstrasse 10, Wien"
        assert event["caldav_uid"] == "abc-123-event"
        assert event["dtstart"].hour == 14
        assert event["dtstart"].tzinfo == _TZ_VIENNA
        assert event["dtend"].hour == 15
        assert event["dtend"].minute == 30
        assert event["all_day"] is False

    def test_utc_event(self):
        event = parse_icalendar(SAMPLE_ICS_UTC, "/caldav/123/event2.ics")

        assert event is not None
        assert event["summary"] == "Team Meeting"
        assert event["caldav_uid"] == "def-456-event"
        assert event["dtstart"].tzinfo == timezone.utc
        assert event["dtstart"].hour == 10

    def test_all_day_event(self):
        event = parse_icalendar(SAMPLE_ICS_ALL_DAY, "/caldav/123/event3.ics")

        assert event is not None
        assert event["summary"] == "Urlaub"
        assert event["all_day"] is True
        assert event["caldav_uid"] == "ghi-789-event"

    def test_minimal_event_uid_from_url(self):
        event = parse_icalendar(SAMPLE_ICS_MINIMAL, "/caldav/123/quick-note.ics")

        assert event is not None
        assert event["summary"] == "Quick Note"
        assert event["caldav_uid"] == "quick-note"

    def test_skip_event_without_summary(self):
        event = parse_icalendar(SAMPLE_ICS_NO_SUMMARY, "/caldav/123/bad.ics")
        assert event is None

    def test_folded_lines(self):
        event = parse_icalendar(SAMPLE_ICS_FOLDED, "/caldav/123/folded.ics")

        assert event is not None
        assert event["summary"] == "Long event with a verylong summary that is folded"
        assert event["description"] == "Also afolded description"

    def test_skip_event_without_dtstart(self):
        ics = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:no-dtstart
SUMMARY:Missing Start
END:VEVENT
END:VCALENDAR"""
        event = parse_icalendar(ics, "/test.ics")
        assert event is None

    def test_summary_with_language_param(self):
        """SUMMARY;LANGUAGE=de:text must be parsed correctly."""
        ics = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:lang-event
DTSTART:20260301T100000Z
SUMMARY;LANGUAGE=de:Teammeeting
END:VEVENT
END:VCALENDAR"""
        event = parse_icalendar(ics, "/test.ics")
        assert event is not None
        assert event["summary"] == "Teammeeting"

    def test_description_with_params(self):
        """DESCRIPTION with parameters must be parsed."""
        ics = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:desc-param
DTSTART:20260301T100000Z
SUMMARY:Test
DESCRIPTION;LANGUAGE=en:Project review notes
END:VEVENT
END:VCALENDAR"""
        event = parse_icalendar(ics, "/test.ics")
        assert event is not None
        assert event["description"] == "Project review notes"

    def test_location_with_params(self):
        """LOCATION with parameters must be parsed."""
        ics = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:loc-param
DTSTART:20260301T100000Z
SUMMARY:Test
LOCATION;LANGUAGE=de:Konferenzraum 3
END:VEVENT
END:VCALENDAR"""
        event = parse_icalendar(ics, "/test.ics")
        assert event is not None
        assert event["location"] == "Konferenzraum 3"


    def test_transp_default_opaque(self):
        """Events without TRANSP should default to OPAQUE."""
        event = parse_icalendar(SAMPLE_ICS_FULL, "/caldav/123/event1.ics")
        assert event is not None
        assert event["transp"] == "OPAQUE"

    def test_transp_transparent(self):
        """Events with TRANSP:TRANSPARENT should be parsed correctly."""
        ics = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:free-event
DTSTART:20260301T100000Z
DTEND:20260301T110000Z
SUMMARY:Optional Meeting
TRANSP:TRANSPARENT
END:VEVENT
END:VCALENDAR"""
        event = parse_icalendar(ics, "/test.ics")
        assert event is not None
        assert event["transp"] == "TRANSPARENT"

    def test_transp_opaque_explicit(self):
        """Events with explicit TRANSP:OPAQUE should be parsed correctly."""
        ics = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:busy-event
DTSTART:20260301T100000Z
SUMMARY:Important Meeting
TRANSP:OPAQUE
END:VEVENT
END:VCALENDAR"""
        event = parse_icalendar(ics, "/test.ics")
        assert event is not None
        assert event["transp"] == "OPAQUE"


class TestExtractValue:
    def test_simple_property(self):
        assert _extract_value("SUMMARY:Team Meeting") == "Team Meeting"

    def test_with_params(self):
        assert _extract_value("SUMMARY;LANGUAGE=de:Teammeeting") == "Teammeeting"

    def test_with_multiple_params(self):
        assert _extract_value("SUMMARY;LANGUAGE=de;X-CUSTOM=1:Titel") == "Titel"

    def test_colon_in_value(self):
        assert _extract_value("SUMMARY:Meeting: 10:00 Uhr") == "Meeting: 10:00 Uhr"

    def test_no_colon(self):
        assert _extract_value("BROKEN") == ""


class TestWindowsTimezones:
    def test_w_europe_standard_time(self):
        dt, all_day = parse_dt("DTSTART;TZID=W. Europe Standard Time:20260301T090000")
        assert dt is not None
        assert dt.hour == 9
        assert all_day is False

    def test_quoted_windows_tz(self):
        dt, all_day = parse_dt('DTSTART;TZID="W. Europe Standard Time":20260301T090000')
        assert dt is not None
        assert dt.hour == 9

    def test_eastern_standard_time(self):
        dt, all_day = parse_dt("DTSTART;TZID=Eastern Standard Time:20260301T090000")
        assert dt is not None
        assert str(dt.tzinfo) == "America/New_York"

    def test_unknown_tz_still_fails(self):
        dt, all_day = parse_dt("DTSTART;TZID=Totally Fake Timezone:20260301T090000")
        assert dt is None
