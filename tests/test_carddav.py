"""Tests for CardDAV contact sync."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from niles.config import Settings
from niles.sync.carddav import CardDAVSync


SAMPLE_PROPFIND_XML = """<?xml version="1.0" encoding="utf-8"?>
<D:multistatus xmlns:D="DAV:">
  <D:response>
    <D:href>/carddav/32/</D:href>
    <D:propstat>
      <D:prop><D:displayname>Contacts</D:displayname></D:prop>
    </D:propstat>
  </D:response>
  <D:response>
    <D:href>/carddav/32/contact1.vcf</D:href>
    <D:propstat>
      <D:prop><D:displayname/></D:prop>
    </D:propstat>
  </D:response>
  <D:response>
    <D:href>/carddav/32/contact2.vcf</D:href>
    <D:propstat>
      <D:prop><D:displayname/></D:prop>
    </D:propstat>
  </D:response>
</D:multistatus>"""

SAMPLE_VCARD_FULL = """BEGIN:VCARD
VERSION:3.0
FN:Max Mustermann
N:Mustermann;Max;;;
TEL;TYPE=CELL:+43 660 1234567
TEL;TYPE=WORK:+43 1 9876543
TEL;TYPE=HOME:+43 1 1111111
EMAIL;TYPE=HOME:max@example.com
EMAIL;TYPE=WORK:max@work.com
UID:abc-123-def
END:VCARD"""

SAMPLE_VCARD_MINIMAL = """BEGIN:VCARD
VERSION:3.0
FN:Anna Test
TEL:+43 660 9999999
END:VCARD"""

SAMPLE_VCARD_NO_FN = """BEGIN:VCARD
VERSION:3.0
N:Mueller;Hans;;;
TEL;TYPE=MOBILE:+43 660 5555555
END:VCARD"""

SAMPLE_VCARD_EMPTY = """BEGIN:VCARD
VERSION:3.0
TEL:+43 660 0000000
END:VCARD"""


@pytest.fixture
def config():
    return Settings(
        postgres_password="test",
        evolution_api_key="test",
        carddav_url="https://dav.mailbox.org/carddav/32",
        carddav_user="testuser",
        carddav_password="testpass",
    )


@pytest.fixture
def pool():
    return AsyncMock()


@pytest.fixture
def sync(pool, config):
    return CardDAVSync(pool, config)


class TestInitialize:
    async def test_creates_table_and_indexes(self, sync, pool):
        # _migrate_phones does a fetch that returns [] by default
        pool.fetch.return_value = []
        await sync.initialize()
        # contacts table + full_name index + contact_phones table + contact_phones index
        assert pool.execute.call_count == 4
        calls = [c[0][0] for c in pool.execute.call_args_list]
        assert "CREATE TABLE IF NOT EXISTS contacts" in calls[0]
        assert "idx_contacts_full_name" in calls[1]
        assert "CREATE TABLE IF NOT EXISTS contact_phones" in calls[2]
        assert "idx_contact_phones_contact_id" in calls[3]


class TestPropfind:
    async def test_extracts_vcf_urls(self, sync):
        mock_response = MagicMock()
        mock_response.text = SAMPLE_PROPFIND_XML
        mock_response.raise_for_status = MagicMock()

        with patch("niles.sync.carddav.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.request.return_value = mock_response
            mock_client_cls.return_value.__aenter__ = AsyncMock(
                return_value=mock_client
            )
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            urls = await sync._propfind()

        assert len(urls) == 2
        assert "/carddav/32/contact1.vcf" in urls
        assert "/carddav/32/contact2.vcf" in urls

    async def test_returns_empty_on_short_response(self, sync):
        mock_response = MagicMock()
        mock_response.text = "<short/>"
        mock_response.raise_for_status = MagicMock()

        with patch("niles.sync.carddav.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.request.return_value = mock_response
            mock_client_cls.return_value.__aenter__ = AsyncMock(
                return_value=mock_client
            )
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            urls = await sync._propfind()

        assert urls == []


class TestParseVcard:
    def test_full_vcard(self, sync):
        contact = sync._parse_vcard(SAMPLE_VCARD_FULL, "/carddav/32/contact1.vcf")

        assert contact is not None
        assert contact["full_name"] == "Max Mustermann"
        assert contact["first_name"] == "Max"
        assert contact["last_name"] == "Mustermann"
        assert contact["email"] == "max@example.com"
        assert contact["cardav_uid"] == "abc-123-def"
        assert contact["cardav_url"] == "/carddav/32/contact1.vcf"
        # All phone numbers collected
        assert ("mobile", "+43 660 1234567") in contact["phones"]
        assert ("work", "+43 1 9876543") in contact["phones"]
        assert ("home", "+43 1 1111111") in contact["phones"]
        assert len(contact["phones"]) == 3

    def test_minimal_vcard(self, sync):
        contact = sync._parse_vcard(SAMPLE_VCARD_MINIMAL, "/carddav/32/anna.vcf")

        assert contact is not None
        assert contact["full_name"] == "Anna Test"
        # TEL without TYPE → "other"
        assert len(contact["phones"]) == 1
        assert contact["phones"][0] == ("other", "+43 660 9999999")
        assert contact["email"] == ""

    def test_skip_empty_name(self, sync):
        contact = sync._parse_vcard(SAMPLE_VCARD_EMPTY, "/carddav/32/empty.vcf")
        assert contact is None

    def test_uid_fallback_from_url(self, sync):
        contact = sync._parse_vcard(SAMPLE_VCARD_MINIMAL, "/carddav/32/anna-test.vcf")

        assert contact is not None
        assert contact["cardav_uid"] == "anna-test"

    def test_name_fallback_from_parts(self, sync):
        contact = sync._parse_vcard(SAMPLE_VCARD_NO_FN, "/carddav/32/hans.vcf")

        assert contact is not None
        assert contact["full_name"] == "Hans Mueller"
        assert contact["first_name"] == "Hans"
        assert contact["last_name"] == "Mueller"
        assert ("mobile", "+43 660 5555555") in contact["phones"]

    def test_multiple_phones_same_type(self, sync):
        """Two mobile numbers should both be stored."""
        vcard = """BEGIN:VCARD
VERSION:3.0
FN:Dual Phone
TEL;TYPE=CELL:+43 660 1111111
TEL;TYPE=CELL:+43 660 2222222
UID:dual-phone
END:VCARD"""
        contact = sync._parse_vcard(vcard, "/carddav/32/dual.vcf")

        assert contact is not None
        assert len(contact["phones"]) == 2
        assert ("mobile", "+43 660 1111111") in contact["phones"]
        assert ("mobile", "+43 660 2222222") in contact["phones"]


class TestUpsertContact:
    async def test_upsert_executes_query(self, sync, pool):
        contact = {
            "full_name": "Test User",
            "first_name": "Test",
            "last_name": "User",
            "phones": [("mobile", "+43 660 1234567"), ("home", "+43 1 9999999")],
            "email": "test@example.com",
            "cardav_uid": "uid-123",
            "cardav_url": "/carddav/32/test.vcf",
        }
        pool.fetchval.return_value = 42  # returned contact id

        await sync._upsert_contact(contact)

        # fetchval for RETURNING id
        sql = pool.fetchval.call_args[0][0]
        assert "ON CONFLICT (cardav_uid) DO UPDATE" in sql
        assert "RETURNING id" in sql
        args = pool.fetchval.call_args[0][1:]
        assert "Test User" in args
        assert "uid-123" in args

        # DELETE old phones + INSERT for each phone
        execute_calls = pool.execute.call_args_list
        assert any("DELETE FROM contact_phones" in c[0][0] for c in execute_calls)
        insert_calls = [
            c for c in execute_calls if "INSERT INTO contact_phones" in c[0][0]
        ]
        assert len(insert_calls) == 2


class TestSyncContacts:
    async def test_full_sync_flow(self, sync, pool):
        with (
            patch.object(
                sync,
                "_propfind",
                return_value=[
                    "/carddav/32/contact1.vcf",
                ],
            ) as mock_propfind,
            patch.object(sync, "_fetch_vcard", return_value=SAMPLE_VCARD_FULL),
            patch.object(sync, "_upsert_contact") as mock_upsert,
        ):
            count = await sync.sync_contacts()

        assert count == 1
        mock_propfind.assert_called_once()
        mock_upsert.assert_called_once()

    async def test_sync_skips_invalid_vcards(self, sync, pool):
        with (
            patch.object(
                sync,
                "_propfind",
                return_value=[
                    "/carddav/32/good.vcf",
                    "/carddav/32/empty.vcf",
                ],
            ),
            patch.object(
                sync,
                "_fetch_vcard",
                side_effect=[
                    SAMPLE_VCARD_FULL,
                    SAMPLE_VCARD_EMPTY,
                ],
            ),
            patch.object(sync, "_upsert_contact") as mock_upsert,
        ):
            count = await sync.sync_contacts()

        assert count == 1
        mock_upsert.assert_called_once()

    async def test_sync_returns_zero_on_propfind_failure(self, sync):
        with patch.object(sync, "_propfind", side_effect=Exception("Network error")):
            count = await sync.sync_contacts()

        assert count == 0

    async def test_sync_returns_zero_when_no_urls(self, sync):
        with patch.object(sync, "_propfind", return_value=[]):
            count = await sync.sync_contacts()

        assert count == 0
