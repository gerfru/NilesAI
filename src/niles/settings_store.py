"""Runtime settings overrides backed by PostgreSQL.

NOTE: JSON serialisation in get_all/set is synchronous (json.loads/dumps).
This is acceptable for the small payloads involved; switch to an async
JSON library only if profiling shows a bottleneck.
"""

import json
import logging
import re
from typing import Any
from zoneinfo import ZoneInfo

import asyncpg

logger = logging.getLogger(__name__)

# Settings that can be changed at runtime via the Settings UI.
# CardDAV credentials are included here (analogous to calendar_sources.auth_password
# which is already stored in the DB by CalendarSourceManager).
EDITABLE_SETTINGS = {
    "llm_base_url",
    "llm_model",
    "timezone",
    "log_level",
    "feature_whatsapp_auto_reply",
    "feature_tool_send_whatsapp",
    "feature_carddav_sync",
    "feature_caldav_sync",
    "caldav_calendars",
    "carddav_url",
    "carddav_user",
    "carddav_password",
}

_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


def _validate_key(key: str) -> None:
    """Validate settings key format (lowercase alphanumeric + underscore, max 64 chars)."""
    if not _KEY_PATTERN.match(key):
        raise ValueError(
            f"Invalid settings key format: '{key}' "
            "(must be lowercase alphanumeric/underscore, 2-64 chars)"
        )


class SettingsStore:
    """Persist runtime setting overrides in PostgreSQL."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def initialize(self) -> None:
        """Create settings_overrides table if it doesn't exist."""
        await self.pool.execute("""
            CREATE TABLE IF NOT EXISTS settings_overrides (
                key TEXT PRIMARY KEY,
                value JSONB NOT NULL,
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)
        logger.info("Settings store initialized")

    async def get_all(self) -> dict[str, Any]:
        """Load all persisted overrides."""
        rows = await self.pool.fetch(
            "SELECT key, value FROM settings_overrides"
        )
        result = {}
        for row in rows:
            try:
                result[row["key"]] = json.loads(row["value"])
            except (json.JSONDecodeError, TypeError):
                logger.warning("Corrupted settings override: %s", row["key"])
        return result

    async def set(self, key: str, value: Any) -> None:
        """Save a setting override. Raises ValueError for invalid/non-editable keys."""
        _validate_key(key)
        if key not in EDITABLE_SETTINGS:
            raise ValueError(f"Setting '{key}' is not editable at runtime")

        # Value length guard for string settings
        if isinstance(value, str) and len(value) > 4096:
            raise ValueError(
                f"Value for '{key}' exceeds maximum length of 4096 characters"
            )

        # Validate timezone is a valid IANA identifier
        if key == "timezone" and isinstance(value, str):
            try:
                ZoneInfo(value)
            except (KeyError, ValueError) as exc:
                raise ValueError(
                    f"Invalid timezone: '{value}' is not a valid IANA timezone"
                ) from exc

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO settings_overrides (key, value, updated_at)
                    VALUES ($1, $2::jsonb, NOW())
                    ON CONFLICT (key) DO UPDATE
                    SET value = $2::jsonb, updated_at = NOW()
                    """,
                    key,
                    json.dumps(value, ensure_ascii=False),
                )

    async def delete(self, key: str) -> None:
        """Remove a setting override (revert to env/default)."""
        _validate_key(key)
        await self.pool.execute(
            "DELETE FROM settings_overrides WHERE key = $1", key
        )
