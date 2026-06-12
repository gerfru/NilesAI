"""Calendar source manager – unified CRUD, sync, and .env migration."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import asyncpg
import httpx

from niles.http_retry import retry_http
from niles.network import is_private_host

if TYPE_CHECKING:
    from niles.crypto import FieldEncryptor

from .caldav import (
    CalDAVSync,
    _SYNC_DAYS_FUTURE,
    _SYNC_DAYS_PAST,
    cleanup_recurring_occurrences,
    upsert_event,
)
from .ical_parser import expand_recurring_event, parse_icalendar

logger = logging.getLogger(__name__)

_MAX_ICS_SIZE = 5 * 1024 * 1024  # 5 MB limit per ICS file
_ICS_TIMEOUT = 60  # seconds

# Strip credentials from URLs in error messages (user:pass@host → ***@host)
_CREDENTIAL_RE = re.compile(r"://[^@/\s]+@")


class CalendarSourceManager:
    """Manages calendar sources of all types (ICS, CalDAV).

    Responsibilities:
    - CRUD for calendar_sources table
    - Schema migrations (calendar_sources + events.source_id)
    - Auto-migration of .env CalDAV config on first startup
    - Sync orchestration across all enabled sources
    - Event creation on writable sources
    """

    def __init__(
        self,
        pool: asyncpg.Pool,
        settings,
        client: httpx.AsyncClient,
        *,
        encryptor: FieldEncryptor | None = None,
    ):
        self.pool = pool
        self.settings = settings
        self._client = client
        self._enc = encryptor

    async def initialize(self) -> None:
        """Run post-migration business logic.

        Schema creation is handled by Alembic (see alembic/versions/).
        """
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
        user_id: int | None = None,
    ) -> dict:
        """Add a new calendar source. Returns the created row."""
        if not url.startswith("https://"):
            raise ValueError("Nur HTTPS-URLs sind erlaubt")
        # SSRF protection: block private/internal IPs
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
        if is_private_host(hostname):
            raise ValueError("Interne Adressen sind nicht erlaubt")
        # Strip embedded credentials from URL
        if parsed.username or parsed.password:
            url = parsed._replace(netloc=(parsed.hostname or "") + (f":{parsed.port}" if parsed.port else "")).geturl()
        if len(url) > 2048:
            raise ValueError("URL ist zu lang (max 2048 Zeichen)")
        if len(name) > 200:
            raise ValueError("Name ist zu lang (max 200 Zeichen)")
        if source_type not in ("ics", "caldav"):
            raise ValueError(f"Unbekannter Typ: {source_type}")

        enc_password = self._enc.encrypt(auth_password) if self._enc and auth_password else auth_password
        row = await self.pool.fetchrow(
            """
            INSERT INTO calendar_sources
                (name, url, source_type, writable, auth_user, auth_password, user_id)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING id, name, url, source_type, writable, enabled,
                      last_synced, last_error, created_at, user_id
            """,
            name,
            url,
            source_type,
            writable,
            auth_user,
            enc_password,
            user_id,
        )
        logger.info("Added calendar source: %s (%s)", name, source_type)
        return dict(row)

    async def remove_source(self, source_id: int, user_id: int | None = None) -> bool:
        """Remove a calendar source. Events are CASCADE-deleted.

        When ``user_id`` is provided, only sources owned by that user can be
        deleted (authorization check).  ``user_id=None`` bypasses the check
        and is reserved for admin/system operations.
        """
        result = await self.pool.execute(
            "DELETE FROM calendar_sources WHERE id = $1 AND ($2::integer IS NULL OR user_id = $2)",
            source_id,
            user_id,
        )
        removed = result == "DELETE 1"
        if removed:
            logger.info("Removed calendar source %d", source_id)
        return removed

    async def get_sources(
        self,
        *,
        user_id: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """List calendar sources, optionally filtered by user_id."""
        rows = await self.pool.fetch(
            """
            SELECT id, name, url, source_type, writable, enabled,
                   last_synced, last_error, created_at, user_id
            FROM calendar_sources
            WHERE ($3::integer IS NULL OR user_id = $3)
            ORDER BY created_at
            LIMIT $1 OFFSET $2
            """,
            limit,
            offset,
            user_id,
        )
        return [dict(r) for r in rows]

    async def get_writable_source(self, user_id: int | None = None) -> dict | None:
        """Return the first enabled, writable calendar source for the user.

        ``user_id=None`` skips the ownership filter (admin/system use).
        """
        row = await self.pool.fetchrow(
            """
            SELECT id, name, url, source_type, auth_user, auth_password
            FROM calendar_sources
            WHERE writable = TRUE AND enabled = TRUE
              AND ($1::integer IS NULL OR user_id = $1)
            ORDER BY created_at
            LIMIT 1
            """,
            user_id,
        )
        return dict(row) if row else None

    async def claim_orphan_sources(self, user_id: int) -> int:
        """Assign orphan sources (user_id IS NULL) to the given user.

        Called when a user first visits calendar settings, so .env-migrated
        sources become visible. Returns the number of claimed sources.

        Note: If two users visit settings concurrently, both issue this UPDATE.
        The first to commit wins all orphans (atomic, no data corruption).
        This is acceptable for the single-admin scenario; multi-admin setups
        should assign sources explicitly via the admin UI.
        """
        result = await self.pool.execute(
            "UPDATE calendar_sources SET user_id = $1 WHERE user_id IS NULL",
            user_id,
        )
        count = int(result.split()[-1])  # "UPDATE N"
        if count > 0:
            logger.info("Claimed %d orphan calendar source(s) for user %d", count, user_id)
        return count

    # --- Sync ---

    async def sync_all(self) -> int:
        """Sync all enabled sources across all users. Returns total events synced.

        This is a system-level background job (cron) — intentionally not
        filtered by user_id so that all users' calendars stay up to date.
        """
        sources = await self.pool.fetch(
            """
            SELECT id, name, url, source_type, auth_user, auth_password
            FROM calendar_sources WHERE enabled = TRUE
            """
        )
        total = 0
        for src in sources:
            src = dict(src)
            try:
                if src["source_type"] == "ics":
                    count = await self._sync_ics(src)
                elif src["source_type"] == "caldav":
                    count = await self._sync_caldav(src)
                else:
                    continue
                total += count
            except Exception:
                logger.exception(
                    "Sync failed for source %d (%s)",
                    src["id"],
                    src["name"],
                )
        logger.info("Calendar sync complete: %d events from %d sources", total, len(sources))
        return total

    async def sync_source(self, source_id: int, user_id: int | None = None) -> int | None:
        """Sync a single source by ID. Returns event count, or None if not found.

        ``user_id=None`` skips the ownership filter (admin/system use).
        """
        row = await self.pool.fetchrow(
            """
            SELECT id, name, url, source_type, auth_user, auth_password
            FROM calendar_sources
            WHERE id = $1 AND enabled = TRUE
              AND ($2::integer IS NULL OR user_id = $2)
            """,
            source_id,
            user_id,
        )
        if not row:
            return None
        src = dict(row)
        if src["source_type"] == "ics":
            return await self._sync_ics(src)
        if src["source_type"] == "caldav":
            return await self._sync_caldav(src)
        return 0

    @retry_http
    async def _fetch_ics(self, url: str) -> str:
        """HTTP GET for ICS file (retryable on transient failures)."""
        response = await self._client.get(
            url,
            timeout=_ICS_TIMEOUT,
            follow_redirects=True,
        )
        response.raise_for_status()
        if len(response.content) > _MAX_ICS_SIZE:
            raise ValueError(f"ICS file too large: {len(response.content)} bytes")
        return response.text

    async def _sync_ics(self, source: dict) -> int:
        """Sync an ICS subscription: HTTP GET, parse, upsert.

        Recurring events (RRULE) are expanded into individual occurrences
        within a window of 30 days past to 365 days future.
        """
        source_id = source["id"]
        url = source["url"]
        logger.info("Syncing ICS source '%s' from %s", source["name"], url)

        try:
            ics_text = await self._fetch_ics(url)
        except Exception as exc:
            await self._set_error(source_id, str(exc))
            raise
        count = 0

        now = datetime.now(timezone.utc)
        window_start = now - timedelta(days=_SYNC_DAYS_PAST)
        window_end = now + timedelta(days=_SYNC_DAYS_FUTURE)

        for vevent_text in _split_vevents(ics_text):
            event = parse_icalendar(vevent_text, url)
            if event:
                # Prefix UID with source_id to avoid collision with CalDAV UIDs
                event["caldav_uid"] = f"ics-{source_id}-{event['caldav_uid']}"
                expanded = expand_recurring_event(event, window_start, window_end)
                if event.get("rrule"):
                    await cleanup_recurring_occurrences(
                        self.pool,
                        event["caldav_uid"],
                        source_id,
                    )
                for occ in expanded:
                    await self._upsert_event(occ, source_id)
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
            client=self._client,
        )
        try:
            count = await sync.sync_events()
            await self._set_synced(source["id"])
            return count
        except Exception as exc:
            await self._set_error(source["id"], str(exc))
            raise

    def _build_auth(self, source: dict) -> httpx.Auth | None:
        """Build httpx auth for a source (decrypts password). Returns None for ICS."""
        if source["source_type"] == "caldav":
            password = source["auth_password"] or ""
            if self._enc and password:
                password = self._enc.decrypt(password)
            return httpx.BasicAuth(source["auth_user"] or "", password)
        return None

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
        """Create an event on a writable CalDAV source."""
        auth = self._build_auth(source)
        sync = CalDAVSync(
            pool=self.pool,
            caldav_url=source["url"],
            auth=auth,
            timezone=self.settings.timezone,
            source_id=source["id"],
            client=self._client,
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
        await upsert_event(self.pool, event, source_id)

    async def _set_synced(self, source_id: int) -> None:
        """Update last_synced timestamp, clear error."""
        await self.pool.execute(
            "UPDATE calendar_sources SET last_synced = NOW(), last_error = NULL WHERE id = $1",
            source_id,
        )

    async def _set_error(self, source_id: int, error_msg: str) -> None:
        """Store sync error message (credentials stripped)."""
        sanitized = _CREDENTIAL_RE.sub("://***@", error_msg)[:500]
        await self.pool.execute(
            "UPDATE calendar_sources SET last_error = $1 WHERE id = $2",
            sanitized,
            source_id,
        )

    async def _migrate_env_source(self) -> None:
        """Auto-migrate .env CalDAV config to calendar_sources on first startup."""
        count = await self.pool.fetchval("SELECT COUNT(*) FROM calendar_sources")
        if count > 0:
            return  # Already have sources

        cfg = self.settings
        if not cfg.caldav_url or not cfg.caldav_user:
            return  # Nothing to migrate

        host = urlparse(cfg.caldav_url).hostname or "CalDAV"
        await self.add_source(
            name=f"{host} (migriert)",
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
            blocks.append("BEGIN:VCALENDAR\nBEGIN:VEVENT" + vevent + "\nEND:VCALENDAR")
    return blocks
