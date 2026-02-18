"""Runtime settings overrides backed by PostgreSQL."""

import json
import logging
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)

# Settings that can be changed at runtime (not credentials/infrastructure)
EDITABLE_SETTINGS = {
    "llm_base_url",
    "llm_model",
    "timezone",
    "log_level",
    "feature_whatsapp_auto_reply",
    "feature_tool_send_whatsapp",
    "feature_carddav_sync",
    "feature_caldav_sync",
}


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
        """Save a setting override. Raises ValueError for non-editable keys."""
        if key not in EDITABLE_SETTINGS:
            raise ValueError(f"Setting '{key}' is not editable at runtime")
        await self.pool.execute(
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
        await self.pool.execute(
            "DELETE FROM settings_overrides WHERE key = $1", key
        )
