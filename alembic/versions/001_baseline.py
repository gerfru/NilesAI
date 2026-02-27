"""Baseline: all tables as of Niles v0.1.0.

Revision ID: 001
Revises: -
Create Date: 2026-02-27

Creates all 11 tables with indexes in FK dependency order.
Every statement uses IF NOT EXISTS for safety on partially migrated databases.
"""

from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. users (no FK)
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            display_name TEXT NOT NULL,
            avatar_url TEXT,
            password_hash TEXT,
            auth_method TEXT NOT NULL DEFAULT 'google',
            is_admin BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT NOW(),
            last_login TIMESTAMP DEFAULT NOW()
        )
    """)

    # ------------------------------------------------------------------
    # 2. whatsapp_sessions (FK -> users)
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS whatsapp_sessions (
            user_id INTEGER PRIMARY KEY REFERENCES users(id),
            instance_name TEXT UNIQUE NOT NULL,
            phone_number TEXT,
            status TEXT NOT NULL DEFAULT 'disconnected'
                CHECK (status IN ('disconnected', 'connecting', 'connected')),
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS whatsapp_sessions_phone_idx
        ON whatsapp_sessions (phone_number)
    """)

    # ------------------------------------------------------------------
    # 3. vikunja_credentials (FK -> users)
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS vikunja_credentials (
            user_id INTEGER PRIMARY KEY REFERENCES users(id),
            api_token TEXT NOT NULL,
            api_url TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        )
    """)

    # ------------------------------------------------------------------
    # 4. contacts (no FK)
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS contacts (
            id SERIAL PRIMARY KEY,
            full_name TEXT NOT NULL,
            first_name TEXT,
            last_name TEXT,
            phone_primary TEXT,   -- TODO: remove after 002 normalizes into contact_phones
            phone_mobile TEXT,    -- TODO: remove after 002 normalizes into contact_phones
            phone_work TEXT,      -- TODO: remove after 002 normalizes into contact_phones
            email TEXT,
            cardav_uid TEXT UNIQUE,
            cardav_url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_contacts_full_name
        ON contacts (full_name)
    """)

    # ------------------------------------------------------------------
    # 5. contact_phones (FK -> contacts)
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS contact_phones (
            id SERIAL PRIMARY KEY,
            contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
            type TEXT NOT NULL DEFAULT 'other',
            number TEXT NOT NULL,
            UNIQUE(contact_id, number)
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_contact_phones_contact_id
        ON contact_phones (contact_id)
    """)

    # ------------------------------------------------------------------
    # 6. calendar_sources (no FK)
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS calendar_sources (
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
        )
    """)

    # ------------------------------------------------------------------
    # 7. events (FK -> calendar_sources) — unified definition
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS events (
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
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_events_dtstart ON events (dtstart)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_events_summary ON events (summary)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_events_source_id ON events (source_id)
    """)

    # ------------------------------------------------------------------
    # 8. memory (no FK)
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS memory (
            key TEXT PRIMARY KEY,
            value JSONB NOT NULL,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_memory_updated
        ON memory (updated_at DESC)
    """)

    # ------------------------------------------------------------------
    # 9. conversations (no FK)
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id SERIAL PRIMARY KEY,
            chat_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_conversations_chat
        ON conversations (chat_id, created_at)
    """)

    # ------------------------------------------------------------------
    # 10. signal_messages (no FK)
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS signal_messages (
            id SERIAL PRIMARY KEY,
            phone TEXT NOT NULL,
            text TEXT NOT NULL,
            from_me BOOLEAN NOT NULL DEFAULT FALSE,
            timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            chat_id TEXT NOT NULL DEFAULT ''
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_signal_messages_phone_ts
        ON signal_messages (phone, timestamp DESC)
    """)

    # ------------------------------------------------------------------
    # 11. settings_overrides (no FK)
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS settings_overrides (
            key TEXT PRIMARY KEY,
            value JSONB NOT NULL,
            updated_at TIMESTAMP DEFAULT NOW()
        )
    """)


def downgrade() -> None:
    # Drop in reverse FK order; CASCADE for safety against external FKs
    op.execute("DROP TABLE IF EXISTS settings_overrides CASCADE")
    op.execute("DROP TABLE IF EXISTS signal_messages CASCADE")
    op.execute("DROP TABLE IF EXISTS conversations CASCADE")
    op.execute("DROP TABLE IF EXISTS memory CASCADE")
    op.execute("DROP TABLE IF EXISTS events CASCADE")
    op.execute("DROP TABLE IF EXISTS calendar_sources CASCADE")
    op.execute("DROP TABLE IF EXISTS contact_phones CASCADE")
    op.execute("DROP TABLE IF EXISTS contacts CASCADE")
    op.execute("DROP TABLE IF EXISTS vikunja_credentials CASCADE")
    op.execute("DROP TABLE IF EXISTS whatsapp_sessions CASCADE")
    op.execute("DROP TABLE IF EXISTS users CASCADE")
