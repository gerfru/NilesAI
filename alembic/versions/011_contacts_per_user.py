"""Make CardDAV contacts per-user with dedicated carddav_sources table.

Revision ID: 011
Revises: 010
Create Date: 2026-06-06

Each user gets their own CardDAV sources and contacts. Migrates from
app-wide settings_overrides to per-user carddav_sources table.
"""

from alembic import op

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create carddav_sources table (mirrors calendar_sources pattern)
    op.execute("""
        CREATE TABLE IF NOT EXISTS carddav_sources (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            name TEXT NOT NULL DEFAULT '',
            url TEXT NOT NULL,
            auth_user TEXT NOT NULL DEFAULT '',
            auth_password TEXT,
            last_synced TIMESTAMPTZ,
            last_error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    # Expression-based unique constraint (COALESCE not allowed in inline UNIQUE)
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_carddav_sources_url_user ON carddav_sources (url, COALESCE(user_id, -1))"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_carddav_sources_user_id ON carddav_sources (user_id)")

    # 2. Add user_id and source_id to contacts
    op.execute("ALTER TABLE contacts ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE CASCADE")
    op.execute(
        "ALTER TABLE contacts "
        "ADD COLUMN IF NOT EXISTS source_id INTEGER "
        "REFERENCES carddav_sources(id) ON DELETE CASCADE"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_contacts_user_id ON contacts (user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_contacts_source_id ON contacts (source_id)")

    # 3. Make cardav_uid unique per user instead of globally
    op.execute("ALTER TABLE contacts DROP CONSTRAINT IF EXISTS contacts_cardav_uid_key")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_contacts_cardav_uid_user ON contacts (cardav_uid, COALESCE(user_id, -1))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_contacts_cardav_uid_user")
    # Restore global unique constraint (only safe if no duplicates exist)
    op.execute("ALTER TABLE contacts ADD CONSTRAINT contacts_cardav_uid_key UNIQUE (cardav_uid)")
    op.execute("DROP INDEX IF EXISTS idx_contacts_source_id")
    op.execute("DROP INDEX IF EXISTS idx_contacts_user_id")
    op.execute("ALTER TABLE contacts DROP COLUMN IF EXISTS source_id")
    op.execute("ALTER TABLE contacts DROP COLUMN IF EXISTS user_id")
    op.execute("DROP INDEX IF EXISTS idx_carddav_sources_user_id")
    op.execute("DROP INDEX IF EXISTS uq_carddav_sources_url_user")
    op.execute("DROP TABLE IF EXISTS carddav_sources")
