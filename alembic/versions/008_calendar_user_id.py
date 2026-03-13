"""Add user_id to calendar_sources for multi-user isolation.

Revision ID: 008
Revises: 007
Create Date: 2026-03-13

Calendar sources were global (shared across all users). This migration
adds a nullable user_id FK so each user only sees their own sources.
Events inherit scope via source_id -> calendar_sources.user_id (JOIN).
"""

from alembic import op

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add nullable user_id column with FK to users
    op.execute(
        "ALTER TABLE calendar_sources "
        "ADD COLUMN IF NOT EXISTS user_id INTEGER "
        "REFERENCES users(id) ON DELETE CASCADE"
    )

    # 2. Assign existing sources to the first user (if any exist)
    op.execute(
        "UPDATE calendar_sources "
        "SET user_id = (SELECT id FROM users ORDER BY id LIMIT 1) "
        "WHERE user_id IS NULL"
    )

    # 3. Replace UNIQUE(url, source_type) with (url, source_type, user_id)
    #    COALESCE so NULL user_id rows still participate in uniqueness
    op.execute(
        "ALTER TABLE calendar_sources "
        "DROP CONSTRAINT IF EXISTS calendar_sources_url_source_type_key"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_calendar_sources_url_type_user "
        "ON calendar_sources (url, source_type, COALESCE(user_id, -1))"
    )

    # 4. Index for user_id lookups
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_calendar_sources_user_id "
        "ON calendar_sources (user_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_calendar_sources_user_id")
    op.execute("DROP INDEX IF EXISTS uq_calendar_sources_url_type_user")
    op.execute(
        "ALTER TABLE calendar_sources "
        "ADD CONSTRAINT calendar_sources_url_source_type_key "
        "UNIQUE (url, source_type)"
    )
    op.execute("ALTER TABLE calendar_sources DROP COLUMN IF EXISTS user_id")
