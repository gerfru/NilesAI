"""Calendar source manager – unified CRUD, sync, and .env migration."""

import logging
from datetime import datetime

import asyncpg
import httpx

from .caldav import CalDAVSync
from .ical_parser import parse_icalendar

logger = logging.getLogger(__name__)

_MAX_ICS_SIZE = 5 * 1024 * 1024  # 5 MB limit per ICS file
_ICS_TIMEOUT = 60  # seconds


class CalendarSourceManager:
    """Manages calendar sources of all types (ICS, CalDAV, Google).

    Responsibilities:
    - CRUD for calendar_sources table
    - Schema migrations (calendar_sources + events.source_id)
    - Auto-migration of .env CalDAV config on first startup
    - Sync orchestration across all enabled sources
    - Event creation on writable sources
    """

    def __init__(self, pool: asyncpg.Pool, settings):
        self.pool = pool
        self.settings = settings

    async def initialize(self) -> None:
        """Create calendar_sources table, extend events table, run migration."""
        await self.pool.execute("""
            CREATE TABLE IF NOT EXISTS calendar_sources (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                url TEXT NOT NULL,
                source_type TEXT NOT NULL DEFAULT 'ics',
                writable BOOLEAN DEFAULT FALSE,
                enabled BOOLEAN DEFAULT TRUE,
                auth_user TEXT,
                auth_password TEXT,
                google_refresh_token TEXT,
                google_token_expiry TIMESTAMP WITH TIME ZONE,
                last_synced TIMESTAMP WITH TIME ZONE,
                last_error TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(url, source_type)
            )
        """)
        # Extend events table with source_id (NULL = legacy/CalDAV before migration)
        await self.pool.execute("""
            ALTER TABLE events ADD COLUMN IF NOT EXISTS
                source_id INTEGER REFERENCES calendar_sources(id) ON DELETE CASCADE
        """)
        await self.pool.execute("""
            CREATE INDEX IF NOT EXISTS idx_events_source_id ON events (source_id)
        """)
        await self._migrate_env_source()
        logger.info("Calendar source manager initialized")

    # --- CRUD ---

    async def add_source(
        self,
        name: str,
        url: str,
        source_type: str = "ics",
        writable: bool = False,
        auth_user: str | None = None,
        auth_password: str | None = None,
        google_refresh_token: str | None = None,
        google_token_expiry: datetime | None = None,
    ) -> dict:
        """Add a new calendar source. Returns the created row."""
        if not url.startswith("https://"):
            raise ValueError("Nur HTTPS-URLs sind erlaubt")
        if len(url) > 2048:
            raise ValueError("URL ist zu lang (max 2048 Zeichen)")
        if len(name) > 200:
            raise ValueError("Name ist zu lang (max 200 Zeichen)")
        if source_type not in ("ics", "caldav", "google"):
            raise ValueError(f"Unbekannter Typ: {source_type}")

        row = await self.pool.fetchrow(
            """
            INSERT INTO calendar_sources
                (name, url, source_type, writable, auth_user, auth_password,
                 google_refresh_token, google_token_expiry)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING id, name, url, source_type, writable, enabled,
                      last_synced, last_error, created_at
            """,
            name, url, source_type, writable,
            auth_user, auth_password,
            google_refresh_token, google_token_expiry,
        )
        logger.info("Added calendar source: %s (%s)", name, source_type)
        return dict(row)

    async def remove_source(self, source_id: int) -> bool:
        """Remove a calendar source. Events are CASCADE-deleted."""
        result = await self.pool.execute(
            "DELETE FROM calendar_sources WHERE id = $1", source_id,
        )
        removed = result == "DELETE 1"
        if removed:
            logger.info("Removed calendar source %d", source_id)
        return removed

    async def get_sources(self) -> list[dict]:
        """List all calendar sources."""
        rows = await self.pool.fetch(
            """
            SELECT id, name, url, source_type, writable, enabled,
                   last_synced, last_error, created_at
            FROM calendar_sources ORDER BY created_at
            """
        )
        return [dict(r) for r in rows]

    async def get_writable_source(self) -> dict | None:
        """Return the first enabled, writable calendar source."""
        row = await self.pool.fetchrow(
            """
            SELECT id, name, url, source_type, auth_user, auth_password,
                   google_refresh_token, google_token_expiry
            FROM calendar_sources
            WHERE writable = TRUE AND enabled = TRUE
            ORDER BY created_at
            LIMIT 1
            """
        )
        return dict(row) if row else None

    # --- Sync ---

    async def sync_all(self) -> int:
        """Sync all enabled sources. Returns total events synced."""
        sources = await self.pool.fetch(
            """
            SELECT id, name, url, source_type, auth_user, auth_password,
                   google_refresh_token, google_token_expiry
            FROM calendar_sources WHERE enabled = TRUE
            """
        )
        total = 0
        for src in sources:
            src = dict(src)
            try:
                if src["source_type"] == "ics":
                    count = await self._sync_ics(src)
                elif src["source_type"] in ("caldav", "google"):
                    count = await self._sync_caldav(src)
                else:
                    continue
                total += count
            except Exception:
                logger.exception(
                    "Sync failed for source %d (%s)", src["id"], src["name"],
                )
        logger.info("Calendar sync complete: %d events from %d sources", total, len(sources))
        return total

    async def sync_source(self, source_id: int) -> int:
        """Sync a single source by ID."""
        row = await self.pool.fetchrow(
            """
            SELECT id, name, url, source_type, auth_user, auth_password,
                   google_refresh_token, google_token_expiry
            FROM calendar_sources WHERE id = $1 AND enabled = TRUE
            """,
            source_id,
        )
        if not row:
            return 0
        src = dict(row)
        if src["source_type"] == "ics":
            return await self._sync_ics(src)
        if src["source_type"] in ("caldav", "google"):
            return await self._sync_caldav(src)
        return 0

    async def _sync_ics(self, source: dict) -> int:
        """Sync an ICS subscription: HTTP GET, parse, upsert."""
        source_id = source["id"]
        url = source["url"]
        logger.info("Syncing ICS source '%s' from %s", source["name"], url)

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    url, timeout=_ICS_TIMEOUT, follow_redirects=True,
                )
                response.raise_for_status()
                if len(response.content) > _MAX_ICS_SIZE:
                    raise ValueError(f"ICS file too large: {len(response.content)} bytes")
        except Exception as exc:
            await self._set_error(source_id, str(exc)[:500])
            raise

        ics_text = response.text
        count = 0

        for vevent_text in _split_vevents(ics_text):
            event = parse_icalendar(vevent_text, url)
            if event:
                # Prefix UID with source_id to avoid collision with CalDAV UIDs
                event["caldav_uid"] = f"ics-{source_id}-{event['caldav_uid']}"
                await self._upsert_event(event, source_id)
                count += 1

        await self._set_synced(source_id)
        logger.info("  '%s': synced %d events", source["name"], count)
        return count

    async def _sync_caldav(self, source: dict) -> int:
        """Sync a CalDAV source using CalDAVSync."""
        auth = self._build_auth(source)
        sync = CalDAVSync(
            pool=self.pool,
            caldav_url=source["url"],
            auth=auth,
            timezone=self.settings.timezone,
            source_id=source["id"],
        )
        try:
            count = await sync.sync_events()
            await self._set_synced(source["id"])
            return count
        except Exception as exc:
            await self._set_error(source["id"], str(exc)[:500])
            raise

    def _build_auth(self, source: dict) -> httpx.Auth:
        """Build httpx auth for a source (Basic or Bearer)."""
        if source["source_type"] == "google":
            # Google Calendar OAuth – placeholder for Phase B
            raise NotImplementedError("Google Calendar sync not yet implemented")
        return httpx.BasicAuth(source["auth_user"] or "", source["auth_password"] or "")

    # --- Event creation ---

    async def create_event(
        self,
        source: dict,
        summary: str,
        dtstart_str: str,
        dtend_str: str | None = None,
        description: str = "",
        location: str = "",
    ) -> dict:
        """Create an event on a writable CalDAV/Google source."""
        auth = self._build_auth(source)
        sync = CalDAVSync(
            pool=self.pool,
            caldav_url=source["url"],
            auth=auth,
            timezone=self.settings.timezone,
            source_id=source["id"],
        )
        return await sync.create_event(
            summary=summary,
            dtstart_str=dtstart_str,
            dtend_str=dtend_str,
            description=description,
            location=location,
        )

    # --- Helpers ---

    async def _upsert_event(self, event: dict, source_id: int) -> None:
        """Insert or update an ICS event."""
        await self.pool.execute(
            """
            INSERT INTO events (
                summary, dtstart, dtend, all_day,
                description, location, caldav_uid, caldav_url,
                source_id, updated_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW())
            ON CONFLICT (caldav_uid) DO UPDATE SET
                summary = EXCLUDED.summary,
                dtstart = EXCLUDED.dtstart,
                dtend = EXCLUDED.dtend,
                all_day = EXCLUDED.all_day,
                description = EXCLUDED.description,
                location = EXCLUDED.location,
                caldav_url = EXCLUDED.caldav_url,
                source_id = EXCLUDED.source_id,
                updated_at = NOW()
            """,
            event["summary"],
            event["dtstart"],
            event["dtend"],
            event["all_day"],
            event["description"],
            event["location"],
            event["caldav_uid"],
            event["caldav_url"],
            source_id,
        )

    async def _set_synced(self, source_id: int) -> None:
        """Update last_synced timestamp, clear error."""
        await self.pool.execute(
            "UPDATE calendar_sources SET last_synced = NOW(), last_error = NULL WHERE id = $1",
            source_id,
        )

    async def _set_error(self, source_id: int, error_msg: str) -> None:
        """Store sync error message."""
        await self.pool.execute(
            "UPDATE calendar_sources SET last_error = $1 WHERE id = $2",
            error_msg, source_id,
        )

    async def _migrate_env_source(self) -> None:
        """Auto-migrate .env CalDAV config to calendar_sources on first startup."""
        count = await self.pool.fetchval("SELECT COUNT(*) FROM calendar_sources")
        if count > 0:
            return  # Already have sources

        cfg = self.settings
        if not cfg.caldav_url or not cfg.caldav_user:
            return  # Nothing to migrate

        await self.add_source(
            name="mailbox.org (migriert)",
            url=cfg.caldav_url,
            source_type="caldav",
            writable=True,
            auth_user=cfg.caldav_user,
            auth_password=cfg.caldav_password,
        )
        logger.info("Migrated .env CalDAV config to calendar_sources")


def _split_vevents(ics_text: str) -> list[str]:
    """Split an ICS file into individual VCALENDAR blocks, one per VEVENT."""
    blocks: list[str] = []
    parts = ics_text.split("BEGIN:VEVENT")
    for part in parts[1:]:  # Skip everything before first VEVENT
        end_idx = part.find("END:VEVENT")
        if end_idx >= 0:
            vevent = part[: end_idx + len("END:VEVENT")]
            blocks.append(
                "BEGIN:VCALENDAR\nBEGIN:VEVENT" + vevent + "\nEND:VCALENDAR"
            )
    return blocks
