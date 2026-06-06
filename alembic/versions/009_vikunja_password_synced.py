"""Add password_synced flag to vikunja_credentials.

Revision ID: 009
Revises: 008
Create Date: 2026-06-06

Tracks whether the Vikunja password has been synced to the user's
Niles password (True) or is still the HMAC-derived internal password (False).
"""

from alembic import op

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE vikunja_credentials "
        "ADD COLUMN IF NOT EXISTS password_synced BOOLEAN NOT NULL DEFAULT FALSE"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE vikunja_credentials DROP COLUMN IF EXISTS password_synced")
