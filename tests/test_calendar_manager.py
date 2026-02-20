"""Tests for CalendarSourceManager (CRUD, sync, migration)."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from niles.config import Settings
from niles.sync.manager import CalendarSourceManager, _split_vevents


@pytest.fixture
def settings():
    return Settings(
        postgres_password="test",
        evolution_api_key="test",
        caldav_url="https://dav.mailbox.org/caldav/",
        caldav_user="testuser",
        caldav_password="testpass",
    )


@pytest.fixture
def pool():
    return AsyncMock()


@pytest.fixture
def manager(pool, settings):
    return CalendarSourceManager(pool, settings)


class TestSplitVevents:
    def test_single_event(self):
        ics = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:abc
SUMMARY:Test
DTSTART:20260101T100000Z
END:VEVENT
END:VCALENDAR"""
        blocks = _split_vevents(ics)
        assert len(blocks) == 1
        assert "BEGIN:VCALENDAR" in blocks[0]
        assert "BEGIN:VEVENT" in blocks[0]
        assert "END:VEVENT" in blocks[0]
        assert "END:VCALENDAR" in blocks[0]

    def test_multiple_events(self):
        ics = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:first
SUMMARY:First
DTSTART:20260101T100000Z
END:VEVENT
BEGIN:VEVENT
UID:second
SUMMARY:Second
DTSTART:20260201T100000Z
END:VEVENT
END:VCALENDAR"""
        blocks = _split_vevents(ics)
        assert len(blocks) == 2
        assert "first" in blocks[0]
        assert "second" in blocks[1]

    def test_empty_input(self):
        assert _split_vevents("") == []

    def test_no_vevent(self):
        assert _split_vevents("BEGIN:VCALENDAR\nEND:VCALENDAR") == []


class TestAddSource:
    async def test_validates_https(self, manager):
        with pytest.raises(ValueError, match="HTTPS"):
            await manager.add_source(
                name="Bad", url="http://example.com/cal.ics", source_type="ics",
            )

    async def test_validates_url_length(self, manager):
        with pytest.raises(ValueError, match="zu lang"):
            await manager.add_source(
                name="Bad", url="https://example.com/" + "a" * 2100, source_type="ics",
            )

    async def test_validates_name_length(self, manager):
        with pytest.raises(ValueError, match="zu lang"):
            await manager.add_source(
                name="N" * 300, url="https://example.com/cal.ics", source_type="ics",
            )

    async def test_validates_source_type(self, manager):
        with pytest.raises(ValueError, match="Unbekannter Typ"):
            await manager.add_source(
                name="Bad", url="https://example.com/cal.ics", source_type="ftp",
            )

    async def test_inserts_and_returns_row(self, manager, pool):
        mock_row = {
            "id": 1, "name": "Feiertage", "url": "https://example.com/cal.ics",
            "source_type": "ics", "writable": False, "enabled": True,
            "last_synced": None, "last_error": None, "created_at": "2026-01-01",
        }
        pool.fetchrow.return_value = MagicMock(**{"__iter__": lambda s: iter(mock_row.items()), "keys": lambda s: mock_row.keys()})
        pool.fetchrow.return_value.__getitem__ = lambda s, k: mock_row[k]
        # Use a real dict-like mock
        pool.fetchrow.return_value = mock_row

        result = await manager.add_source(
            name="Feiertage", url="https://example.com/cal.ics", source_type="ics",
        )
        pool.fetchrow.assert_called_once()
        assert result["name"] == "Feiertage"


class TestRemoveSource:
    async def test_returns_true_on_delete(self, manager, pool):
        pool.execute.return_value = "DELETE 1"
        removed = await manager.remove_source(42)
        assert removed is True

    async def test_returns_false_when_not_found(self, manager, pool):
        pool.execute.return_value = "DELETE 0"
        removed = await manager.remove_source(999)
        assert removed is False


class TestGetSources:
    async def test_returns_list_of_dicts(self, manager, pool):
        pool.fetch.return_value = [
            {"id": 1, "name": "A", "url": "https://a.com", "source_type": "ics",
             "writable": False, "enabled": True, "last_synced": None,
             "last_error": None, "created_at": "2026-01-01"},
        ]
        sources = await manager.get_sources()
        assert len(sources) == 1
        assert sources[0]["name"] == "A"


class TestSyncICS:
    async def test_fetches_and_parses_events(self, manager, pool):
        ics_text = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:ev-1
SUMMARY:Feiertag
DTSTART;VALUE=DATE:20260101
END:VEVENT
END:VCALENDAR"""
        source = {
            "id": 5, "name": "Feiertage", "url": "https://example.com/cal.ics",
            "source_type": "ics", "auth_user": None, "auth_password": None,
            "google_refresh_token": None, "google_token_expiry": None,
        }

        mock_response = MagicMock()
        mock_response.text = ics_text
        mock_response.content = ics_text.encode()
        mock_response.raise_for_status = MagicMock()

        with patch("niles.sync.manager.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            count = await manager._sync_ics(source)

        assert count == 1
        # Verify UID was prefixed
        upsert_call = pool.execute.call_args_list[-2]  # last execute before _set_synced
        args = upsert_call[0]
        uid_arg = args[7]  # caldav_uid is the 7th positional param (index 7)
        assert uid_arg.startswith("ics-5-")

    async def test_handles_empty_ics(self, manager, pool):
        source = {
            "id": 6, "name": "Empty", "url": "https://example.com/empty.ics",
            "source_type": "ics", "auth_user": None, "auth_password": None,
            "google_refresh_token": None, "google_token_expiry": None,
        }

        mock_response = MagicMock()
        mock_response.text = "BEGIN:VCALENDAR\nEND:VCALENDAR"
        mock_response.content = b"BEGIN:VCALENDAR\nEND:VCALENDAR"
        mock_response.raise_for_status = MagicMock()

        with patch("niles.sync.manager.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            count = await manager._sync_ics(source)

        assert count == 0

    async def test_records_error_on_http_failure(self, manager, pool):
        source = {
            "id": 7, "name": "Broken", "url": "https://example.com/broken.ics",
            "source_type": "ics", "auth_user": None, "auth_password": None,
            "google_refresh_token": None, "google_token_expiry": None,
        }

        with patch("niles.sync.manager.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.side_effect = httpx.HTTPError("Connection refused")
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(httpx.HTTPError):
                await manager._sync_ics(source)

        # Verify error was recorded
        pool.execute.assert_called()
        error_call = pool.execute.call_args
        assert "last_error" in error_call[0][0]


class TestSyncCalDAV:
    async def test_creates_caldav_sync_with_source_id(self, manager, pool):
        source = {
            "id": 10, "name": "CalDAV", "url": "https://dav.example.com/caldav/",
            "source_type": "caldav", "auth_user": "user", "auth_password": "pass",
            "google_refresh_token": None, "google_token_expiry": None,
        }

        with patch("niles.sync.manager.CalDAVSync") as mock_cls:
            mock_instance = AsyncMock()
            mock_instance.sync_events.return_value = 42
            mock_cls.return_value = mock_instance

            count = await manager._sync_caldav(source)

        assert count == 42
        # Verify CalDAVSync was created with correct params
        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs["source_id"] == 10
        assert call_kwargs["caldav_url"] == "https://dav.example.com/caldav/"


class TestSyncAll:
    async def test_syncs_multiple_sources(self, manager, pool):
        pool.fetch.return_value = [
            {"id": 1, "name": "ICS", "url": "https://a.com/cal.ics",
             "source_type": "ics", "auth_user": None, "auth_password": None,
             "google_refresh_token": None, "google_token_expiry": None},
            {"id": 2, "name": "CalDAV", "url": "https://dav.example.com/",
             "source_type": "caldav", "auth_user": "u", "auth_password": "p",
             "google_refresh_token": None, "google_token_expiry": None},
        ]

        with patch.object(manager, "_sync_ics", return_value=5) as mock_ics, \
             patch.object(manager, "_sync_caldav", return_value=10) as mock_caldav:
            total = await manager.sync_all()

        assert total == 15
        mock_ics.assert_called_once()
        mock_caldav.assert_called_once()

    async def test_error_in_one_source_continues(self, manager, pool):
        pool.fetch.return_value = [
            {"id": 1, "name": "Broken", "url": "https://broken.com/cal.ics",
             "source_type": "ics", "auth_user": None, "auth_password": None,
             "google_refresh_token": None, "google_token_expiry": None},
            {"id": 2, "name": "Good", "url": "https://good.com/cal.ics",
             "source_type": "ics", "auth_user": None, "auth_password": None,
             "google_refresh_token": None, "google_token_expiry": None},
        ]

        call_count = 0

        async def sync_ics_side_effect(src):
            nonlocal call_count
            call_count += 1
            if src["id"] == 1:
                raise Exception("Network error")
            return 3

        with patch.object(manager, "_sync_ics", side_effect=sync_ics_side_effect):
            total = await manager.sync_all()

        assert total == 3  # Only the second source succeeded
        assert call_count == 2  # Both were attempted


class TestMigrateEnvSource:
    async def test_migrates_when_table_empty(self, manager, pool):
        pool.fetchval.return_value = 0
        pool.fetchrow.return_value = {
            "id": 1, "name": "mailbox.org (migriert)",
            "url": "https://dav.mailbox.org/caldav/",
            "source_type": "caldav", "writable": True, "enabled": True,
            "last_synced": None, "last_error": None, "created_at": "2026-01-01",
        }

        await manager._migrate_env_source()

        pool.fetchrow.assert_called_once()
        sql = pool.fetchrow.call_args[0][0]
        assert "INSERT INTO calendar_sources" in sql

    async def test_skips_when_sources_exist(self, manager, pool):
        pool.fetchval.return_value = 2

        await manager._migrate_env_source()

        # Only fetchval should be called, no insert
        pool.fetchrow.assert_not_called()

    async def test_skips_when_no_env_config(self, pool):
        settings = Settings(
            postgres_password="test",
            evolution_api_key="test",
            caldav_url="",
            caldav_user="",
            caldav_password="",
        )
        mgr = CalendarSourceManager(pool, settings)
        pool.fetchval.return_value = 0

        await mgr._migrate_env_source()

        pool.fetchrow.assert_not_called()


class TestBuildAuth:
    def test_caldav_basic_auth(self, manager):
        source = {
            "source_type": "caldav",
            "auth_user": "user",
            "auth_password": "pass",
        }
        auth = manager._build_auth(source)
        assert isinstance(auth, httpx.BasicAuth)

    def test_google_not_implemented(self, manager):
        source = {"source_type": "google"}
        with pytest.raises(NotImplementedError):
            manager._build_auth(source)

    def test_caldav_none_credentials(self, manager):
        source = {
            "source_type": "caldav",
            "auth_user": None,
            "auth_password": None,
        }
        auth = manager._build_auth(source)
        assert isinstance(auth, httpx.BasicAuth)
