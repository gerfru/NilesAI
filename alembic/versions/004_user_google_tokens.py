"""Add user_google_tokens table for per-user Google OAuth tokens.

Revision ID: 004
Revises: 003
Create Date: 2026-03-05

Stores per-user Google OAuth refresh/access tokens for gws MCP server
instances. Each user gets their own gws process with their own token.
"""

from alembic import op

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
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


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS user_google_tokens")
