"""CardDAV contact sync from mailbox.org to PostgreSQL."""

import logging
import re

import asyncpg
import httpx

from ..config import Settings

logger = logging.getLogger(__name__)

# PROPFIND body to list vCard resources
_PROPFIND_BODY = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<D:propfind xmlns:D="DAV:">'
    "<D:prop><D:displayname/></D:prop>"
    "</D:propfind>"
)

# Namespace-agnostic regex for href elements containing .vcf paths
_HREF_REGEX = re.compile(
    r"<(?:[dD]:)?href[^>]*>\s*([^<]*\.vcf)\s*</(?:[dD]:)?href>", re.IGNORECASE
)


class CardDAVSync:
    """Syncs contacts from a CardDAV server to PostgreSQL."""

    def __init__(self, pool: asyncpg.Pool, config: Settings):
        self.pool = pool
        self.carddav_url = config.carddav_url
        self.auth = (config.carddav_user, config.carddav_password)
        # Base URL for fetching individual vCards (scheme + host)
        self._base_url = re.match(r"https?://[^/]+", config.carddav_url)
        self._base_url = self._base_url.group(0) if self._base_url else ""

    def update_config(self, config: Settings) -> None:
        """Hot-reload credentials from updated settings."""
        self.carddav_url = config.carddav_url
        self.auth = (config.carddav_user, config.carddav_password)
        match = re.match(r"https?://[^/]+", config.carddav_url)
        self._base_url = match.group(0) if match else ""
        logger.info("CardDAV credentials updated via settings UI")

    async def test_connection(self) -> tuple[bool, str]:
        """Test CardDAV connection with current credentials. Returns (ok, message)."""
        if not self.carddav_url:
            return False, "Keine CardDAV URL konfiguriert."
        try:
            vcf_urls = await self._propfind()
            return True, f"{len(vcf_urls)} Kontakte gefunden."
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                return False, "Authentifizierung fehlgeschlagen (401)."
            return False, f"Server-Fehler: HTTP {exc.response.status_code}"
        except Exception as exc:
            return False, f"Verbindung fehlgeschlagen: {exc}"

    async def initialize(self) -> None:
        """Create contacts table and indexes if they don't exist."""
        await self.pool.execute("""
            CREATE TABLE IF NOT EXISTS contacts (
                id SERIAL PRIMARY KEY,
                full_name TEXT NOT NULL,
                first_name TEXT,
                last_name TEXT,
                phone_primary TEXT,
                phone_mobile TEXT,
                phone_work TEXT,
                email TEXT,
                cardav_uid TEXT UNIQUE,
                cardav_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await self.pool.execute("""
            CREATE INDEX IF NOT EXISTS idx_contacts_full_name
            ON contacts (full_name)
        """)
        await self.pool.execute("""
            CREATE INDEX IF NOT EXISTS idx_contacts_phone
            ON contacts (phone_primary)
        """)
        logger.info("Contacts table initialized")

    async def sync_contacts(self) -> int:
        """Run a full CardDAV sync. Returns number of synced contacts."""
        logger.info("Starting CardDAV contact sync...")

        try:
            vcf_urls = await self._propfind()
        except Exception:
            logger.exception("PROPFIND failed")
            return 0

        if not vcf_urls:
            logger.warning("No vCard URLs found")
            return 0

        logger.info("Found %d vCard URLs", len(vcf_urls))

        count = 0
        for url in vcf_urls:
            try:
                vcard_text = await self._fetch_vcard(url)
                if not vcard_text:
                    continue

                contact = self._parse_vcard(vcard_text, url)
                if not contact:
                    continue

                await self._upsert_contact(contact)
                count += 1
            except Exception:
                logger.exception("Failed to sync vCard: %s", url)

        logger.info("Synced %d contacts", count)
        return count

    async def _propfind(self) -> list[str]:
        """Send PROPFIND request and extract .vcf URLs from response."""
        url = self.carddav_url
        if not url.endswith("/"):
            url += "/"
        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.request(
                "PROPFIND",
                url,
                content=_PROPFIND_BODY,
                headers={
                    "Depth": "1",
                    "Content-Type": "application/xml; charset=utf-8",
                },
                auth=self.auth,
                timeout=30,
            )
            response.raise_for_status()

        xml = response.text
        if not xml or len(xml) < 100:
            logger.warning("Empty or too short PROPFIND response")
            return []

        urls = _HREF_REGEX.findall(xml)
        return [u.strip() for u in urls if u.strip()]

    async def _fetch_vcard(self, url: str) -> str | None:
        """Fetch a single vCard by URL."""
        full_url = self._base_url + url if not url.startswith("http") else url

        async with httpx.AsyncClient() as client:
            response = await client.get(
                full_url,
                auth=self.auth,
                timeout=30,
            )
            response.raise_for_status()

        text = response.text
        if "BEGIN:VCARD" not in text:
            return None
        return text

    def _parse_vcard(self, vcard_text: str, url: str) -> dict | None:
        """Parse vCard text into a contact dict. Returns None if invalid."""
        lines = vcard_text.split("\n")
        contact = {
            "full_name": "",
            "first_name": "",
            "last_name": "",
            "phone_primary": "",
            "phone_mobile": "",
            "phone_work": "",
            "email": "",
            "cardav_uid": "",
            "cardav_url": url,
        }

        for raw_line in lines:
            line = raw_line.strip()

            if line.startswith("FN:"):
                contact["full_name"] = line[3:].strip()

            elif line.startswith("N:"):
                parts = line[2:].split(";")
                contact["last_name"] = (parts[0] if parts else "").strip()
                contact["first_name"] = (parts[1] if len(parts) > 1 else "").strip()

            elif line.startswith("TEL"):
                tel_match = re.match(r"TEL[^:]*:(.+)", line)
                if tel_match:
                    number = tel_match.group(1).strip()
                    type_match = re.search(r"TYPE=([^;:]+)", line, re.IGNORECASE)
                    tel_type = type_match.group(1).upper() if type_match else "OTHER"
                    if tel_type in ("CELL", "MOBILE"):
                        contact["phone_mobile"] = contact["phone_mobile"] or number
                    elif tel_type == "WORK":
                        contact["phone_work"] = contact["phone_work"] or number
                    else:
                        contact["phone_primary"] = contact["phone_primary"] or number

            elif line.startswith("EMAIL"):
                email_match = re.match(r"EMAIL[^:]*:(.+)", line)
                if email_match:
                    contact["email"] = contact["email"] or email_match.group(1).strip()

            elif line.startswith("UID:"):
                contact["cardav_uid"] = line[4:].strip()

        # Fallback UID from URL
        if not contact["cardav_uid"]:
            contact["cardav_uid"] = url.rsplit("/", 1)[-1].replace(".vcf", "")

        # Skip contacts without any name
        if not contact["full_name"] and not contact["first_name"]:
            return None

        # Build full_name from parts if missing
        if not contact["full_name"]:
            contact["full_name"] = (
                f"{contact['first_name']} {contact['last_name']}".strip()
            )

        return contact

    async def _upsert_contact(self, contact: dict) -> None:
        """Insert or update a contact by cardav_uid."""
        await self.pool.execute(
            """
            INSERT INTO contacts (
                full_name, first_name, last_name,
                phone_primary, phone_mobile, phone_work,
                email, cardav_uid, cardav_url, updated_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW())
            ON CONFLICT (cardav_uid) DO UPDATE SET
                full_name = EXCLUDED.full_name,
                first_name = EXCLUDED.first_name,
                last_name = EXCLUDED.last_name,
                phone_primary = EXCLUDED.phone_primary,
                phone_mobile = EXCLUDED.phone_mobile,
                phone_work = EXCLUDED.phone_work,
                email = EXCLUDED.email,
                cardav_url = EXCLUDED.cardav_url,
                updated_at = NOW()
            """,
            contact["full_name"],
            contact["first_name"],
            contact["last_name"],
            contact["phone_primary"],
            contact["phone_mobile"],
            contact["phone_work"],
            contact["email"],
            contact["cardav_uid"],
            contact["cardav_url"],
        )
