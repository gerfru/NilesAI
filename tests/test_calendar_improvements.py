"""Tests for calendar improvements: weekday parsing, all-day display, calendar filter, prompts."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest

from niles.actions.calendar import CalendarAction, _WEEKDAY_MAP
from niles.agent.prompts import build_system_prompt


# ---------------------------------------------------------------------------
# Weekday map
# ---------------------------------------------------------------------------

class TestWeekdayMap:
    def test_all_german_weekdays_present(self):
        for name in ("montag", "dienstag", "mittwoch", "donnerstag",
                      "freitag", "samstag", "sonntag"):
            assert name in _WEEKDAY_MAP

    def test_all_english_weekdays_present(self):
        for name in ("monday", "tuesday", "wednesday", "thursday",
                      "friday", "saturday", "sunday"):
            assert name in _WEEKDAY_MAP


# ---------------------------------------------------------------------------
# _parse_date — weekday names
# ---------------------------------------------------------------------------

class TestParseDateMalformedLLM:
    """Small LLMs sometimes wrap dates in dicts or lists."""

    @pytest.fixture
    def action(self):
        pool = AsyncMock()
        return CalendarAction(pool, timezone="Europe/Vienna")

    def test_dict_wrapped_date(self, action):
        """{'date': '2026-02-24'} should extract 2026-02-24."""
        result = action._parse_date("{'date': '2026-02-24'}")
        assert result is not None
        assert result.year == 2026
        assert result.month == 2
        assert result.day == 24

    def test_dict_wrapped_datetime(self, action):
        """{'date': '2026-02-24T14:00'} should extract the datetime."""
        result = action._parse_date("{'date': '2026-02-24T14:00'}")
        assert result is not None
        assert result.year == 2026
        assert result.hour == 14

    def test_dict_wrapped_datetime_with_tz(self, action):
        """{'date': '2026-02-24T14:00:00+01:00'} should extract with timezone."""
        result = action._parse_date("{'date': '2026-02-24T14:00:00+01:00'}")
        assert result is not None
        assert result.year == 2026
        assert result.hour == 14

    def test_dict_wrapped_datetime_utc(self, action):
        """{'date': '2026-02-24T14:00:00Z'} should extract with Z suffix."""
        result = action._parse_date("{'date': '2026-02-24T14:00:00Z'}")
        assert result is not None
        assert result.year == 2026

    def test_normal_date_unchanged(self, action):
        """Normal ISO dates should still work."""
        result = action._parse_date("2026-02-24")
        assert result is not None
        assert result.day == 24

    def test_relative_date_unchanged(self, action):
        """Relative terms like 'morgen' should still work."""
        result = action._parse_date("morgen")
        assert result is not None


class TestParseDateWeekday:
    @pytest.fixture
    def action(self):
        pool = AsyncMock()
        return CalendarAction(pool, timezone="Europe/Vienna")

    def test_next_monday_from_thursday(self, action):
        """If today is Thursday (weekday=3), 'montag' should be next Monday (+4 days)."""
        tz = ZoneInfo("Europe/Vienna")
        # Find a Thursday to anchor the test
        now = datetime(2026, 2, 19, 12, 0, tzinfo=tz)  # Thu 19 Feb 2026
        assert now.weekday() == 3  # Thursday

        # Monkey-patch datetime.now via _parse_date internals
        import niles.actions.calendar as cal_mod

        def fake_now(tz=None):
            return now

        cal_mod.datetime = type("FakeDT", (datetime,), {"now": staticmethod(fake_now)})
        try:
            result = action._parse_date("montag")
        finally:
            cal_mod.datetime = datetime

        assert result is not None
        assert result.weekday() == 0  # Monday
        assert result.day == 23  # Feb 23, 2026

    def test_same_weekday_returns_next_week(self, action):
        """If today is Thursday and we ask for 'donnerstag', we get next Thursday."""
        tz = ZoneInfo("Europe/Vienna")
        now = datetime(2026, 2, 19, 12, 0, tzinfo=tz)  # Thursday

        import niles.actions.calendar as cal_mod

        def fake_now(tz=None):
            return now

        cal_mod.datetime = type("FakeDT", (datetime,), {"now": staticmethod(fake_now)})
        try:
            result = action._parse_date("donnerstag")
        finally:
            cal_mod.datetime = datetime

        assert result is not None
        assert result.weekday() == 3  # Thursday
        assert result.day == 26  # Feb 26, 2026 (next week)

    def test_weekday_end_of_day(self, action):
        """end_of_day=True should set 23:59:59."""
        tz = ZoneInfo("Europe/Vienna")
        now = datetime(2026, 2, 19, 12, 0, tzinfo=tz)

        import niles.actions.calendar as cal_mod

        def fake_now(tz=None):
            return now

        cal_mod.datetime = type("FakeDT", (datetime,), {"now": staticmethod(fake_now)})
        try:
            result = action._parse_date("samstag", end_of_day=True)
        finally:
            cal_mod.datetime = datetime

        assert result is not None
        assert result.weekday() == 5  # Saturday
        assert result.hour == 23
        assert result.minute == 59
        assert result.second == 59

    def test_english_weekday(self, action):
        """English weekday names should also work."""
        tz = ZoneInfo("Europe/Vienna")
        now = datetime(2026, 2, 19, 12, 0, tzinfo=tz)

        import niles.actions.calendar as cal_mod

        def fake_now(tz=None):
            return now

        cal_mod.datetime = type("FakeDT", (datetime,), {"now": staticmethod(fake_now)})
        try:
            result = action._parse_date("Saturday")
        finally:
            cal_mod.datetime = datetime

        assert result is not None
        assert result.weekday() == 5


# ---------------------------------------------------------------------------
# _row_to_dict — all-day events
# ---------------------------------------------------------------------------

class TestRowToDictAllDay:
    @pytest.fixture
    def action(self):
        pool = AsyncMock()
        return CalendarAction(pool, timezone="Europe/Vienna")

    def test_all_day_event_date_only(self, action):
        """All-day events should output date-only, not timezone-converted time."""
        row = MagicMock()
        row.__getitem__ = lambda self, key: {
            "summary": "Geburtstag",
            "dtstart": datetime(2026, 3, 15, 0, 0, tzinfo=ZoneInfo("UTC")),
            "dtend": datetime(2026, 3, 16, 0, 0, tzinfo=ZoneInfo("UTC")),
            "all_day": True,
            "description": None,
            "location": None,
            "transp": "OPAQUE",
        }[key]

        result = action._row_to_dict(row)
        assert result["start"] == "2026-03-15"
        assert result["end"] == "2026-03-16"
        assert result["all_day"] is True

    def test_timed_event_has_timezone(self, action):
        """Non-all-day events should include full ISO with timezone."""
        tz = ZoneInfo("UTC")
        row = MagicMock()
        row.__getitem__ = lambda self, key: {
            "summary": "Meeting",
            "dtstart": datetime(2026, 3, 15, 14, 0, tzinfo=tz),
            "dtend": datetime(2026, 3, 15, 15, 0, tzinfo=tz),
            "all_day": False,
            "description": None,
            "location": None,
            "transp": "OPAQUE",
        }[key]

        result = action._row_to_dict(row)
        assert "T" in result["start"]  # Has time component
        assert "+01:00" in result["start"] or "+02:00" in result["start"]

    def test_transparent_event_has_status(self, action):
        """TRANSPARENT events should have status='verfuegbar'."""
        tz = ZoneInfo("UTC")
        row = MagicMock()
        row.__getitem__ = lambda self, key: {
            "summary": "Optional Sync",
            "dtstart": datetime(2026, 3, 15, 14, 0, tzinfo=tz),
            "dtend": datetime(2026, 3, 15, 15, 0, tzinfo=tz),
            "all_day": False,
            "description": None,
            "location": None,
            "transp": "TRANSPARENT",
        }[key]

        result = action._row_to_dict(row)
        assert result["status"] == "verfuegbar"

    def test_opaque_event_has_no_status(self, action):
        """OPAQUE events should not have a status field."""
        tz = ZoneInfo("UTC")
        row = MagicMock()
        row.__getitem__ = lambda self, key: {
            "summary": "Important Meeting",
            "dtstart": datetime(2026, 3, 15, 14, 0, tzinfo=tz),
            "dtend": datetime(2026, 3, 15, 15, 0, tzinfo=tz),
            "all_day": False,
            "description": None,
            "location": None,
            "transp": "OPAQUE",
        }[key]

        result = action._row_to_dict(row)
        assert "status" not in result

    def test_all_day_no_one_am(self, action):
        """Regression: midnight UTC must NOT become 01:00 Vienna for all-day events."""
        row = MagicMock()
        row.__getitem__ = lambda self, key: {
            "summary": "Feiertag",
            "dtstart": datetime(2026, 6, 1, 0, 0, tzinfo=ZoneInfo("UTC")),
            "dtend": None,
            "all_day": True,
            "description": None,
            "location": None,
            "transp": "OPAQUE",
        }[key]

        result = action._row_to_dict(row)
        assert "01:00" not in result["start"]
        assert result["start"] == "2026-06-01"


# ---------------------------------------------------------------------------
# _resolve_source_id
# ---------------------------------------------------------------------------

class TestResolveSourceId:
    async def test_returns_id_when_found(self):
        pool = AsyncMock()
        pool.fetchrow.return_value = {"id": 42}
        action = CalendarAction(pool)

        result = await action._resolve_source_id("Geburtstage")
        assert result == 42
        pool.fetchrow.assert_called_once()

    async def test_returns_none_when_not_found(self):
        pool = AsyncMock()
        pool.fetchrow.return_value = None
        action = CalendarAction(pool)

        result = await action._resolve_source_id("Nonexistent")
        assert result is None


# ---------------------------------------------------------------------------
# find_by_query with calendar filter
# ---------------------------------------------------------------------------

class TestFindByQueryCalendarFilter:
    async def test_passes_source_id_to_query(self):
        pool = AsyncMock()
        pool.fetchrow.return_value = {"id": 7}
        pool.fetch.return_value = []
        action = CalendarAction(pool)

        await action.find_by_query(query="Geburtstag", calendar="Birthdays")

        # Verify source_id=7 was passed as the 4th parameter
        fetch_call = pool.fetch.call_args
        assert fetch_call[0][4] == 7  # $4 = source_id

    async def test_no_calendar_passes_none(self):
        pool = AsyncMock()
        pool.fetch.return_value = []
        action = CalendarAction(pool)

        await action.find_by_query(query="Test")

        fetch_call = pool.fetch.call_args
        assert fetch_call[0][4] is None  # $4 = source_id should be None


# ---------------------------------------------------------------------------
# build_system_prompt — upcoming days + calendar sources
# ---------------------------------------------------------------------------

class TestBuildSystemPromptUpcomingDays:
    def test_includes_upcoming_7_days(self):
        prompt = build_system_prompt("Base prompt.", [], timezone="Europe/Vienna")
        assert "Kommende Tage:" in prompt

        weekdays_de = ["Montag", "Dienstag", "Mittwoch", "Donnerstag",
                        "Freitag", "Samstag", "Sonntag"]
        # At least some weekday names should appear in the upcoming section
        found_weekdays = sum(1 for w in weekdays_de if w in prompt)
        assert found_weekdays >= 7  # All 7 upcoming days should be listed

    def test_upcoming_days_are_correct(self):
        """The upcoming days should be the next 7 days from now."""
        prompt = build_system_prompt("Base.", [], timezone="Europe/Vienna")
        tz = ZoneInfo("Europe/Vienna")
        now = datetime.now(tz)

        for i in range(1, 8):
            day = now + timedelta(days=i)
            date_str = day.strftime("%d.%m.%Y")
            assert date_str in prompt, f"Expected {date_str} in prompt"


class TestBuildSystemPromptCalendarSources:
    def test_includes_calendar_sources(self):
        prompt = build_system_prompt(
            "Base.", [], timezone="Europe/Vienna",
            calendar_sources=["Hauptkalender", "Geburtstage", "Feiertage"],
        )
        assert "## Verfügbare Kalender" in prompt
        assert "- Hauptkalender" in prompt
        assert "- Geburtstage" in prompt
        assert "- Feiertage" in prompt

    def test_no_calendar_section_when_empty(self):
        prompt = build_system_prompt("Base.", [], timezone="Europe/Vienna")
        assert "Verfügbare Kalender" not in prompt

    def test_no_calendar_section_when_none(self):
        prompt = build_system_prompt(
            "Base.", [], timezone="Europe/Vienna", calendar_sources=None,
        )
        assert "Verfügbare Kalender" not in prompt
