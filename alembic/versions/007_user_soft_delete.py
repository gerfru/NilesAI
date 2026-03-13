"""Add soft-delete columns to users table.

Revision ID: 007
Revises: 006
Create Date: 2026-03-13

Replaces hard DELETE with is_active flag + deactivated_at timestamp.
"""

from alembic import op

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE users "
        "ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE"
    )
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS deactivated_at TIMESTAMPTZ")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_users_active"
        " ON users (is_active) WHERE is_active = TRUE"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_users_active")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS deactivated_at")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS is_active")
