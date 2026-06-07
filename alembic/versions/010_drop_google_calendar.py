"""Drop Google Calendar OAuth infrastructure.

Revision ID: 010
Revises: 009
Create Date: 2026-06-06

Google Calendar is no longer accessed via OAuth / per-user MCP server.
Users add Google Calendar as an ICS subscription (read-only) instead.
Google Login OAuth (openid scope) remains untouched.
"""

from alembic import op

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS user_google_tokens")
    op.execute("ALTER TABLE calendar_sources DROP COLUMN IF EXISTS google_refresh_token")
    op.execute("ALTER TABLE calendar_sources DROP COLUMN IF EXISTS google_token_expiry")


def downgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS user_google_tokens (
            user_id       INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            refresh_token TEXT NOT NULL,
            access_token  TEXT NOT NULL DEFAULT '',
            token_expiry  TIMESTAMPTZ,
            scopes        TEXT NOT NULL DEFAULT '',
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("ALTER TABLE calendar_sources ADD COLUMN IF NOT EXISTS google_refresh_token TEXT")
    op.execute("ALTER TABLE calendar_sources ADD COLUMN IF NOT EXISTS google_token_expiry TIMESTAMPTZ")
