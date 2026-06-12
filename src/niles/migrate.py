# SPDX-License-Identifier: AGPL-3.0-only
"""Database migration bootstrap — runs before uvicorn.

Detects whether the database is a fresh install or an existing one
(tables present but no alembic_version) and acts accordingly:

- Fresh DB: ``alembic upgrade head`` creates all tables.
- Existing DB without alembic_version: stamp to current head, then upgrade.
- Already managed DB: ``alembic upgrade head`` applies pending migrations.

Usage::

    python -m niles.migrate
"""

import logging
import os
import sys
import time

logging.basicConfig(level=logging.INFO, format="%(levelname)-5s %(message)s")
logger = logging.getLogger("niles.migrate")

# Maximum seconds to wait for PostgreSQL to accept connections
_PG_WAIT_TIMEOUT = int(os.environ.get("PG_WAIT_TIMEOUT", "60"))


def _get_database_url() -> str:
    """Build PostgreSQL URL from environment variables."""
    password = os.environ.get("EVOLUTION_POSTGRES_PASSWORD", "")
    if not password:
        logger.error("EVOLUTION_POSTGRES_PASSWORD not set")
        sys.exit(1)
    host = os.environ.get("POSTGRES_HOST", "evolution_postgres")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db = os.environ.get("POSTGRES_DB", "evolution_db")
    user = os.environ.get("POSTGRES_USER", "evolution")
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


def _wait_for_postgres(engine) -> None:
    """Block until PostgreSQL accepts connections."""
    from sqlalchemy import text

    deadline = time.monotonic() + _PG_WAIT_TIMEOUT
    while True:
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return
        except Exception:
            if time.monotonic() > deadline:
                logger.error("PostgreSQL not reachable after %ds", _PG_WAIT_TIMEOUT)
                sys.exit(1)
            time.sleep(1)


def _table_exists(engine, table_name: str) -> bool:
    """Check whether a table exists in the public schema."""
    from sqlalchemy import text

    with engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT EXISTS("
                "  SELECT 1 FROM information_schema.tables"
                "  WHERE table_schema = 'public' AND table_name = :name"
                ")"
            ),
            {"name": table_name},
        )
        return result.scalar()


def main() -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine

    url = _get_database_url()
    engine = create_engine(url)

    logger.info("Waiting for PostgreSQL...")
    _wait_for_postgres(engine)
    logger.info("PostgreSQL ready")

    # Determine database state
    has_alembic = _table_exists(engine, "alembic_version")
    has_users = _table_exists(engine, "users")

    # Alembic config — point to project root.
    # When running from source (__file__ in src/niles/), __file__-based resolution
    # works. When installed as a package (venv site-packages), fall back to CWD
    # which is /app in Docker (set via WORKDIR).
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    ini_path = os.path.join(project_root, "alembic.ini")
    if not os.path.exists(ini_path):
        project_root = os.getcwd()
        ini_path = os.path.join(project_root, "alembic.ini")
    cfg = Config(ini_path)
    cfg.set_main_option("script_location", os.path.join(project_root, "alembic"))
    # Pass URL to env.py (overrides get_database_url if set)
    cfg.set_main_option("sqlalchemy.url", url)

    if has_users and not has_alembic:
        # Existing installation — tables already exist.
        # Stamp baseline (001), then upgrade to apply data migrations (e.g. 002)
        # which are idempotent and safe to re-run on existing data.
        logger.info("Existing installation detected — stamping baseline, then upgrading")
        command.stamp(cfg, "001")
        command.upgrade(cfg, "head")
        logger.info("Stamped + upgraded to head")
    else:
        # Fresh install or already managed — apply pending migrations
        logger.info("Running alembic upgrade head...")
        command.upgrade(cfg, "head")
        logger.info("Migrations applied")

    engine.dispose()


if __name__ == "__main__":
    main()
