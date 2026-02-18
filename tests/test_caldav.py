"""Tests for CalDAV calendar sync."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from niles.config import Settings
from niles.sync.caldav import CalDAVSync, _parse_dt, _unfold_ics

_TZ_VIENNA = ZoneInfo("Europe/Vienna")


SAMPLE_PROPFIND_XML = """<?xml version="1.0" encoding="utf-8"?>
<D:multistatus xmlns:D="DAV:">
  <D:response>
    <D:href>/caldav/123/</D:href>
    <D:propstat>
      <D:prop><D:displayname>Calendar</D:displayname></D:prop>
    </D:propstat>
  </D:response>
  <D:response>
    <D:href>/caldav/123/event1.ics</D:href>
    <D:propstat>
      <D:prop><D:displayname/></D:prop>
    </D:propstat>
  </D:response>
  <D:response>
    <D:href>/caldav/123/event2.ics</D:href>
    <D:propstat>
      <D:prop><D:displayname/></D:prop>
    </D:propstat>
  </D:response>
</D:multistatus>"""

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


@pytest.fixture
def config():
    return Settings(
        postgres_password="test",
        evolution_api_key="test",
        caldav_url="https://dav.example.com/caldav/123/",
        caldav_user="testuser",
        caldav_password="testpass",
    )


@pytest.fixture
def pool():
    return AsyncMock()


@pytest.fixture
def sync(pool, config):
    return CalDAVSync(pool, config)


class TestInitialize:
    async def test_creates_table_and_indexes(self, sync, pool):
        await sync.initialize()
        assert pool.execute.call_count == 3
        calls = [c[0][0] for c in pool.execute.call_args_list]
        assert "CREATE TABLE IF NOT EXISTS events" in calls[0]
        assert "idx_events_dtstart" in calls[1]
        assert "idx_events_summary" in calls[2]


class TestPropfind:
    async def test_extracts_ics_urls(self, sync):
        mock_response = MagicMock()
        mock_response.text = SAMPLE_PROPFIND_XML
        mock_response.raise_for_status = MagicMock()

        with patch("niles.sync.caldav.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.request.return_value = mock_response
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            urls = await sync._propfind()

        assert len(urls) == 2
        assert "/caldav/123/event1.ics" in urls
        assert "/caldav/123/event2.ics" in urls

    async def test_returns_empty_on_short_response(self, sync):
        mock_response = MagicMock()
        mock_response.text = "<short/>"
        mock_response.raise_for_status = MagicMock()

        with patch("niles.sync.caldav.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.request.return_value = mock_response
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            urls = await sync._propfind()

        assert urls == []


class TestUnfoldIcs:
    def test_unfolds_space_continuation(self):
        # RFC 5545: CRLF + space/tab is removed entirely (space is folding indicator)
        text = "SUMMARY:Long\n summary here"
        assert _unfold_ics(text) == "SUMMARY:Longsummary here"

    def test_unfolds_tab_continuation(self):
        text = "SUMMARY:Long\n\tsummary here"
        assert _unfold_ics(text) == "SUMMARY:Longsummary here"

    def test_leaves_normal_lines(self):
        text = "SUMMARY:Short\nDTSTART:20260101"
        assert _unfold_ics(text) == "SUMMARY:Short\nDTSTART:20260101"

    def test_unfolds_crlf(self):
        text = "SUMMARY:Long\r\n summary"
        assert _unfold_ics(text) == "SUMMARY:Longsummary"


class TestParseDt:
    def test_utc_format(self):
        dt, all_day = _parse_dt("DTSTART:20260714T170000Z")
        assert dt is not None
        assert dt.tzinfo == timezone.utc
        assert dt.year == 2026
        assert dt.month == 7
        assert dt.hour == 17
        assert all_day is False

    def test_tzid_format(self):
        dt, all_day = _parse_dt("DTSTART;TZID=Europe/Vienna:20260714T170000")
        assert dt is not None
        assert dt.tzinfo == _TZ_VIENNA
        assert dt.hour == 17
        assert all_day is False

    def test_all_day_format(self):
        dt, all_day = _parse_dt("DTSTART;VALUE=DATE:20260714")
        assert dt is not None
        assert all_day is True
        assert dt.year == 2026
        assert dt.month == 7
        assert dt.day == 14

    def test_dtend_utc(self):
        dt, all_day = _parse_dt("DTEND:20260714T180000Z")
        assert dt is not None
        assert dt.hour == 18

    def test_invalid_line(self):
        dt, all_day = _parse_dt("SUMMARY:Not a datetime")
        assert dt is None
        assert all_day is False

    def test_naive_datetime(self):
        dt, all_day = _parse_dt("DTSTART:20260714T170000")
        assert dt is not None
        assert dt.tzinfo == timezone.utc
        assert all_day is False


class TestParseICalendar:
    def test_full_event(self, sync):
        event = sync._parse_icalendar(SAMPLE_ICS_FULL, "/caldav/123/event1.ics")

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

    def test_utc_event(self, sync):
        event = sync._parse_icalendar(SAMPLE_ICS_UTC, "/caldav/123/event2.ics")

        assert event is not None
        assert event["summary"] == "Team Meeting"
        assert event["caldav_uid"] == "def-456-event"
        assert event["dtstart"].tzinfo == timezone.utc
        assert event["dtstart"].hour == 10

    def test_all_day_event(self, sync):
        event = sync._parse_icalendar(SAMPLE_ICS_ALL_DAY, "/caldav/123/event3.ics")

        assert event is not None
        assert event["summary"] == "Urlaub"
        assert event["all_day"] is True
        assert event["caldav_uid"] == "ghi-789-event"

    def test_minimal_event_uid_from_url(self, sync):
        event = sync._parse_icalendar(SAMPLE_ICS_MINIMAL, "/caldav/123/quick-note.ics")

        assert event is not None
        assert event["summary"] == "Quick Note"
        assert event["caldav_uid"] == "quick-note"

    def test_skip_event_without_summary(self, sync):
        event = sync._parse_icalendar(SAMPLE_ICS_NO_SUMMARY, "/caldav/123/bad.ics")
        assert event is None

    def test_folded_lines(self, sync):
        event = sync._parse_icalendar(SAMPLE_ICS_FOLDED, "/caldav/123/folded.ics")

        assert event is not None
        assert event["summary"] == "Long event with a verylong summary that is folded"
        assert event["description"] == "Also afolded description"


class TestUpsertEvent:
    async def test_upsert_executes_query(self, sync, pool):
        event = {
            "summary": "Test Event",
            "dtstart": datetime(2026, 2, 20, 14, 0, tzinfo=_TZ_VIENNA),
            "dtend": datetime(2026, 2, 20, 15, 0, tzinfo=_TZ_VIENNA),
            "all_day": False,
            "description": "A test event",
            "location": "Office",
            "caldav_uid": "uid-123",
            "caldav_url": "/caldav/123/test.ics",
        }

        await sync._upsert_event(event)

        pool.execute.assert_called_once()
        sql = pool.execute.call_args[0][0]
        assert "ON CONFLICT (caldav_uid) DO UPDATE" in sql
        args = pool.execute.call_args[0][1:]
        assert "Test Event" in args
        assert "uid-123" in args


class TestSyncEvents:
    async def test_full_sync_flow(self, sync, pool):
        with patch.object(sync, "_propfind", return_value=[
            "/caldav/123/event1.ics",
        ]) as mock_propfind, \
            patch.object(sync, "_fetch_ics", return_value=SAMPLE_ICS_FULL), \
            patch.object(sync, "_upsert_event") as mock_upsert:

            count = await sync.sync_events()

        assert count == 1
        mock_propfind.assert_called_once()
        mock_upsert.assert_called_once()

    async def test_sync_skips_invalid_events(self, sync, pool):
        with patch.object(sync, "_propfind", return_value=[
            "/caldav/123/good.ics",
            "/caldav/123/bad.ics",
        ]), \
            patch.object(sync, "_fetch_ics", side_effect=[
                SAMPLE_ICS_FULL,
                SAMPLE_ICS_NO_SUMMARY,
            ]), \
            patch.object(sync, "_upsert_event") as mock_upsert:

            count = await sync.sync_events()

        assert count == 1
        mock_upsert.assert_called_once()

    async def test_sync_returns_zero_on_propfind_failure(self, sync):
        with patch.object(sync, "_propfind", side_effect=Exception("Network error")):
            count = await sync.sync_events()

        assert count == 0

    async def test_sync_returns_zero_when_no_urls(self, sync):
        with patch.object(sync, "_propfind", return_value=[]):
            count = await sync.sync_events()

        assert count == 0


class TestCreateEvent:
    async def test_creates_event_on_server(self, sync, pool):
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.raise_for_status = MagicMock()

        with patch("niles.sync.caldav.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.put.return_value = mock_response
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await sync.create_event(
                summary="Zahnarzt",
                dtstart_str="2026-02-20T14:00",
                description="Kontrolle",
                location="Wien",
            )

        assert result["status"] == "created"
        assert result["summary"] == "Zahnarzt"
        assert "uid" in result

        # Verify PUT was called with correct content
        put_call = mock_client.put.call_args
        body = put_call.kwargs.get("content") or put_call[1].get("content", "")
        assert "BEGIN:VCALENDAR" in body
        assert "SUMMARY:Zahnarzt" in body
        assert "DESCRIPTION:Kontrolle" in body
        assert "LOCATION:Wien" in body

        # Verify local upsert
        pool.execute.assert_called_once()

    async def test_default_end_time(self, sync, pool):
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.raise_for_status = MagicMock()

        with patch("niles.sync.caldav.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.put.return_value = mock_response
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await sync.create_event(
                summary="Meeting",
                dtstart_str="2026-02-20T14:00",
            )

        # End should be 1 hour after start
        assert "15:00" in result["end"]

    async def test_put_failure_raises(self, sync, pool):
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = Exception("HTTP 403")

        with patch("niles.sync.caldav.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.put.return_value = mock_response
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(Exception, match="HTTP 403"):
                await sync.create_event(
                    summary="Fail",
                    dtstart_str="2026-02-20T14:00",
                )

        # No local upsert on failure
        pool.execute.assert_not_called()
