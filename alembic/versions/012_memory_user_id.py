"""Add user_id to memory table for per-user scoping.

Revision ID: 012
Revises: 011
Create Date: 2026-06-11

Scope all memory entries to a user. Migrates from global key-only PK
to composite (user_id, key) PK so each user has their own namespace.
"""

from alembic import op

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add nullable user_id FK
    op.execute("ALTER TABLE memory ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE CASCADE")

    # 2. Assign existing rows to the first user
    op.execute("UPDATE memory SET user_id = (SELECT id FROM users ORDER BY id LIMIT 1) WHERE user_id IS NULL")

    # 3. Remove orphaned rows (if no users exist at all)
    op.execute("DELETE FROM memory WHERE user_id IS NULL")

    # 4. Set NOT NULL constraint
    op.execute("ALTER TABLE memory ALTER COLUMN user_id SET NOT NULL")

    # 5. Change PK: key-only -> composite (user_id, key)
    op.execute("ALTER TABLE memory DROP CONSTRAINT IF EXISTS memory_pkey")
    op.execute("ALTER TABLE memory ADD CONSTRAINT memory_pkey PRIMARY KEY (user_id, key)")

    # 6. Index for per-user list_all queries
    op.execute("CREATE INDEX IF NOT EXISTS idx_memory_user_id ON memory (user_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_memory_user_id")
    op.execute("ALTER TABLE memory DROP CONSTRAINT IF EXISTS memory_pkey")
    # Restore key-only PK (only safe if no duplicate keys across users)
    op.execute("ALTER TABLE memory ADD CONSTRAINT memory_pkey PRIMARY KEY (key)")
    op.execute("ALTER TABLE memory DROP COLUMN IF EXISTS user_id")
