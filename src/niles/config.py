"""Niles configuration via Pydantic Settings."""

import logging
import secrets

from pydantic import Field
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    # Logging
    log_level: str = "INFO"

    # Ollama (runs natively on the host for full GPU performance)
    llm_base_url: str = "http://host.docker.internal:11434/v1"
    llm_model: str = "llama3.1:8b"

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

    # Internal base URL for webhooks (Evolution API → Niles Core, Docker-internal)
    webhook_base_url: str = "http://niles_core:8000"

    # Niles API authentication
    niles_api_key: str = Field(
        default_factory=lambda: secrets.token_urlsafe(32),
    )

    # Session signing secret (separate from API key for security)
    session_secret: str = Field(
        default_factory=lambda: secrets.token_urlsafe(64),
    )

    # Base URL for OAuth redirect URI (e.g. https://niles.example.ts.net)
    # If empty, derived from request headers (less secure)
    base_url: str = ""

    # Timezone (used by CalDAV sync and calendar actions)
    timezone: str = "Europe/Vienna"

    # Weather (configured via Settings UI, stored as strings for env-var pass-through)
    weather_latitude: str = ""
    weather_longitude: str = ""
    weather_location_name: str = ""

    # Features
    feature_whatsapp_send_others: bool = True

    # CardDAV (configured via Settings UI)
    carddav_url: str = ""
    carddav_user: str = ""
    carddav_password: str = ""

    # CalDAV (mailbox.org)
    caldav_url: str = ""
    caldav_user: str = ""
    caldav_password: str = ""
    caldav_calendars: str = ""  # Comma-separated collection hrefs, empty = all

    # Google OAuth (optional -- Web-UI login)
    google_client_id: str = ""
    google_client_secret: str = ""
    google_allowed_emails: str = ""  # Comma-separated, empty = all allowed

    # Vikunja (Todo/Task Management) — tokens are per-user (auto-provisioned)
    vikunja_api_url: str = ""
    # Public URL for Vikunja web UI (shown as nav link, e.g. https://vikunja.niles.example.ts.net)
    vikunja_public_url: str = ""

    # Signal (signal-cli-rest-api)
    signal_api_url: str = "http://signal_api:8080"
    signal_phone_number: str = ""  # e.g. +436601234567
    feature_signal_send_others: bool = False

    # Web Search (SearXNG)
    feature_search: bool = False
    searxng_url: str = "http://searxng:8080"

    # Notion RAG (Knowledge Base)
    notion_token: str = ""
    notion_sync_interval: int = 30  # minutes between syncs
    notion_embedding_model: str = "nomic-embed-text-v2-moe"
    notion_chunk_size: int = 600  # characters per chunk
    notion_chunk_overlap: int = 100  # overlap between chunks
    notion_similarity_threshold: float = 0.3  # minimum cosine similarity
    notion_summary_model: str = ""  # empty = use llm_model
    notion_summary_max_input: int = 4000  # max chars sent to LLM for summarization
    notion_summary_max_tokens: int = 200  # max LLM output tokens for summary
    feature_notion: bool = False

    # Briefing / Digest
    feature_briefing_daily: bool = False
    feature_briefing_weekly: bool = False
    briefing_daily_time: str = "07:30"  # HH:MM, Mo-Fr
    briefing_weekly_time: str = "07:15"  # HH:MM, Montag
    briefing_channel: str = "whatsapp"  # whatsapp | signal | both

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
