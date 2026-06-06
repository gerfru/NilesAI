"""Runtime settings overrides backed by PostgreSQL.

NOTE: JSON serialisation in get_all/set is synchronous (json.loads/dumps).
This is acceptable for the small payloads involved; switch to an async
JSON library only if profiling shows a bottleneck.
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import asyncpg

if TYPE_CHECKING:
    from .crypto import FieldEncryptor

logger = logging.getLogger(__name__)

# Keys whose values are encrypted at rest when CREDENTIAL_ENCRYPTION_KEY is set.
_ENCRYPTED_KEYS = {"notion_token", "carddav_password"}

# Settings that can be changed at runtime via the Settings UI.
# CardDAV credentials are included here (analogous to calendar_sources.auth_password
# which is already stored in the DB by CalendarSourceManager).
# NOTE: carddav_url/user/password are individually settable via the generic
# POST /api/settings/{key} endpoint, but should only be changed atomically
# through the dedicated contacts_connect flow in web.py. A direct POST to
# a single key would leave credentials in a transiently inconsistent state.
EDITABLE_SETTINGS = {
    "llm_base_url",
    "llm_model",
    "timezone",
    "log_level",
    "feature_whatsapp_send_others",
    "caldav_calendars",
    "carddav_url",
    "carddav_user",
    "carddav_password",
    "feature_signal_send_others",
    "signal_api_url",
    "signal_phone_number",
    # signal_disabled is a runtime-only flag (not a field on the Settings
    # model). It suppresses Signal auto-discovery after intentional disconnect
    # and is persisted here so the flag survives container restarts.
    "signal_disabled",
    "feature_briefing_daily",
    "feature_briefing_weekly",
    "briefing_daily_time",
    "briefing_weekly_time",
    "briefing_channel",
    "weather_latitude",
    "weather_longitude",
    "weather_location_name",
    "feature_search",
    "searxng_url",
    "feature_notion",
    "notion_token",
    "notion_sync_interval",
    "notion_embedding_model",
    "notion_chunk_size",
    "notion_chunk_overlap",
    "notion_similarity_threshold",
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

    def __init__(self, pool: asyncpg.Pool, *, encryptor: FieldEncryptor | None = None):
        self.pool = pool
        self._enc = encryptor

    async def get_all(self) -> dict[str, Any]:
        """Load all persisted overrides (decrypting sensitive keys)."""
        rows = await self.pool.fetch("SELECT key, value FROM settings_overrides")
        result = {}
        for row in rows:
            try:
                val = json.loads(row["value"])
                if self._enc and row["key"] in _ENCRYPTED_KEYS and isinstance(val, str):
                    val = self._enc.decrypt(val)
                result[row["key"]] = val
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

        # Validate briefing time format (HH:MM, 00:00–23:59)
        if key in ("briefing_daily_time", "briefing_weekly_time") and isinstance(
            value, str
        ):
            if not re.match(r"^(?:[01]\d|2[0-3]):[0-5]\d$", value):
                raise ValueError(
                    f"Invalid time format: '{value}' (expected HH:MM, 00:00–23:59)"
                )

        # Validate weather coordinates
        if key == "weather_latitude" and isinstance(value, str) and value:
            try:
                lat = float(value)
            except ValueError:
                raise ValueError(
                    f"Invalid latitude: '{value}' (must be a number)"
                ) from None
            if not -90 <= lat <= 90:
                raise ValueError(
                    f"Invalid latitude: {lat} (must be between -90 and 90)"
                )
        # Validate URL format for URL-type settings
        if key == "searxng_url" and isinstance(value, str) and value:
            parsed = urlparse(value)
            if parsed.scheme not in ("http", "https") or not parsed.hostname:
                raise ValueError(
                    f"Invalid URL: '{value}' (must be http:// or https://)"
                )

        if key == "weather_longitude" and isinstance(value, str) and value:
            try:
                lon = float(value)
            except ValueError:
                raise ValueError(
                    f"Invalid longitude: '{value}' (must be a number)"
                ) from None
            if not -180 <= lon <= 180:
                raise ValueError(
                    f"Invalid longitude: {lon} (must be between -180 and 180)"
                )

        store_value = value
        if self._enc and key in _ENCRYPTED_KEYS and isinstance(store_value, str):
            store_value = self._enc.encrypt(store_value)

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
                    json.dumps(store_value, ensure_ascii=False),
                )

    async def delete(self, key: str) -> None:
        """Remove a setting override (revert to env/default)."""
        _validate_key(key)
        await self.pool.execute("DELETE FROM settings_overrides WHERE key = $1", key)
