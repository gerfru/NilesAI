"""Tests for the BriefingGenerator and briefing time parsing."""

from datetime import datetime, timedelta, timezone
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
        gen.vikunja_store = None
        gen.weather_latitude = ""
        gen.weather_longitude = ""
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
        overdue = [
            {"title": "Steuererklärung", "id": 1, "due_date": "2026-02-20T00:00:00Z"}
        ]
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
        gen.vikunja_store = None
        gen.weather_latitude = ""
        gen.weather_longitude = ""
        gen.timezone = "Europe/Vienna"
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
        """Without vikunja_store, returns empty list."""
        gen = BriefingGenerator.__new__(BriefingGenerator)
        gen.vikunja_store = None
        result = await gen._get_open_tasks()
        assert result == []

    @pytest.mark.asyncio
    async def test_no_user_id_returns_empty(self):
        """Without user_id, returns empty list."""
        gen = BriefingGenerator.__new__(BriefingGenerator)
        gen.vikunja_store = AsyncMock()
        result = await gen._get_open_tasks(user_id=None)
        assert result == []

    @pytest.mark.asyncio
    async def test_vikunja_error_returns_empty(self):
        """If Vikunja is unreachable, returns empty list (no crash)."""
        gen = BriefingGenerator.__new__(BriefingGenerator)
        gen.tz = TZ
        store = AsyncMock()
        store.get_credentials.return_value = {
            "api_token": "test-token",
            "api_url": "http://localhost:99999/api/v1",
        }
        gen.vikunja_store = store
        result = await gen._get_open_tasks(user_id=1)
        assert result == []


class TestFilterOverdue:
    """Test _filter_overdue edge cases."""

    def setup_method(self):
        self.gen = BriefingGenerator.__new__(BriefingGenerator)
        self.gen.tz = TZ

    def test_no_due_date(self):
        """Tasks without due_date are never overdue."""
        tasks = [{"title": "No due", "id": 1}]
        result = self.gen._filter_overdue(tasks)
        assert result == []

    def test_malformed_due_date(self):
        """Malformed date strings are silently skipped."""
        tasks = [{"title": "Bad date", "id": 1, "due_date": "not-a-date"}]
        result = self.gen._filter_overdue(tasks)
        assert result == []

    def test_future_task_not_overdue(self):
        """A task due in the future is not overdue."""
        future = (datetime.now(tz=TZ) + timedelta(days=7)).isoformat()
        tasks = [{"title": "Future", "id": 1, "due_date": future}]
        result = self.gen._filter_overdue(tasks)
        assert result == []

    def test_past_task_is_overdue(self):
        """A task due yesterday is overdue."""
        past = (datetime.now(tz=TZ) - timedelta(days=1)).isoformat()
        tasks = [{"title": "Yesterday", "id": 1, "due_date": past}]
        result = self.gen._filter_overdue(tasks)
        assert len(result) == 1
        assert result[0]["title"] == "Yesterday"

    def test_mixed_tasks(self):
        """Only past-due tasks are returned from a mixed list."""
        past = (datetime.now(tz=TZ) - timedelta(days=2)).isoformat()
        future = (datetime.now(tz=TZ) + timedelta(days=3)).isoformat()
        tasks = [
            {"title": "Overdue", "id": 1, "due_date": past},
            {"title": "Not yet", "id": 2, "due_date": future},
            {"title": "No date", "id": 3},
        ]
        result = self.gen._filter_overdue(tasks)
        assert len(result) == 1
        assert result[0]["id"] == 1


class TestOverdueTodayDeduplication:
    """Test that overdue tasks due today only appear in 'Überfällig', not 'Heute fällig'."""

    @pytest.fixture
    def generator(self):
        gen = BriefingGenerator.__new__(BriefingGenerator)
        gen.tz = TZ
        gen.pool = AsyncMock()
        gen.vikunja_store = AsyncMock()
        gen.weather_latitude = ""
        gen.weather_longitude = ""
        return gen

    @pytest.mark.asyncio
    async def test_overdue_today_only_in_overdue_section(self, generator):
        """A task due at 01:00 today (already past) should appear only in Überfällig."""
        # Task due at 01:00 today Vienna time — already past if briefing runs at 07:30
        now = datetime.now(tz=TZ).replace(hour=7, minute=30, second=0, microsecond=0)
        due_early_today = (
            now.replace(hour=1, minute=0)
            .astimezone(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )

        tasks = [
            {"title": "Frühaufgabe", "id": 10, "due_date": due_early_today},
            {
                "title": "Spätaufgabe",
                "id": 11,
                "due_date": now.replace(hour=18)
                .astimezone(timezone.utc)
                .isoformat()
                .replace("+00:00", "Z"),
            },
        ]
        generator._get_events_for_range = AsyncMock(return_value=[])
        generator._get_open_tasks = AsyncMock(return_value=tasks)

        with patch("niles.actions.briefing.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.fromisoformat = datetime.fromisoformat
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = await generator.generate_daily()

        # "Frühaufgabe" is overdue (01:00 < 07:30) → only in Überfällig
        assert "Überfällig" in result
        assert "Frühaufgabe" in result
        # "Spätaufgabe" is due today at 18:00 (not yet overdue) → only in Heute fällig
        assert "Heute fällig" in result
        assert "Spätaufgabe" in result

        # Frühaufgabe must NOT appear in the "Heute fällig" section
        heute_faellig_idx = result.index("Heute fällig")
        heute_section = result[heute_faellig_idx:]
        assert "Frühaufgabe" not in heute_section

    @pytest.mark.asyncio
    async def test_remaining_count_not_negative(self, generator):
        """With overdue+today dedup, remaining count must never be negative."""
        now = datetime.now(tz=TZ).replace(hour=7, minute=30, second=0, microsecond=0)
        due_early = (
            now.replace(hour=1)
            .astimezone(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )

        # 1 task, overdue (due today at 01:00, it's 07:30 now)
        tasks = [{"title": "Only task", "id": 1, "due_date": due_early}]
        generator._get_events_for_range = AsyncMock(return_value=[])
        generator._get_open_tasks = AsyncMock(return_value=tasks)

        with patch("niles.actions.briefing.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.fromisoformat = datetime.fromisoformat
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = await generator.generate_daily()

        # Must not contain negative remaining count
        assert "+(-" not in result
        assert "+-" not in result


class TestSendBriefingReturnValue:
    """Test that send_daily/weekly_briefing return bool correctly."""

    def _make_settings(self, channel="whatsapp"):
        return SimpleNamespace(
            briefing_channel=channel,
            signal_phone_number="",
            weather_latitude="",
            weather_longitude="",
        )

    @pytest.mark.asyncio
    async def test_daily_returns_false_no_session(self):
        """send_daily_briefing returns False when no WhatsApp session exists."""
        from niles.jobs.briefing import send_daily_briefing

        pool = AsyncMock()
        pool.fetchrow = AsyncMock(return_value=None)
        briefing_gen = AsyncMock()
        briefing_gen.generate_daily = AsyncMock(return_value="Test")
        app_state = SimpleNamespace(
            pool=pool,
            briefing_generator=briefing_gen,
            whatsapp_action=AsyncMock(),
            settings=self._make_settings("whatsapp"),
        )

        result = await send_daily_briefing(app_state)
        assert result is False

    @pytest.mark.asyncio
    async def test_weekly_returns_false_no_session(self):
        """send_weekly_briefing returns False when no WhatsApp session exists."""
        from niles.jobs.briefing import send_weekly_briefing

        pool = AsyncMock()
        pool.fetchrow = AsyncMock(return_value=None)
        briefing_gen = AsyncMock()
        briefing_gen.generate_weekly = AsyncMock(return_value="Test")
        app_state = SimpleNamespace(
            pool=pool,
            briefing_generator=briefing_gen,
            whatsapp_action=AsyncMock(),
            settings=self._make_settings("whatsapp"),
        )

        result = await send_weekly_briefing(app_state)
        assert result is False

    @pytest.mark.asyncio
    async def test_daily_returns_true_on_success(self):
        """send_daily_briefing returns True when briefing is sent."""
        from niles.jobs.briefing import send_daily_briefing

        pool = AsyncMock()
        pool.fetchrow = AsyncMock(
            return_value={
                "phone_number": "436601234567",
                "instance_name": "niles-wa-1",
                "user_id": 1,
            }
        )
        briefing_gen = AsyncMock()
        briefing_gen.generate_daily = AsyncMock(return_value="Test briefing")
        whatsapp = AsyncMock()
        app_state = SimpleNamespace(
            pool=pool,
            briefing_generator=briefing_gen,
            whatsapp_action=whatsapp,
            settings=self._make_settings("whatsapp"),
        )

        result = await send_daily_briefing(app_state)
        assert result is True
        whatsapp.send_message.assert_called_once_with(
            to="436601234567",
            text="Test briefing",
            instance="niles-wa-1",
        )

    @pytest.mark.asyncio
    async def test_daily_returns_false_on_exception(self):
        """send_daily_briefing returns False when generation fails."""
        from niles.jobs.briefing import send_daily_briefing

        briefing_gen = AsyncMock()
        briefing_gen.generate_daily = AsyncMock(side_effect=RuntimeError("boom"))
        app_state = SimpleNamespace(
            pool=AsyncMock(),
            briefing_generator=briefing_gen,
            whatsapp_action=AsyncMock(),
            settings=self._make_settings("whatsapp"),
        )

        result = await send_daily_briefing(app_state)
        assert result is False

    @pytest.mark.asyncio
    async def test_signal_channel(self):
        """send_daily_briefing sends via Signal when channel is signal."""
        from niles.jobs.briefing import send_daily_briefing

        briefing_gen = AsyncMock()
        briefing_gen.generate_daily = AsyncMock(return_value="Signal briefing")
        signal_action = AsyncMock()
        settings = SimpleNamespace(
            briefing_channel="signal",
            signal_phone_number="+436601234567",
            weather_latitude="",
            weather_longitude="",
        )
        app_state = SimpleNamespace(
            pool=AsyncMock(),
            briefing_generator=briefing_gen,
            whatsapp_action=AsyncMock(),
            signal_action=signal_action,
            settings=settings,
        )

        result = await send_daily_briefing(app_state)
        assert result is True
        signal_action.send_message.assert_called_once_with(
            to="+436601234567", text="Signal briefing"
        )

    @pytest.mark.asyncio
    async def test_both_channels(self):
        """send_daily_briefing sends via both channels when configured."""
        from niles.jobs.briefing import send_daily_briefing

        pool = AsyncMock()
        pool.fetchrow = AsyncMock(
            return_value={
                "phone_number": "436601234567",
                "instance_name": "niles-wa-1",
                "user_id": 1,
            }
        )
        briefing_gen = AsyncMock()
        briefing_gen.generate_daily = AsyncMock(return_value="Both briefing")
        whatsapp = AsyncMock()
        signal_action = AsyncMock()
        settings = SimpleNamespace(
            briefing_channel="both",
            signal_phone_number="+436601234567",
            weather_latitude="",
            weather_longitude="",
        )
        app_state = SimpleNamespace(
            pool=pool,
            briefing_generator=briefing_gen,
            whatsapp_action=whatsapp,
            signal_action=signal_action,
            settings=settings,
        )

        result = await send_daily_briefing(app_state)
        assert result is True
        whatsapp.send_message.assert_called_once()
        signal_action.send_message.assert_called_once()


# Mock Open-Meteo response for weather tests
_MOCK_DAILY_RESPONSE = {
    "daily": {
        "time": ["2026-02-27"],
        "weather_code": [3],
        "temperature_2m_min": [2.1],
        "temperature_2m_max": [8.5],
        "precipitation_sum": [1.2],
        "precipitation_probability_max": [65],
    }
}

_MOCK_FORECAST_RESPONSE = {
    "daily": {
        "time": ["2026-02-23", "2026-02-24", "2026-02-25"],
        "weather_code": [0, 61, 3],
        "temperature_2m_min": [-1.0, 3.0, 5.0],
        "temperature_2m_max": [6.0, 9.0, 11.0],
        "precipitation_sum": [0, 4.5, 0],
        "precipitation_probability_max": [5, 80, 10],
    }
}


class TestGetWeatherToday:
    """Test _get_weather_today."""

    def _make_gen(self, lat="48.2", lon="16.4"):
        gen = BriefingGenerator.__new__(BriefingGenerator)
        gen.tz = TZ
        gen.timezone = "Europe/Vienna"
        gen.weather_latitude = lat
        gen.weather_longitude = lon
        return gen

    @pytest.mark.asyncio
    async def test_no_coordinates_returns_none(self):
        gen = self._make_gen(lat="", lon="")
        result = await gen._get_weather_today()
        assert result is None

    @pytest.mark.asyncio
    async def test_happy_path(self):
        gen = self._make_gen()
        gen._fetch_daily_weather = AsyncMock(return_value=_MOCK_DAILY_RESPONSE["daily"])
        result = await gen._get_weather_today()

        assert result is not None
        assert "Bedeckt" in result
        assert "2.1" in result
        assert "8.5" in result
        assert "1.2mm" in result

    @pytest.mark.asyncio
    async def test_api_error_returns_none(self):
        gen = self._make_gen()
        gen._fetch_daily_weather = AsyncMock(return_value=None)
        result = await gen._get_weather_today()
        assert result is None


class TestGetWeatherForecast:
    """Test _get_weather_forecast."""

    def _make_gen(self, lat="48.2", lon="16.4"):
        gen = BriefingGenerator.__new__(BriefingGenerator)
        gen.tz = TZ
        gen.timezone = "Europe/Vienna"
        gen.weather_latitude = lat
        gen.weather_longitude = lon
        return gen

    @pytest.mark.asyncio
    async def test_no_coordinates_returns_none(self):
        gen = self._make_gen(lat="", lon="")
        result = await gen._get_weather_forecast(days=3)
        assert result is None

    @pytest.mark.asyncio
    async def test_happy_path(self):
        gen = self._make_gen()
        gen._fetch_daily_weather = AsyncMock(
            return_value=_MOCK_FORECAST_RESPONSE["daily"]
        )
        result = await gen._get_weather_forecast(days=3)

        assert result is not None
        assert len(result) == 4  # header + 3 days
        assert "Wetter" in result[0]
        assert "Klar" in result[1]  # code 0
        assert "Leichter Regen" in result[2]  # code 61
        assert "4.5mm" in result[2]

    @pytest.mark.asyncio
    async def test_api_error_returns_none(self):
        gen = self._make_gen()
        gen._fetch_daily_weather = AsyncMock(return_value=None)
        result = await gen._get_weather_forecast(days=3)
        assert result is None


class TestFetchDailyWeather:
    """Test _fetch_daily_weather HTTP interaction."""

    def _make_gen(self, lat="48.2", lon="16.4"):
        gen = BriefingGenerator.__new__(BriefingGenerator)
        gen.tz = TZ
        gen.timezone = "Europe/Vienna"
        gen.weather_latitude = lat
        gen.weather_longitude = lon
        return gen

    @pytest.mark.asyncio
    async def test_no_coordinates_returns_none(self):
        gen = self._make_gen(lat="", lon="")
        result = await gen._fetch_daily_weather(days=1)
        assert result is None

    @pytest.mark.asyncio
    async def test_http_error_returns_none(self):
        import httpx

        gen = self._make_gen()
        with patch("httpx.AsyncClient") as mock_cls:
            client = AsyncMock()
            client.get = AsyncMock(side_effect=httpx.ConnectError("connection refused"))
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await gen._fetch_daily_weather(days=1)

        assert result is None
