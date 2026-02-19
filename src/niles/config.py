"""Niles configuration via Pydantic Settings."""

import logging
import secrets

from pydantic import Field
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    # Logging
    log_level: str = "INFO"

    # LM Studio
    llm_base_url: str = "http://host.docker.internal:1234/v1"
    llm_model: str = "qwen2.5-coder-7b-instruct-mlx"

    # PostgreSQL (bestehende Verbindung)
    postgres_host: str = "evolution_postgres"
    postgres_port: int = 5432
    postgres_db: str = "evolution_db"
    postgres_user: str = "evolution"
    postgres_password: str = Field(
        validation_alias="EVOLUTION_POSTGRES_PASSWORD",
    )

    # Evolution API (WhatsApp)
    evolution_api_url: str = "http://evolution_api:8080"
    evolution_api_key: str  # Via EVOLUTION_API_KEY
    evolution_instance: str = "niles-whatsapp"

    # Niles API authentication
    niles_api_key: str = Field(
        default_factory=lambda: secrets.token_urlsafe(32),
    )

    # Session signing secret (separate from API key for security)
    session_secret: str = Field(
        default_factory=lambda: secrets.token_urlsafe(64),
    )

    # Base URL for OAuth redirect URI (e.g. https://niles.tail1d4a0f.ts.net)
    # If empty, derived from request headers (less secure)
    base_url: str = ""

    # Timezone (used by CalDAV sync and calendar actions)
    timezone: str = "Europe/Vienna"

    # Features
    feature_whatsapp_auto_reply: bool = False
    feature_tool_send_whatsapp: bool = True
    feature_carddav_sync: bool = False
    feature_caldav_sync: bool = False

    # CardDAV (mailbox.org)
    carddav_url: str = "https://dav.mailbox.org/carddav/32"
    carddav_user: str = ""
    carddav_password: str = ""

    # CalDAV (mailbox.org)
    caldav_url: str = "https://dav.mailbox.org/caldav/"
    caldav_user: str = ""
    caldav_password: str = ""

    # Google OAuth (optional -- Web-UI login)
    google_client_id: str = ""
    google_client_secret: str = ""
    google_allowed_emails: str = ""  # Comma-separated, empty = all allowed

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


def apply_overrides(settings: Settings, overrides: dict) -> Settings:
    """Apply runtime overrides, returning a new Settings instance via model_copy."""
    valid = {k: v for k, v in overrides.items() if hasattr(settings, k)}
    if not valid:
        return settings
    for k in valid:
        logger.debug("Applied setting override: %s", k)
    return settings.model_copy(update=valid)
