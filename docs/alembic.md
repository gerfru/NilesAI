# Niles AI — Alembic Migration Implementation Spec

> **Version:** 1.0  
> **Date:** 2026-02-27  
> **Author:** System Architect  
> **Scope:** Database schema management migration from ad-hoc `CREATE TABLE IF NOT EXISTS` to Alembic version control  
> **Prerequisite:** Niles-Core-Spec v7.3, PostgreSQL 15, asyncpg, Python >= 3.11

---

## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [Architecture Decision](#2-architecture-decision)
3. [Current State Analysis](#3-current-state-analysis)
4. [Target Architecture](#4-target-architecture)
5. [Implementation Plan](#5-implementation-plan)
6. [Migration Baseline](#6-migration-baseline)
7. [Store Refactoring](#7-store-refactoring)
8. [Runtime Integration](#8-runtime-integration)
9. [Developer Workflow](#9-developer-workflow)
10. [Rollback Strategy](#10-rollback-strategy)
11. [Testing Strategy](#11-testing-strategy)
12. [File Changes Summary](#12-file-changes-summary)
13. [Verification Checklist](#13-verification-checklist)

---

## 1. Problem Statement

### Current Situation

Schema creation is scattered across 7 Store classes, each running `CREATE TABLE IF NOT EXISTS` and `ALTER TABLE ADD COLUMN IF NOT EXISTS` during application startup:

| Store Class | Tables Created | Ad-hoc Migrations |
|-------------|---------------|-------------------|
| `memory/store.py` | `memory` | — |
| `memory/history.py` | `conversations` | — |
| `user_store.py` | `users` | `ALTER TABLE ADD COLUMN IF NOT EXISTS` × 3 (password_hash, auth_method, is_admin) |
| `whatsapp_store.py` | `whatsapp_sessions` | — |
| `vikunja_store.py` | `vikunja_credentials` | — |
| `settings_store.py` | `settings_overrides` | — |
| `signal_store.py` | `signal_messages` | — |
| `sync/carddav.py` | `contacts`, `contact_phones` | Phone migration from legacy columns |
| `sync/caldav.py` | `events` | — |
| `sync/manager.py` | `calendar_sources`, `events` (ensures existence) | `ALTER TABLE ADD COLUMN IF NOT EXISTS` × 2 (source_id, transp) |

### Why This Is a Problem

1. **No version tracking.** There is no way to know which schema version a customer's database is at.
2. **No rollback.** If a schema change breaks something, there is no `downgrade` path.
3. **Hidden dependencies.** Table creation order matters (FK constraints), but the order is implicit in `main.py` lifespan.
4. **Duplicate schema definitions.** `events` table is created in both `caldav.py` and `manager.py`.
5. **Silent failures.** `ADD COLUMN IF NOT EXISTS` succeeds even if the column already has a different type — no validation.
6. **Customer updates.** Without migrations, every schema change for a new Niles version requires a manual SQL script or risks data loss.

---

## 2. Architecture Decision

### Choice: Alembic (Standalone, Sync Mode)

**Why Alembic:**
- De facto standard for Python/SQLAlchemy database migrations
- Supports raw SQL (no SQLAlchemy ORM required)
- Version history table (`alembic_version`) tracks applied migrations
- Upgrade + downgrade paths
- Auto-generation possible (not used here — we use raw SQL for asyncpg compatibility)

**Why NOT SQLAlchemy ORM:**
- Niles uses `asyncpg` directly (raw SQL) — not SQLAlchemy
- Adding SQLAlchemy as a dependency for schema management only would be overengineered
- Alembic supports raw SQL migrations via `op.execute()` without ORM models

**Why NOT asyncpg-migrate or custom scripts:**
- No standardized version tracking
- No downgrade support
- Less community support

### Compatibility Constraint

Alembic requires a synchronous database connection (via `sqlalchemy.engine`). Since Niles uses `asyncpg` exclusively, Alembic runs as a **standalone CLI tool** with its own sync connection — not integrated into the async FastAPI runtime.

**Runtime flow:**
1. Alembic runs migrations (sync, via `psycopg2` or `sqlalchemy[asyncio]`)
2. Niles Core starts (async, via `asyncpg`)
3. Stores no longer create tables — they only read/write

---

## 3. Current State Analysis

### Complete Table Inventory

11 tables, 8 indexes, in database `evolution_db`:

```sql
-- 1. users (user_store.py)
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL,
    avatar_url TEXT,
    password_hash TEXT,
    auth_method TEXT NOT NULL DEFAULT 'google',
    is_admin BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW(),
    last_login TIMESTAMP DEFAULT NOW()
);

-- 2. whatsapp_sessions (whatsapp_store.py)
CREATE TABLE whatsapp_sessions (
    user_id INTEGER PRIMARY KEY REFERENCES users(id),
    instance_name TEXT UNIQUE NOT NULL,
    phone_number TEXT,
    status TEXT NOT NULL DEFAULT 'disconnected'
        CHECK (status IN ('disconnected', 'connecting', 'connected')),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX whatsapp_sessions_phone_idx ON whatsapp_sessions (phone_number);

-- 3. vikunja_credentials (vikunja_store.py)
CREATE TABLE vikunja_credentials (
    user_id INTEGER PRIMARY KEY REFERENCES users(id),
    api_token TEXT NOT NULL,
    api_url TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 4. contacts (carddav.py)
CREATE TABLE contacts (
    id SERIAL PRIMARY KEY,
    full_name TEXT NOT NULL,
    first_name TEXT,
    last_name TEXT,
    phone_primary TEXT,
    phone_mobile TEXT,
    phone_work TEXT,
    email TEXT,
    cardav_uid TEXT UNIQUE,
    cardav_url TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_contacts_full_name ON contacts (full_name);

-- 5. contact_phones (carddav.py)
CREATE TABLE contact_phones (
    id SERIAL PRIMARY KEY,
    contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    type TEXT NOT NULL DEFAULT 'other',
    number TEXT NOT NULL,
    UNIQUE(contact_id, number)
);
CREATE INDEX idx_contact_phones_contact_id ON contact_phones (contact_id);

-- 6. events (caldav.py + manager.py)
CREATE TABLE events (
    id SERIAL PRIMARY KEY,
    summary TEXT NOT NULL,
    dtstart TIMESTAMP WITH TIME ZONE NOT NULL,
    dtend TIMESTAMP WITH TIME ZONE,
    all_day BOOLEAN DEFAULT FALSE,
    description TEXT,
    location TEXT,
    transp TEXT DEFAULT 'OPAQUE',
    caldav_uid TEXT UNIQUE,
    caldav_url TEXT,
    source_id INTEGER REFERENCES calendar_sources(id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_events_dtstart ON events (dtstart);
CREATE INDEX idx_events_summary ON events (summary);
CREATE INDEX idx_events_source_id ON events (source_id);

-- 7. calendar_sources (manager.py)
CREATE TABLE calendar_sources (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    source_type TEXT NOT NULL DEFAULT 'ics',
    writable BOOLEAN DEFAULT FALSE,
    enabled BOOLEAN DEFAULT TRUE,
    auth_user TEXT,
    auth_password TEXT,
    google_refresh_token TEXT,
    google_token_expiry TIMESTAMP WITH TIME ZONE,
    last_synced TIMESTAMP WITH TIME ZONE,
    last_error TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(url, source_type)
);

-- 8. memory (memory/store.py)
CREATE TABLE memory (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_memory_updated ON memory (updated_at DESC);

-- 9. conversations (memory/history.py)
CREATE TABLE conversations (
    id SERIAL PRIMARY KEY,
    chat_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_conversations_chat ON conversations (chat_id, created_at);

-- 10. signal_messages (signal_store.py)
CREATE TABLE signal_messages (
    id SERIAL PRIMARY KEY,
    phone TEXT NOT NULL,
    text TEXT NOT NULL,
    from_me BOOLEAN NOT NULL DEFAULT FALSE,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    chat_id TEXT NOT NULL DEFAULT ''
);
CREATE INDEX idx_signal_messages_phone ON signal_messages (phone, timestamp DESC);

-- 11. settings_overrides (settings_store.py)
CREATE TABLE settings_overrides (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### Foreign Key Dependencies (Creation Order)

```
users                    (no FK)
├── whatsapp_sessions    (FK → users.id)
├── vikunja_credentials  (FK → users.id)
contacts                 (no FK)
├── contact_phones       (FK → contacts.id)
calendar_sources         (no FK)
├── events               (FK → calendar_sources.id)
memory                   (no FK)
conversations            (no FK)
signal_messages          (no FK)
settings_overrides       (no FK)
```

---

## 4. Target Architecture

### Directory Structure

```
Niles/
├── alembic/
│   ├── env.py                          # Alembic environment (sync connection)
│   ├── script.py.mako                  # Migration template
│   └── versions/
│       ├── 001_baseline.py             # Initial schema (all 11 tables)
│       └── 002_*.py                    # Future migrations
├── alembic.ini                         # Alembic config (reads DATABASE_URL from env)
├── scripts/
│   ├── migrate.sh                      # Run migrations (wraps alembic upgrade head)
│   └── start.sh                        # Updated: runs migrate.sh before container start
```

### Runtime Flow (Updated)

```
./scripts/start.sh
    │
    ├── 1. docker compose up -d postgres     (DB ready)
    ├── 2. ./scripts/migrate.sh              (Alembic upgrade head)
    │       └── alembic upgrade head
    │           ├── Checks alembic_version table
    │           ├── Applies pending migrations in order
    │           └── Updates alembic_version to latest
    └── 3. docker compose up -d              (All services)
            └── Niles Core starts
                └── lifespan(): Stores connect but do NOT create tables
```

### Key Principle: Separation of Concerns

| Responsibility | Before | After |
|---------------|--------|-------|
| Schema creation | Store `initialize()` methods | Alembic migration files |
| Schema versioning | None | `alembic_version` table |
| Data migrations | Ad-hoc in `initialize()` | Alembic migration files |
| Runtime Store init | CREATE TABLE + business logic | Business logic only (verify table exists) |

---

## 5. Implementation Plan

### Step-by-Step (Ordered)

| Step | Action | Files | Risk |
|------|--------|-------|------|
| 1 | Add dependencies | `pyproject.toml` | None |
| 2 | Initialize Alembic | `alembic.ini`, `alembic/env.py`, `alembic/script.py.mako` | None |
| 3 | Create baseline migration | `alembic/versions/001_baseline.py` | **Medium** — must match production schema exactly |
| 4 | Stamp existing databases | `scripts/migrate.sh` | **Low** — stamp only marks version, no SQL |
| 5 | Refactor Store `initialize()` methods | 7 store files | **Medium** — remove CREATE TABLE, keep business logic |
| 6 | Update `main.py` lifespan | `src/niles/main.py` | **Low** — remove init calls, add version check |
| 7 | Update `start.sh` | `scripts/start.sh` | **Low** |
| 8 | Add tests | `tests/test_migrations.py` | None |
| 9 | Update documentation | `Deployment.md`, `Development.md`, `Niles-Core-Spec.md` | None |

---

## 6. Migration Baseline

### `alembic/versions/001_baseline.py`

The baseline migration creates all 11 tables as they exist today. For **existing** installations (databases that already have the tables), the migration is stamped without execution.

```python
"""Baseline: all tables as of Niles v0.1.0.

Revision ID: 001
Create Date: 2026-02-27
"""
from alembic import op
import sqlalchemy as sa

revision = "001"
down_revision = None


def upgrade():
    # Table creation order respects FK dependencies.
    # Every statement uses IF NOT EXISTS for safety on partially
    # migrated databases (e.g., interrupted first run).

    # --- Independent tables (no FKs) ---
    op.execute("""
        CREATE TABLE IF NOT EXISTS users ( ... );
    """)
    # ... all 11 tables, indexes, constraints
    # (full SQL from Section 3 above)


def downgrade():
    # Reverse order (FKs first)
    op.execute("DROP TABLE IF EXISTS signal_messages")
    op.execute("DROP TABLE IF EXISTS settings_overrides")
    op.execute("DROP TABLE IF EXISTS conversations")
    op.execute("DROP TABLE IF EXISTS memory")
    op.execute("DROP TABLE IF EXISTS events")
    op.execute("DROP TABLE IF EXISTS calendar_sources")
    op.execute("DROP TABLE IF EXISTS contact_phones")
    op.execute("DROP TABLE IF EXISTS contacts")
    op.execute("DROP TABLE IF EXISTS vikunja_credentials")
    op.execute("DROP TABLE IF EXISTS whatsapp_sessions")
    op.execute("DROP TABLE IF EXISTS users")
```

**Critical:** The baseline must produce the exact same schema as the current `CREATE TABLE IF NOT EXISTS` statements. Verify by comparing `pg_dump --schema-only` before and after on a test database.

### Handling Existing Installations

Existing databases already have all tables. The first migration run must **stamp** the baseline without executing it:

```bash
# In migrate.sh:
# If alembic_version table doesn't exist but users table does → stamp baseline
if alembic heads shows 001 as pending AND users table exists:
    alembic stamp 001
else:
    alembic upgrade head
```

Implementation in `scripts/migrate.sh`:

```bash
#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")/.."

# Build DATABASE_URL from .env variables
source .env
DB_URL="postgresql://evolution:${EVOLUTION_POSTGRES_PASSWORD}@${POSTGRES_HOST:-localhost}:${POSTGRES_PORT:-5432}/evolution_db"

# Wait for PostgreSQL
echo "Waiting for PostgreSQL..."
until docker exec niles_evolution_postgres pg_isready -U evolution -d evolution_db -q 2>/dev/null; do
    sleep 1
done

# Check if this is an existing installation (tables exist but no alembic_version)
HAS_USERS=$(docker exec niles_evolution_postgres psql -U evolution -d evolution_db -tAc \
    "SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name='users')")
HAS_ALEMBIC=$(docker exec niles_evolution_postgres psql -U evolution -d evolution_db -tAc \
    "SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name='alembic_version')")

if [ "$HAS_USERS" = "t" ] && [ "$HAS_ALEMBIC" = "f" ]; then
    echo "Existing installation detected — stamping baseline..."
    DATABASE_URL="$DB_URL" alembic stamp 001
else
    echo "Running migrations..."
    DATABASE_URL="$DB_URL" alembic upgrade head
fi

echo "Database schema up to date."
```

---

## 7. Store Refactoring

### Pattern: Remove Schema Creation, Keep Business Logic

**Before** (example: `user_store.py`):

```python
async def initialize(self) -> None:
    """Create users table and run migrations."""
    await self.pool.execute("""
        CREATE TABLE IF NOT EXISTS users ( ... )
    """)
    await self.pool.execute("""
        ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash TEXT
    """)
    # ... more ALTER TABLE ...
    # Business logic: auto-promote single user to admin
    admin_count = await self.pool.fetchval(...)
    ...
```

**After:**

```python
async def initialize(self) -> None:
    """Run post-migration business logic.

    Schema creation and migrations are handled by Alembic.
    See alembic/versions/ for schema history.
    """
    # Auto-promote: if exactly one user exists and no admin, make them admin
    admin_count = await self.pool.fetchval(
        "SELECT COUNT(*) FROM users WHERE is_admin = TRUE"
    )
    if admin_count == 0:
        total = await self.pool.fetchval("SELECT COUNT(*) FROM users")
        if total == 1:
            await self.pool.execute(
                "UPDATE users SET is_admin = TRUE WHERE id = "
                "(SELECT id FROM users LIMIT 1)"
            )
            logger.info("Auto-promoted single existing user to admin")
    logger.info("User store initialized")
```

### Refactoring Table Per Store

| Store | Remove | Keep |
|-------|--------|------|
| `memory/store.py` | `CREATE TABLE memory`, `CREATE INDEX` | Nothing (pure CRUD) |
| `memory/history.py` | `CREATE TABLE conversations`, `CREATE INDEX` | Nothing (pure CRUD) |
| `user_store.py` | `CREATE TABLE users`, 3× `ALTER TABLE` | Admin auto-promote logic |
| `whatsapp_store.py` | `CREATE TABLE whatsapp_sessions`, `CREATE INDEX` | Nothing |
| `vikunja_store.py` | `CREATE TABLE vikunja_credentials` | Nothing |
| `settings_store.py` | `CREATE TABLE settings_overrides` | Nothing |
| `signal_store.py` | `CREATE TABLE signal_messages`, `CREATE INDEX` | Nothing |
| `sync/carddav.py` | `CREATE TABLE contacts`, `contact_phones`, indexes | `_migrate_phones()` — **move to Alembic migration** |
| `sync/caldav.py` | `CREATE TABLE events`, indexes | Nothing |
| `sync/manager.py` | `CREATE TABLE calendar_sources`, `events`, `ALTER TABLE` × 2, indexes | `_migrate_env_source()` — **keep** (runtime, reads .env) |

### Special Case: `_migrate_phones()` in CardDAV

The phone migration (`carddav.py._migrate_phones()`) copies data from legacy columns (`phone_primary`, `phone_mobile`, `phone_work`) to the `contact_phones` table. This is a **data migration**, not a schema migration.

**Decision:** Move to a separate Alembic data migration (`002_migrate_contact_phones.py`). The migration checks if legacy columns have data not yet in `contact_phones`, copies it, and is idempotent.

### Special Case: `_migrate_env_source()` in CalendarSourceManager

This method checks if a CalDAV URL is configured in `.env` but not yet in `calendar_sources`, and creates the entry. This is **runtime business logic** (depends on current .env values), not a schema migration.

**Decision:** Keep in `manager.py initialize()`.

---

## 8. Runtime Integration

### Updated `main.py` Lifespan

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Load settings
    # 2. Configure logging
    # 3. Create asyncpg pool

    # 4. Verify schema version (new)
    alembic_version = await pool.fetchval(
        "SELECT version_num FROM alembic_version LIMIT 1"
    )
    if alembic_version is None:
        logger.error(
            "No alembic_version found. Run ./scripts/migrate.sh first."
        )
        sys.exit(1)
    logger.info("Database schema version: %s", alembic_version)

    # 5. Initialize stores (business logic only, no CREATE TABLE)
    memory_store = MemoryStore(pool)
    # No more: await memory_store.initialize()
    # Stores that still have business logic:
    user_store = UserStore(pool)
    await user_store.initialize()  # admin auto-promote only
    # ...

    # 6. Rest of lifespan unchanged
```

### Updated `scripts/start.sh`

```bash
#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")/.."

# 1. Check Docker
# 2. Build images
# 3. Start PostgreSQL first
docker compose -f docker/docker-compose.yml --env-file .env up -d evolution_postgres

# 4. Run migrations (NEW)
echo "Running database migrations..."
./scripts/migrate.sh

# 5. Start all services
docker compose -f docker/docker-compose.yml --env-file .env up -d
```

### Alembic Connection Configuration

`alembic/env.py`:

```python
import os
from alembic import context

def run_migrations_online():
    """Run migrations using a sync connection."""
    from sqlalchemy import create_engine

    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL not set")

    engine = create_engine(url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()
```

`alembic.ini`:

```ini
[alembic]
script_location = alembic
# URL is set via DATABASE_URL env var in env.py
# sqlalchemy.url is intentionally left empty
```

---

## 9. Developer Workflow

### Creating a New Migration

```bash
# 1. Write migration
DATABASE_URL="postgresql://evolution:password@localhost:5432/evolution_db" \
    alembic revision -m "add_email_integration"

# 2. Edit the generated file in alembic/versions/
#    - Write upgrade() with raw SQL via op.execute()
#    - Write downgrade() with reverse SQL

# 3. Test locally
DATABASE_URL="..." alembic upgrade head
DATABASE_URL="..." alembic downgrade -1
DATABASE_URL="..." alembic upgrade head

# 4. Commit migration file
```

### Migration File Template

```python
"""Short description of the change.

Revision ID: auto-generated
Create Date: auto-generated
"""
from alembic import op

revision = "003"
down_revision = "002"


def upgrade():
    op.execute("""
        ALTER TABLE users ADD COLUMN IF NOT EXISTS
            phone TEXT
    """)


def downgrade():
    op.execute("""
        ALTER TABLE users DROP COLUMN IF EXISTS phone
    """)
```

### Convention: Raw SQL Only

All migrations use `op.execute()` with raw SQL. No SQLAlchemy Table objects, no ORM. This keeps consistency with the asyncpg-based codebase and avoids a parallel schema definition.

---

## 10. Rollback Strategy

### Downgrade Path

```bash
# Roll back one migration
DATABASE_URL="..." alembic downgrade -1

# Roll back to specific version
DATABASE_URL="..." alembic downgrade 001

# Show current version
DATABASE_URL="..." alembic current

# Show migration history
DATABASE_URL="..." alembic history
```

### Backup Before Migration

`scripts/migrate.sh` should create a lightweight backup before applying:

```bash
echo "Creating pre-migration backup..."
docker exec niles_evolution_postgres pg_dump -U evolution evolution_db \
    --schema-only > "backups/schema-before-$(date +%Y%m%d-%H%M%S).sql"
```

### Failed Migration Recovery

If a migration fails mid-way:

1. Alembic does NOT auto-rollback partial migrations (PostgreSQL DDL is transactional, but Alembic default is autocommit)
2. **Solution:** Configure `transaction_per_migration=True` in `env.py` so each migration runs in a single transaction
3. On failure: the migration is rolled back atomically, `alembic_version` stays at the previous version

```python
# In env.py:
context.configure(
    connection=connection,
    target_metadata=None,
    transaction_per_migration=True,  # Critical: atomic migrations
)
```

---

## 11. Testing Strategy

### `tests/test_migrations.py`

```python
"""Test that Alembic migrations are consistent."""

class TestMigrations:
    def test_migration_chain_complete(self):
        """All migrations form an unbroken chain from base to head."""
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        config = Config("alembic.ini")
        scripts = ScriptDirectory.from_config(config)
        revisions = list(scripts.walk_revisions())
        # Chain is unbroken: each revision has a down_revision
        # pointing to the previous one (except base)
        assert len(revisions) > 0
        base = [r for r in revisions if r.down_revision is None]
        assert len(base) == 1, "Exactly one base revision"

    def test_baseline_matches_stores(self):
        """Baseline migration SQL matches current store schema.

        Compare pg_dump of a fresh database (after alembic upgrade head)
        with pg_dump of a database created by store.initialize() methods.
        """
        # This test requires a real PostgreSQL instance.
        # Mark as integration test, skip in CI without DB.
        pass

    def test_upgrade_downgrade_cycle(self):
        """Each migration can be upgraded and downgraded cleanly."""
        # Requires real PostgreSQL.
        pass
```

### Existing Tests

Existing unit tests (455) mock the database. They are not affected by this change because:
- Stores still have `initialize()` methods (just without CREATE TABLE)
- Tests mock `pool.execute()` — they never hit real SQL
- No test currently depends on schema creation in `initialize()`

---

## 12. File Changes Summary

### New Files

| File | Purpose |
|------|---------|
| `alembic.ini` | Alembic configuration |
| `alembic/env.py` | Database connection for migrations |
| `alembic/script.py.mako` | Migration file template |
| `alembic/versions/001_baseline.py` | Baseline: all 11 tables + indexes |
| `alembic/versions/002_migrate_contact_phones.py` | Data migration: legacy phone columns → contact_phones |
| `scripts/migrate.sh` | Migration runner (stamp or upgrade) |
| `tests/test_migrations.py` | Migration chain validation |

### Modified Files

| File | Change |
|------|--------|
| `pyproject.toml` | Add `alembic>=1.13.0`, `sqlalchemy>=2.0.0` (Alembic dependency), `psycopg2-binary>=2.9.0` |
| `scripts/start.sh` | Add `./scripts/migrate.sh` before full `docker compose up` |
| `src/niles/main.py` | Add schema version check, remove Store `initialize()` calls where only CREATE TABLE |
| `src/niles/memory/store.py` | Remove `initialize()` (or make it a no-op) |
| `src/niles/memory/history.py` | Remove `initialize()` (or make it a no-op) |
| `src/niles/user_store.py` | Remove CREATE TABLE + ALTER TABLE, keep admin auto-promote |
| `src/niles/whatsapp_store.py` | Remove `initialize()` |
| `src/niles/vikunja_store.py` | Remove `initialize()` |
| `src/niles/settings_store.py` | Remove `initialize()` |
| `src/niles/signal_store.py` | Remove `initialize()` |
| `src/niles/sync/carddav.py` | Remove `initialize()` (table creation + phone migration) |
| `src/niles/sync/caldav.py` | Remove `initialize()` |
| `src/niles/sync/manager.py` | Remove CREATE TABLE + ALTER TABLE, keep `_migrate_env_source()` |
| `docs/Deployment.md` | Add migration section, update Quick Start |
| `docs/Development.md` | Add "Creating a New Migration" workflow |
| `docs/Niles-Core-Spec.md` | Update Section 4 (Database Schema) to reference Alembic |
| `docker/Dockerfile.niles` | Add `alembic` + `sqlalchemy` + `psycopg2-binary` to image |

---

## 13. Verification Checklist

### Before Merge

- [ ] `alembic upgrade head` on an **empty** database creates all 11 tables with correct schema
- [ ] `pg_dump --schema-only` on Alembic-created DB matches `pg_dump` on current production DB
- [ ] `alembic upgrade head` on an **existing** database (with `alembic stamp 001` first) makes no changes
- [ ] `alembic downgrade base` drops all tables cleanly
- [ ] `alembic upgrade head && alembic downgrade -1 && alembic upgrade head` cycle works
- [ ] `./scripts/start.sh` on a fresh system creates DB and starts Niles
- [ ] `./scripts/start.sh` on an existing system stamps and starts without data loss
- [ ] All 455 existing tests still pass
- [ ] `python -m ruff check src/ tests/ alembic/` — no lint errors
- [ ] `_migrate_env_source()` still works (runtime CalDAV migration from .env)
- [ ] Contact phone data migration (002) is idempotent — running twice produces same result
- [ ] Schema version is logged on startup: `Database schema version: 002`

### After Deploy (First Customer)

- [ ] Niles starts without manual SQL intervention
- [ ] Schema version is visible in logs
- [ ] Subsequent update with a new migration applies automatically