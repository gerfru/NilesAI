"""Per-user CardDAV source management (CRUD + sync).

Mirrors the CalendarSourceManager pattern for calendar_sources.
Each user has their own CardDAV sources with encrypted credentials.
"""

import logging
from urllib.parse import urlparse

import asyncpg
import httpx

from ..crypto import FieldEncryptor
from ..network import is_private_host
from ..sync.carddav import CardDAVSync

logger = logging.getLogger(__name__)


class CardDAVSourceManager:
    """Manages per-user CardDAV contact sources.

    Responsibilities:
    - CRUD for carddav_sources table
    - Auto-migration of legacy settings_overrides on first startup
    - Sync orchestration across all sources
    - Orphan source claiming for multi-user migration
    """

    def __init__(
        self,
        pool: asyncpg.Pool,
        *,
        encryptor: FieldEncryptor | None = None,
        client: httpx.AsyncClient,
    ):
        self.pool = pool
        self._enc = encryptor
        self._client = client

    async def initialize(self) -> None:
        """Run post-migration business logic."""
        await self._migrate_settings_source()
        logger.info("CardDAV source manager initialized")

    # --- CRUD ---

    async def add_source(
        self,
        url: str,
        auth_user: str,
        auth_password: str,
        user_id: int | None = None,
        name: str = "",
    ) -> dict:
        """Add a new CardDAV source. Returns the created row."""
        if not url.startswith("https://"):
            raise ValueError("Nur HTTPS-URLs sind erlaubt")
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
        if is_private_host(hostname):
            raise ValueError("Interne Adressen sind nicht erlaubt")
        if len(url) > 2048:
            raise ValueError("URL ist zu lang (max 2048 Zeichen)")
        if len(name) > 200:
            raise ValueError("Name ist zu lang (max 200 Zeichen)")

        if not name.strip():
            name = url.split("//", 1)[-1].split("/")[0][:80]

        enc_password = self._enc.encrypt(auth_password) if self._enc and auth_password else auth_password
        row = await self.pool.fetchrow(
            """
            INSERT INTO carddav_sources
                (name, url, auth_user, auth_password, user_id)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id, name, url, auth_user, user_id,
                      last_synced, last_error, created_at
            """,
            name.strip(),
            url.strip(),
            auth_user.strip(),
            enc_password,
            user_id,
        )
        logger.info("Added CardDAV source: %s", name)
        return dict(row)

    async def remove_source(self, source_id: int, user_id: int | None = None) -> bool:
        """Remove a CardDAV source. Contacts are CASCADE-deleted."""
        result = await self.pool.execute(
            "DELETE FROM carddav_sources WHERE id = $1 AND ($2::integer IS NULL OR user_id = $2)",
            source_id,
            user_id,
        )
        removed = result == "DELETE 1"
        if removed:
            logger.info("Removed CardDAV source %d", source_id)
        return removed

    async def get_sources(self, *, user_id: int | None = None) -> list[dict]:
        """List CardDAV sources, optionally filtered by user_id."""
        rows = await self.pool.fetch(
            """
            SELECT id, name, url, auth_user, user_id,
                   last_synced, last_error, created_at
            FROM carddav_sources
            WHERE ($1::integer IS NULL OR user_id = $1)
            ORDER BY created_at
            """,
            user_id,
        )
        return [dict(r) for r in rows]

    async def claim_orphan_sources(self, user_id: int) -> int:
        """Assign orphan sources and their contacts to the given user."""
        result = await self.pool.execute(
            "UPDATE carddav_sources SET user_id = $1 WHERE user_id IS NULL",
            user_id,
        )
        source_count = int(result.split()[-1])

        contact_result = await self.pool.execute(
            "UPDATE contacts SET user_id = $1 WHERE user_id IS NULL",
            user_id,
        )
        contact_count = int(contact_result.split()[-1])

        if source_count > 0 or contact_count > 0:
            logger.info(
                "Claimed %d orphan CardDAV source(s) and %d contact(s) for user %d",
                source_count,
                contact_count,
                user_id,
            )
        return source_count

    async def test_connection(self, url: str, auth_user: str, auth_password: str) -> tuple[bool, str]:
        """Test a CardDAV connection before saving."""
        sync = CardDAVSync(
            self.pool,
            carddav_url=url,
            auth=(auth_user, auth_password),
            client=self._client,
        )
        return await sync.test_connection()

    # --- Sync ---

    async def sync_all(self) -> int:
        """Sync all CardDAV sources. Returns total contacts synced."""
        sources = await self.pool.fetch("SELECT id, url, auth_user, auth_password, user_id FROM carddav_sources")
        total = 0
        for src in sources:
            try:
                count = await self._sync_one(dict(src))
                total += count
            except Exception:
                logger.exception("CardDAV sync failed for source %d", src["id"])
        logger.info(
            "CardDAV sync complete: %d contacts from %d sources",
            total,
            len(sources),
        )
        return total

    async def sync_source(self, source_id: int, user_id: int | None = None) -> int | None:
        """Sync a single source by ID. Returns contact count or None."""
        row = await self.pool.fetchrow(
            """
            SELECT id, url, auth_user, auth_password, user_id
            FROM carddav_sources
            WHERE id = $1 AND ($2::integer IS NULL OR user_id = $2)
            """,
            source_id,
            user_id,
        )
        if not row:
            return None
        return await self._sync_one(dict(row))

    async def _sync_one(self, src: dict) -> int:
        """Sync a single source row."""
        password = src["auth_password"] or ""
        if self._enc and password:
            password = self._enc.decrypt(password)

        sync = CardDAVSync(
            self.pool,
            carddav_url=src["url"],
            auth=(src["auth_user"], password),
            user_id=src["user_id"],
            source_id=src["id"],
            client=self._client,
        )
        try:
            count = await sync.sync_contacts()
            await self.pool.execute(
                "UPDATE carddav_sources SET last_synced = NOW(), last_error = NULL WHERE id = $1",
                src["id"],
            )
            return count
        except Exception as exc:
            await self.pool.execute(
                "UPDATE carddav_sources SET last_error = $1 WHERE id = $2",
                str(exc)[:500],
                src["id"],
            )
            raise

    # --- Legacy migration ---

    async def _migrate_settings_source(self) -> None:
        """Auto-migrate legacy settings_overrides CardDAV config.

        If carddav_sources is empty and settings_overrides contains
        carddav_url, create an orphan source row (user_id=NULL) that
        will be claimed by the first user to visit settings.
        """
        count = await self.pool.fetchval("SELECT COUNT(*) FROM carddav_sources")
        if count > 0:
            return

        row = await self.pool.fetchrow("SELECT value FROM settings_overrides WHERE key = 'carddav_url'")
        if not row:
            return

        import json

        url = json.loads(row["value"])
        if not url:
            return

        user_row = await self.pool.fetchrow("SELECT value FROM settings_overrides WHERE key = 'carddav_user'")
        pass_row = await self.pool.fetchrow("SELECT value FROM settings_overrides WHERE key = 'carddav_password'")

        auth_user = json.loads(user_row["value"]) if user_row else ""
        auth_password = pass_row["value"] if pass_row else ""
        # auth_password may be JSON-encoded or already encrypted
        if auth_password and not auth_password.startswith("v1:"):
            try:
                auth_password = json.loads(auth_password)
            except json.JSONDecodeError, TypeError:
                pass

        # Re-encrypt with FieldEncryptor if available
        enc_password = self._enc.encrypt(auth_password) if self._enc and auth_password else auth_password

        await self.pool.execute(
            """
            INSERT INTO carddav_sources (name, url, auth_user, auth_password)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT DO NOTHING
            """,
            "CardDAV (migriert)",
            url,
            auth_user,
            enc_password,
        )
        logger.info("Migrated legacy CardDAV config to carddav_sources table")
