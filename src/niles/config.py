"""Niles configuration via Pydantic Settings."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # LM Studio
    llm_base_url: str = "http://host.docker.internal:1234/v1"
    llm_model: str = "qwen2.5-coder-7b-instruct-mlx"

    # PostgreSQL (bestehende Verbindung)
    postgres_host: str = "evolution_postgres"
    postgres_port: int = 5432
    postgres_db: str = "evolution_db"
    postgres_user: str = "evolution"
    postgres_password: str  # Via POSTGRES_PASSWORD or EVOLUTION_POSTGRES_PASSWORD

    # Evolution API (WhatsApp)
    evolution_api_url: str = "http://evolution_api:8080"
    evolution_api_key: str  # Via EVOLUTION_API_KEY
    evolution_instance: str = "niles-whatsapp"

    # CardDAV (mailbox.org)
    carddav_url: str = "https://dav.mailbox.org/carddav/32"
    carddav_user: str = ""  # Via CARDDAV_USER
    carddav_password: str = ""  # Via CARDDAV_PASSWORD

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "env_prefix": "",
        "extra": "ignore",
    }
