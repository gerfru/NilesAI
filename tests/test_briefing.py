"""Tests for the BriefingGenerator and briefing time parsing."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest

from niles.actions.briefing import BriefingGenerator

TZ = ZoneInfo("Europe/Vienna")


def _make_event(summary, hour=None, all_day=False, location=None):
    """Create a mock calendar event dict."""
    if all_day:
        dtstart = datetime(2026, 2, 25, 0, 0, tzinfo=TZ)
    else:
        dtstart = datetime(2026, 2, 25, hour, 0, tzinfo=TZ)
    event = {
        "summary": summary,
        "dtstart": dtstart,
        "dtend": None,
        "all_day": all_day,
        "location": location,
        "calendar_name": "Default",
    }
    return event


class TestFormatEvent:
    """Test _format_event helper."""

    def setup_method(self):
        self.gen = BriefingGenerator.__new__(BriefingGenerator)
        self.gen.tz = TZ

    def test_timed_event(self):
        event = _make_event("Standup", hour=9)
        result = self.gen._format_event(event)
        assert "09:00" in result
        assert "Standup" in result

    def test_all_day_event(self):
        event = _make_event("Urlaub", all_day=True)
        result = self.gen._format_event(event)
        assert "ganztägig" in result
        assert "Urlaub" in result

    def test_event_with_location(self):
        event = _make_event("Lunch", hour=12, location="Figlmüller")
        result = self.gen._format_event(event)
        assert "📍" in result
        assert "Figlmüller" in result


class TestFormatTask:
    """Test _format_task helper."""

    def setup_method(self):
        self.gen = BriefingGenerator.__new__(BriefingGenerator)
        self.gen.tz = TZ

    def test_simple_task(self):
        task = {"title": "Milch kaufen", "id": 1}
        result = self.gen._format_task(task)
        assert "Milch kaufen" in result

    def test_task_with_priority(self):
        task = {"title": "Dringend", "id": 2, "priority": 4}
        result = self.gen._format_task(task)
        assert "🔴" in result

    def test_task_with_due_date(self):
        task = {"title": "Abgabe", "id": 3, "due_date": "2026-02-25T00:00:00Z"}
        result = self.gen._format_task(task)
        assert "fällig:" in result
        assert "25.02." in result


class TestGenerateDaily:
    """Test generate_daily output."""

    @pytest.fixture
    def generator(self):
        gen = BriefingGenerator.__new__(BriefingGenerator)
        gen.tz = TZ
        gen.pool = AsyncMock()
        gen.vikunja_api_url = ""
        gen.vikunja_api_token = ""
        return gen

    @pytest.mark.asyncio
    async def test_with_events(self, generator):
        events = [
            _make_event("Standup", hour=9),
            _make_event("Lunch", hour=12, location="Figlmüller"),
        ]
        generator._get_events_for_range = AsyncMock(return_value=events)
        generator._get_open_tasks = AsyncMock(return_value=[])

        result = await generator.generate_daily()
        assert "Guten Morgen" in result
        assert "Termine heute" in result
        assert "(2)" in result
        assert "Standup" in result
        assert "Lunch" in result
        assert "Schönen Tag!" in result

    @pytest.mark.asyncio
    async def test_no_events(self, generator):
        generator._get_events_for_range = AsyncMock(return_value=[])
        generator._get_open_tasks = AsyncMock(return_value=[])

        result = await generator.generate_daily()
        assert "Keine Termine heute" in result

    @pytest.mark.asyncio
    async def test_with_overdue_tasks(self, generator):
        overdue = [{"title": "Steuererklärung", "id": 1, "due_date": "2026-02-20T00:00:00Z"}]
        generator._get_events_for_range = AsyncMock(return_value=[])
        generator._get_open_tasks = AsyncMock(return_value=overdue)

        result = await generator.generate_daily()
        assert "Überfällig" in result
        assert "Steuererklärung" in result

    @pytest.mark.asyncio
    async def test_no_vikunja(self, generator):
        """Without Vikunja, briefing still works (calendar only)."""
        events = [_make_event("Meeting", hour=10)]
        generator._get_events_for_range = AsyncMock(return_value=events)
        generator._get_open_tasks = AsyncMock(return_value=[])

        result = await generator.generate_daily()
        assert "Meeting" in result
        assert "Schönen Tag!" in result


class TestGenerateWeekly:
    """Test generate_weekly output."""

    @pytest.fixture
    def generator(self):
        gen = BriefingGenerator.__new__(BriefingGenerator)
        gen.tz = TZ
        gen.pool = AsyncMock()
        gen.vikunja_api_url = ""
        gen.vikunja_api_token = ""
        return gen

    @pytest.mark.asyncio
    async def test_weekly_with_events(self, generator):
        """Weekly overview groups events by day."""
        # Monday event
        mon_event = {
            "summary": "Standup",
            "dtstart": datetime(2026, 2, 23, 9, 0, tzinfo=TZ),
            "dtend": None,
            "all_day": False,
            "location": None,
            "calendar_name": "Work",
        }
        # Wednesday event
        wed_event = {
            "summary": "Zahnarzt",
            "dtstart": datetime(2026, 2, 25, 16, 0, tzinfo=TZ),
            "dtend": None,
            "all_day": False,
            "location": "Praxis",
            "calendar_name": "Personal",
        }
        generator._get_events_for_range = AsyncMock(return_value=[mon_event, wed_event])
        generator._get_open_tasks = AsyncMock(return_value=[])

        with patch("niles.actions.briefing.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 2, 23, 7, 15, tzinfo=TZ)
            mock_dt.fromisoformat = datetime.fromisoformat
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = await generator.generate_weekly()

        assert "Wochenübersicht" in result
        assert "Standup" in result
        assert "Zahnarzt" in result
        assert "frei" in result  # Some days should be free
        assert "Gute Woche!" in result


class TestParseTime:
    """Test _parse_briefing_time helper."""

    def test_valid_time(self):
        from niles.main import _parse_briefing_time
        assert _parse_briefing_time("07:30") == (7, 30)
        assert _parse_briefing_time("23:59") == (23, 59)
        assert _parse_briefing_time("00:00") == (0, 0)

    def test_invalid_time_fallback(self):
        from niles.main import _parse_briefing_time
        assert _parse_briefing_time("25:00") == (7, 30)
        assert _parse_briefing_time("abc") == (7, 30)
        assert _parse_briefing_time("") == (7, 30)


class TestGetOpenTasks:
    """Test _get_open_tasks with Vikunja API."""

    @pytest.mark.asyncio
    async def test_no_vikunja_configured(self):
        """Without Vikunja URL/token, returns empty list."""
        gen = BriefingGenerator.__new__(BriefingGenerator)
        gen.vikunja_api_url = ""
        gen.vikunja_api_token = ""
        result = await gen._get_open_tasks()
        assert result == []

    @pytest.mark.asyncio
    async def test_vikunja_error_returns_empty(self):
        """If Vikunja is unreachable, returns empty list (no crash)."""
        gen = BriefingGenerator.__new__(BriefingGenerator)
        gen.tz = TZ
        gen.vikunja_api_url = "http://localhost:99999/api/v1"
        gen.vikunja_api_token = "test-token"
        result = await gen._get_open_tasks()
        assert result == []
