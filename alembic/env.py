"""Alembic environment configuration.

Constructs DATABASE_URL from the same environment variables used by
niles.config.Settings (EVOLUTION_POSTGRES_PASSWORD, POSTGRES_HOST, etc.).
"""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def get_database_url() -> str:
    """Build PostgreSQL URL from environment variables."""
    password = os.environ.get("EVOLUTION_POSTGRES_PASSWORD", "")
    if not password:
        raise RuntimeError(
            "EVOLUTION_POSTGRES_PASSWORD environment variable is not set. Set it before running Alembic migrations."
        )
    host = os.environ.get("POSTGRES_HOST", "evolution_postgres")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db = os.environ.get("POSTGRES_DB", "evolution_db")
    user = os.environ.get("POSTGRES_USER", "evolution")
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


def _resolve_url() -> str:
    """Get database URL from config or environment."""
    url = config.get_main_option("sqlalchemy.url")
    if url:
        return url
    return get_database_url()


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (generate SQL script)."""
    url = _resolve_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live database."""
    engine = create_engine(_resolve_url())
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                transaction_per_migration=True,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
