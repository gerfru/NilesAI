"""Niles configuration via Pydantic Settings."""

from pydantic import Field
from pydantic_settings import BaseSettings


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

    # Features
    feature_whatsapp_auto_reply: bool = False
    feature_tool_send_whatsapp: bool = True

    # CardDAV (mailbox.org)
    carddav_url: str = "https://dav.mailbox.org/carddav/32"
    carddav_user: str = ""
    carddav_password: str = ""

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }
