"""Add hierarchical chunking (2-level) to Notion embeddings.

Revision ID: 005
Revises: 004
Create Date: 2026-03-10

Adds chunk_level column to notion_embeddings:
- Level 0: Summary (parent) embeddings — one per page
- Level 1: Detail (child) embeddings — fine-grained chunks (existing data)

Existing rows default to level 1 (detail), so no data migration is needed.
"""

from alembic import op

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add chunk_level with default 1 (all existing rows become detail chunks)
    op.execute("ALTER TABLE notion_embeddings ADD COLUMN IF NOT EXISTS chunk_level SMALLINT NOT NULL DEFAULT 1")

    # 2. Replace unique constraint to include chunk_level
    op.execute("ALTER TABLE notion_embeddings DROP CONSTRAINT IF EXISTS notion_embeddings_page_id_chunk_index_key")
    op.execute(
        "ALTER TABLE notion_embeddings "
        "ADD CONSTRAINT notion_embeddings_page_id_level_chunk_key "
        "UNIQUE (page_id, chunk_level, chunk_index)"
    )

    # 3. Partial index for fast summary lookups
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_notion_embeddings_summaries "
        "ON notion_embeddings (page_id) WHERE chunk_level = 0"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_notion_embeddings_summaries")
    op.execute("ALTER TABLE notion_embeddings DROP CONSTRAINT IF EXISTS notion_embeddings_page_id_level_chunk_key")
    # Delete summaries before restoring old constraint
    op.execute("DELETE FROM notion_embeddings WHERE chunk_level = 0")
    op.execute(
        "ALTER TABLE notion_embeddings "
        "ADD CONSTRAINT notion_embeddings_page_id_chunk_index_key "
        "UNIQUE (page_id, chunk_index)"
    )
    op.execute("ALTER TABLE notion_embeddings DROP COLUMN IF EXISTS chunk_level")
