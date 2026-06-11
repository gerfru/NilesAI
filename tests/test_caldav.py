"""Tests for CalDAV calendar sync.

Parser tests (unfold, parse_dt, parse_icalendar) have been moved to
test_ical_parser.py.  This file tests CalDAVSync behaviour:
collection discovery, event upsert, sync flow, and event creation.
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import httpx
import pytest

from niles.sync.caldav import CalDAVSync, _escape_ical_text

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

# Root-level response listing calendar collections (no .ics files)
SAMPLE_PROPFIND_ROOT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<D:multistatus xmlns:D="DAV:" xmlns:CAL="urn:ietf:params:xml:ns:caldav"
               xmlns:CS="http://calendarserver.org/ns/">
  <D:response>
    <D:href>/caldav/</D:href>
    <D:propstat>
      <D:prop><D:displayname>Calendars</D:displayname></D:prop>
    </D:propstat>
  </D:response>
  <D:response>
    <D:href>/caldav/Y2FsOi8vMC8zMQ/</D:href>
    <D:propstat>
      <D:prop><D:displayname>Kalender</D:displayname></D:prop>
    </D:propstat>
  </D:response>
  <D:response>
    <D:href>/caldav/Y2FsOi8vMTUvMA/</D:href>
    <D:propstat>
      <D:prop><D:displayname>SK Sturm Graz</D:displayname></D:prop>
    </D:propstat>
  </D:response>
  <D:response>
    <D:href>/caldav/schedule-inbox/</D:href>
    <D:propstat>
      <D:prop><D:displayname>Schedule Inbox</D:displayname></D:prop>
    </D:propstat>
  </D:response>
  <D:response>
    <D:href>/caldav/schedule-outbox/</D:href>
    <D:propstat>
      <D:prop><D:displayname>Schedule Outbox</D:displayname></D:prop>
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

SAMPLE_ICS_NO_SUMMARY = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:bad-event
DTSTART:20260515T090000Z
END:VEVENT
END:VCALENDAR"""


@pytest.fixture
def pool():
    return AsyncMock()


@pytest.fixture
def sync(pool):
    return CalDAVSync(
        pool=pool,
        caldav_url="https://dav.example.com/caldav/123/",
        auth=httpx.BasicAuth("testuser", "testpass"),
        timezone="Europe/Vienna",
    )


def _make_root_sync(pool, caldav_calendars=""):
    return CalDAVSync(
        pool=pool,
        caldav_url="https://dav.example.com/caldav/",
        auth=httpx.BasicAuth("testuser", "testpass"),
        timezone="Europe/Vienna",
        caldav_calendars=caldav_calendars,
    )


class TestGetSyncCollections:
    async def test_direct_calendar_url(self, sync):
        """When URL has .ics files directly, return that URL."""
        with patch.object(sync, "_propfind_request", return_value=SAMPLE_PROPFIND_XML):
            urls = await sync._get_sync_collections()

        assert urls == ["https://dav.example.com/caldav/123/"]

    async def test_returns_empty_on_no_response(self, sync):
        with patch.object(sync, "_propfind_request", return_value=None):
            urls = await sync._get_sync_collections()

        assert urls == []

    async def test_discovers_collections_from_root(self, pool):
        """When URL is root, discover sub-collections."""
        root_sync = _make_root_sync(pool)

        with patch.object(root_sync, "_propfind_request", return_value=SAMPLE_PROPFIND_ROOT_XML):
            urls = await root_sync._get_sync_collections()

        assert len(urls) == 2
        assert any("Y2FsOi8vMC8zMQ" in u for u in urls)
        assert any("Y2FsOi8vMTUvMA" in u for u in urls)
        assert not any("schedule-" in u for u in urls)

    async def test_filters_by_caldav_calendars_setting(self, pool):
        """When caldav_calendars is set, only matching collections are returned."""
        root_sync = _make_root_sync(pool, caldav_calendars="/caldav/Y2FsOi8vMC8zMQ/")

        with patch.object(root_sync, "_propfind_request", return_value=SAMPLE_PROPFIND_ROOT_XML):
            urls = await root_sync._get_sync_collections()

        assert len(urls) == 1
        assert "Y2FsOi8vMC8zMQ" in urls[0]
        assert not any("Y2FsOi8vMTUvMA" in u for u in urls)


class TestEscapeIcalText:
    def test_escapes_semicolons(self):
        assert _escape_ical_text("a;b") == "a\\;b"

    def test_escapes_commas(self):
        assert _escape_ical_text("a,b") == "a\\,b"

    def test_escapes_backslashes(self):
        assert _escape_ical_text("a\\b") == "a\\\\b"

    def test_escapes_newlines(self):
        assert _escape_ical_text("line1\nline2") == "line1\\nline2"

    def test_escapes_crlf(self):
        assert _escape_ical_text("line1\r\nline2") == "line1\\nline2"

    def test_strips_bare_cr(self):
        assert _escape_ical_text("line1\rline2") == "line1line2"

    def test_plain_text_unchanged(self):
        assert _escape_ical_text("Hello World") == "Hello World"

    def test_combined_escaping(self):
        assert _escape_ical_text("a;b,c\\d\ne") == "a\\;b\\,c\\\\d\\ne"


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

    async def test_upsert_includes_source_id(self, pool):
        """When source_id is set, it is included in the INSERT."""
        sync_with_source = CalDAVSync(
            pool=pool,
            caldav_url="https://dav.example.com/caldav/",
            auth=httpx.BasicAuth("u", "p"),
            timezone="Europe/Vienna",
            source_id=42,
        )
        event = {
            "summary": "Sourced Event",
            "dtstart": datetime(2026, 2, 20, 14, 0, tzinfo=_TZ_VIENNA),
            "dtend": datetime(2026, 2, 20, 15, 0, tzinfo=_TZ_VIENNA),
            "all_day": False,
            "description": "",
            "location": "",
            "caldav_uid": "uid-sourced",
            "caldav_url": "/test.ics",
        }

        await sync_with_source._upsert_event(event)

        args = pool.execute.call_args[0]
        assert 42 in args  # source_id should be passed


class TestSyncEvents:
    async def test_full_sync_flow(self, sync, pool):
        with (
            patch.object(
                sync,
                "_get_sync_collections",
                return_value=[
                    "https://dav.example.com/caldav/123/",
                ],
            ),
            patch.object(
                sync,
                "_report_time_range",
                return_value=[
                    (SAMPLE_ICS_FULL, "/caldav/123/event1.ics"),
                ],
            ),
            patch.object(sync, "_upsert_event") as mock_upsert,
        ):
            count = await sync.sync_events()

        assert count == 1
        mock_upsert.assert_called_once()

    async def test_sync_skips_invalid_events(self, sync, pool):
        with (
            patch.object(
                sync,
                "_get_sync_collections",
                return_value=[
                    "https://dav.example.com/caldav/123/",
                ],
            ),
            patch.object(
                sync,
                "_report_time_range",
                return_value=[
                    (SAMPLE_ICS_FULL, "/caldav/123/good.ics"),
                    (SAMPLE_ICS_NO_SUMMARY, "/caldav/123/bad.ics"),
                ],
            ),
            patch.object(sync, "_upsert_event") as mock_upsert,
        ):
            count = await sync.sync_events()

        assert count == 1
        mock_upsert.assert_called_once()

    async def test_sync_returns_zero_on_discovery_failure(self, sync):
        with patch.object(sync, "_get_sync_collections", side_effect=OSError("Network")):
            count = await sync.sync_events()

        assert count == 0

    async def test_sync_returns_zero_when_no_collections(self, sync):
        with patch.object(sync, "_get_sync_collections", return_value=[]):
            count = await sync.sync_events()

        assert count == 0


class TestCreateEvent:
    """Tests for CalDAVSync.create_event with collection discovery."""

    @pytest.fixture(autouse=True)
    def _mock_resolve(self, sync):
        """Mock _resolve_write_collection to return the fixture caldav_url."""
        with patch.object(
            sync,
            "_resolve_write_collection",
            return_value=sync.caldav_url,
        ):
            yield

    async def test_creates_event_on_server(self, sync, pool):
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.put.return_value = mock_response
        sync._client = mock_client

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

        mock_client = AsyncMock()
        mock_client.put.return_value = mock_response
        sync._client = mock_client

        result = await sync.create_event(
            summary="Meeting",
            dtstart_str="2026-02-20T14:00",
        )

        # End should be 1 hour after start
        assert "15:00" in result["end"]

    async def test_put_failure_raises(self, sync, pool):
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = Exception("HTTP 403")

        mock_client = AsyncMock()
        mock_client.put.return_value = mock_response
        sync._client = mock_client

        with pytest.raises(Exception, match="HTTP 403"):
            await sync.create_event(
                summary="Fail",
                dtstart_str="2026-02-20T14:00",
            )

        # No local upsert on failure
        pool.execute.assert_not_called()

    async def test_injection_attempt_escaped(self, sync, pool):
        """Verify iCalendar injection via summary is neutralized by escaping."""
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.put.return_value = mock_response
        sync._client = mock_client

        result = await sync.create_event(
            summary="Meeting\r\nDTEND:20260101T000000Z\r\nSUMMARY:Injected",
            dtstart_str="2026-02-20T14:00",
        )

        assert result["status"] == "created"
        put_call = mock_client.put.call_args
        body = put_call.kwargs.get("content") or put_call[1].get("content", "")
        # Newlines should be escaped, not raw
        assert "SUMMARY:Meeting\\nDTEND" in body
        # Should NOT contain a raw injected SUMMARY line
        assert "\r\nSUMMARY:Injected" not in body

    async def test_invalid_iso_raises(self, sync, pool):
        """Invalid ISO datetime string should raise ValueError."""
        with pytest.raises(ValueError):
            await sync.create_event(
                summary="Bad",
                dtstart_str="not-a-date",
            )


class TestResolveWriteCollection:
    """Tests for _resolve_write_collection (discovery before PUT)."""

    async def test_uses_first_discovered_collection(self, pool):
        """Root CalDAV URL discovers sub-collections; first one is used."""
        root_sync = _make_root_sync(pool)

        with patch.object(
            root_sync,
            "_get_sync_collections",
            return_value=[
                "https://dav.example.com/caldav/Y2FsOi8vMC8zMQ/",
                "https://dav.example.com/caldav/Y2FsOi8vMTUvMA/",
            ],
        ):
            url = await root_sync._resolve_write_collection()

        assert url == "https://dav.example.com/caldav/Y2FsOi8vMC8zMQ/"

    async def test_returns_first_discovered_collection(self, sync):
        """Single collection discovered; returned as-is."""
        with patch.object(
            sync,
            "_get_sync_collections",
            return_value=[
                "https://dav.example.com/caldav/123/",
            ],
        ):
            url = await sync._resolve_write_collection()

        assert url == "https://dav.example.com/caldav/123/"

    async def test_raises_when_no_collections(self, pool):
        """Raises RuntimeError when no writable collection is found."""
        root_sync = _make_root_sync(pool)

        with patch.object(root_sync, "_get_sync_collections", return_value=[]):
            with pytest.raises(RuntimeError, match="No writable calendar"):
                await root_sync._resolve_write_collection()
