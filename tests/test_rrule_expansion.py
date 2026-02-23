"""Tests for RRULE expansion in ical_parser.py."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from niles.sync.ical_parser import (
    _parse_exdate_line,
    expand_recurring_event,
    parse_icalendar,
)

_TZ_VIENNA = ZoneInfo("Europe/Vienna")


# --- RRULE extraction from parse_icalendar ---


class TestRRuleExtraction:
    def test_extracts_rrule(self):
        ics = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:weekly-meeting
DTSTART:20260101T100000Z
DTEND:20260101T110000Z
SUMMARY:Weekly Standup
RRULE:FREQ=WEEKLY;BYDAY=MO
END:VEVENT
END:VCALENDAR"""
        event = parse_icalendar(ics, "/test.ics")
        assert event is not None
        assert event["rrule"] == "RRULE:FREQ=WEEKLY;BYDAY=MO"

    def test_no_rrule(self):
        ics = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:single-event
DTSTART:20260101T100000Z
SUMMARY:One-time
END:VEVENT
END:VCALENDAR"""
        event = parse_icalendar(ics, "/test.ics")
        assert event is not None
        assert event["rrule"] == ""
        assert event["exdates"] == []

    def test_extracts_exdate_value_date(self):
        ics = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:birthday
DTSTART;VALUE=DATE:19830617
SUMMARY:Papa Geburtstag
RRULE:FREQ=YEARLY
EXDATE;VALUE=DATE:20250617
END:VEVENT
END:VCALENDAR"""
        event = parse_icalendar(ics, "/test.ics")
        assert event is not None
        assert len(event["exdates"]) == 1
        assert event["exdates"][0].year == 2025
        assert event["exdates"][0].month == 6
        assert event["exdates"][0].day == 17

    def test_extracts_exdate_utc(self):
        ics = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:meeting
DTSTART:20260101T100000Z
SUMMARY:Weekly
RRULE:FREQ=WEEKLY
EXDATE:20260108T100000Z,20260115T100000Z
END:VEVENT
END:VCALENDAR"""
        event = parse_icalendar(ics, "/test.ics")
        assert event is not None
        assert len(event["exdates"]) == 2

    def test_extracts_exdate_with_tzid(self):
        ics = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:meeting
DTSTART;TZID=Europe/Vienna:20260101T100000
SUMMARY:Weekly
RRULE:FREQ=WEEKLY
EXDATE;TZID=Europe/Vienna:20260108T100000
END:VEVENT
END:VCALENDAR"""
        event = parse_icalendar(ics, "/test.ics")
        assert event is not None
        assert len(event["exdates"]) == 1
        assert event["exdates"][0].tzinfo == _TZ_VIENNA


# --- EXDATE line parsing ---


class TestParseExdateLine:
    def test_value_date(self):
        result = _parse_exdate_line("EXDATE;VALUE=DATE:20260617")
        assert len(result) == 1
        assert result[0].year == 2026
        assert result[0].month == 6
        assert result[0].day == 17

    def test_utc_datetime(self):
        result = _parse_exdate_line("EXDATE:20260108T100000Z")
        assert len(result) == 1
        assert result[0].hour == 10
        assert result[0].tzinfo == timezone.utc

    def test_multiple_values(self):
        result = _parse_exdate_line("EXDATE:20260108T100000Z,20260115T100000Z")
        assert len(result) == 2

    def test_with_tzid(self):
        result = _parse_exdate_line("EXDATE;TZID=Europe/Vienna:20260108T100000")
        assert len(result) == 1
        assert result[0].tzinfo == _TZ_VIENNA

    def test_invalid_value_skipped(self):
        result = _parse_exdate_line("EXDATE:badvalue")
        assert len(result) == 0


# --- expand_recurring_event ---


class TestExpandRecurringEvent:
    """Test RRULE expansion logic."""

    def _make_event(self, **overrides):
        """Create a base event dict for testing."""
        event = {
            "summary": "Test Event",
            "dtstart": datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc),
            "dtend": datetime(2026, 1, 1, 11, 0, tzinfo=timezone.utc),
            "all_day": False,
            "description": "",
            "location": "",
            "transp": "OPAQUE",
            "caldav_uid": "test-uid-123",
            "caldav_url": "/test.ics",
            "rrule": "",
            "exdates": [],
        }
        event.update(overrides)
        return event

    def test_non_recurring_returns_single(self):
        event = self._make_event()
        window_start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        window_end = datetime(2026, 12, 31, tzinfo=timezone.utc)

        result = expand_recurring_event(event, window_start, window_end)

        assert len(result) == 1
        assert result[0]["summary"] == "Test Event"
        # rrule/exdates should be stripped from output
        assert "rrule" not in result[0]
        assert "exdates" not in result[0]

    def test_yearly_birthday(self):
        """A yearly birthday from 1983 should expand to occurrences in the window."""
        event = self._make_event(
            summary="Papa Geburtstag",
            dtstart=datetime(1983, 6, 17, 0, 0, tzinfo=timezone.utc),
            dtend=datetime(1983, 6, 18, 0, 0, tzinfo=timezone.utc),
            all_day=True,
            rrule="RRULE:FREQ=YEARLY",
            caldav_uid="birthday-papa",
        )
        window_start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        window_end = datetime(2027, 1, 1, tzinfo=timezone.utc)

        result = expand_recurring_event(event, window_start, window_end)

        assert len(result) == 1
        occ = result[0]
        assert occ["summary"] == "Papa Geburtstag"
        assert occ["dtstart"].year == 2026
        assert occ["dtstart"].month == 6
        assert occ["dtstart"].day == 17
        assert occ["all_day"] is True
        assert occ["caldav_uid"] == "birthday-papa@20260617"
        # Duration preserved (1 day)
        assert occ["dtend"] - occ["dtstart"] == timedelta(days=1)

    def test_weekly_recurring(self):
        """Weekly events should expand to multiple occurrences."""
        event = self._make_event(
            summary="Team Meeting",
            dtstart=datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc),  # Monday
            dtend=datetime(2026, 1, 5, 11, 0, tzinfo=timezone.utc),
            rrule="RRULE:FREQ=WEEKLY;BYDAY=MO",
        )
        # 4-week window
        window_start = datetime(2026, 1, 5, tzinfo=timezone.utc)
        window_end = datetime(2026, 2, 1, tzinfo=timezone.utc)

        result = expand_recurring_event(event, window_start, window_end)

        assert len(result) == 4
        # All on Mondays
        for occ in result:
            assert occ["dtstart"].weekday() == 0  # Monday
            assert occ["dtstart"].hour == 10
            assert (occ["dtend"] - occ["dtstart"]) == timedelta(hours=1)

        # Unique UIDs
        uids = [occ["caldav_uid"] for occ in result]
        assert len(set(uids)) == 4
        assert all(uid.startswith("test-uid-123@") for uid in uids)

    def test_exdate_excluded(self):
        """Occurrences on EXDATE should be skipped."""
        event = self._make_event(
            summary="Weekly",
            dtstart=datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc),
            dtend=datetime(2026, 1, 5, 11, 0, tzinfo=timezone.utc),
            rrule="RRULE:FREQ=WEEKLY;COUNT=4",
            exdates=[datetime(2026, 1, 12, 10, 0, tzinfo=timezone.utc)],
        )
        window_start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        window_end = datetime(2026, 12, 31, tzinfo=timezone.utc)

        result = expand_recurring_event(event, window_start, window_end)

        assert len(result) == 3  # 4 - 1 excluded
        dates = [occ["dtstart"].day for occ in result]
        assert 12 not in dates  # Jan 12 excluded

    def test_exdate_all_day(self):
        """EXDATE exclusion for all-day events compares by date."""
        event = self._make_event(
            summary="Yearly",
            dtstart=datetime(2020, 3, 15, 0, 0, tzinfo=timezone.utc),
            dtend=datetime(2020, 3, 16, 0, 0, tzinfo=timezone.utc),
            all_day=True,
            rrule="RRULE:FREQ=YEARLY",
            exdates=[datetime(2026, 3, 15, 0, 0, tzinfo=timezone.utc)],
        )
        window_start = datetime(2025, 1, 1, tzinfo=timezone.utc)
        window_end = datetime(2027, 12, 31, tzinfo=timezone.utc)

        result = expand_recurring_event(event, window_start, window_end)

        years = [occ["dtstart"].year for occ in result]
        assert 2025 in years
        assert 2026 not in years  # Excluded
        assert 2027 in years

    def test_window_filters_occurrences(self):
        """Only occurrences within the window are returned."""
        event = self._make_event(
            summary="Monthly",
            dtstart=datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc),
            dtend=datetime(2025, 1, 1, 11, 0, tzinfo=timezone.utc),
            rrule="RRULE:FREQ=MONTHLY;BYMONTHDAY=1",
        )
        window_start = datetime(2026, 3, 1, tzinfo=timezone.utc)
        window_end = datetime(2026, 5, 31, tzinfo=timezone.utc)

        result = expand_recurring_event(event, window_start, window_end)

        assert len(result) == 3  # March, April, May
        months = [occ["dtstart"].month for occ in result]
        assert months == [3, 4, 5]

    def test_rrule_with_count(self):
        """RRULE with COUNT limits total occurrences."""
        event = self._make_event(
            rrule="RRULE:FREQ=DAILY;COUNT=3",
        )
        window_start = datetime(2025, 1, 1, tzinfo=timezone.utc)
        window_end = datetime(2027, 12, 31, tzinfo=timezone.utc)

        result = expand_recurring_event(event, window_start, window_end)

        assert len(result) == 3

    def test_rrule_with_until(self):
        """RRULE with UNTIL stops at the specified date."""
        event = self._make_event(
            dtstart=datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc),
            dtend=datetime(2026, 1, 1, 11, 0, tzinfo=timezone.utc),
            rrule="RRULE:FREQ=WEEKLY;UNTIL=20260115T100000Z",
        )
        window_start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        window_end = datetime(2026, 12, 31, tzinfo=timezone.utc)

        result = expand_recurring_event(event, window_start, window_end)

        assert len(result) == 3  # Jan 1, 8, 15
        assert result[-1]["dtstart"].day == 15

    def test_invalid_rrule_returns_original(self):
        """An unparseable RRULE should fall back to returning the original event."""
        event = self._make_event(rrule="RRULE:INVALID_GARBAGE")
        window_start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        window_end = datetime(2026, 12, 31, tzinfo=timezone.utc)

        result = expand_recurring_event(event, window_start, window_end)

        assert len(result) == 1
        assert result[0]["summary"] == "Test Event"

    def test_no_occurrences_in_window(self):
        """If no occurrences fall in the window, return empty list."""
        event = self._make_event(
            dtstart=datetime(2020, 6, 17, 0, 0, tzinfo=timezone.utc),
            dtend=datetime(2020, 6, 18, 0, 0, tzinfo=timezone.utc),
            all_day=True,
            rrule="RRULE:FREQ=YEARLY",
        )
        # Window doesn't contain June
        window_start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        window_end = datetime(2026, 3, 1, tzinfo=timezone.utc)

        result = expand_recurring_event(event, window_start, window_end)

        assert result == []

    def test_preserves_transp(self):
        """Expanded occurrences carry over transp from master."""
        event = self._make_event(
            transp="TRANSPARENT",
            rrule="RRULE:FREQ=DAILY;COUNT=2",
        )
        window_start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        window_end = datetime(2026, 12, 31, tzinfo=timezone.utc)

        result = expand_recurring_event(event, window_start, window_end)

        for occ in result:
            assert occ["transp"] == "TRANSPARENT"

    def test_preserves_description_and_location(self):
        """Expanded occurrences carry over description/location from master."""
        event = self._make_event(
            description="Important!",
            location="Room 101",
            rrule="RRULE:FREQ=DAILY;COUNT=2",
        )
        window_start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        window_end = datetime(2026, 12, 31, tzinfo=timezone.utc)

        result = expand_recurring_event(event, window_start, window_end)

        for occ in result:
            assert occ["description"] == "Important!"
            assert occ["location"] == "Room 101"

    def test_duration_preserved(self):
        """Each occurrence has the same duration as the master event."""
        event = self._make_event(
            dtstart=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
            dtend=datetime(2026, 1, 1, 12, 30, tzinfo=timezone.utc),  # 3.5 hours
            rrule="RRULE:FREQ=DAILY;COUNT=2",
        )
        window_start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        window_end = datetime(2026, 12, 31, tzinfo=timezone.utc)

        result = expand_recurring_event(event, window_start, window_end)

        for occ in result:
            assert occ["dtend"] - occ["dtstart"] == timedelta(hours=3, minutes=30)


# --- Full ICS parsing + expansion integration ---


class TestFullICSExpansion:
    """Integration tests: parse_icalendar → expand_recurring_event."""

    def test_yearly_birthday_ics(self):
        ics = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:birthday-papa-123
DTSTART;VALUE=DATE:19470617
SUMMARY:Papa Geburtstag
RRULE:FREQ=YEARLY
END:VEVENT
END:VCALENDAR"""
        event = parse_icalendar(ics, "/birthdays/papa.ics")
        assert event is not None
        assert event["rrule"] == "RRULE:FREQ=YEARLY"

        window_start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        window_end = datetime(2027, 1, 1, tzinfo=timezone.utc)
        result = expand_recurring_event(event, window_start, window_end)

        assert len(result) == 1
        assert result[0]["dtstart"].year == 2026
        assert result[0]["dtstart"].month == 6
        assert result[0]["dtstart"].day == 17
        assert result[0]["caldav_uid"] == "birthday-papa-123@20260617"

    def test_weekly_meeting_with_exdate_ics(self):
        ics = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:weekly-standup-456
DTSTART:20260105T100000Z
DTEND:20260105T103000Z
SUMMARY:Standup
RRULE:FREQ=WEEKLY;BYDAY=MO;COUNT=5
EXDATE:20260119T100000Z
END:VEVENT
END:VCALENDAR"""
        event = parse_icalendar(ics, "/meetings/standup.ics")
        assert event is not None

        window_start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        window_end = datetime(2026, 12, 31, tzinfo=timezone.utc)
        result = expand_recurring_event(event, window_start, window_end)

        assert len(result) == 4  # 5 - 1 excluded
        dates = sorted(occ["dtstart"].day for occ in result)
        assert 19 not in dates  # Jan 19 excluded
