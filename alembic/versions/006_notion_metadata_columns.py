"""Add page_title and heading_context columns for keyword search.

Revision ID: 006
Revises: 005
Create Date: 2026-03-12

Adds structured metadata columns to notion_embeddings so the retriever
can apply keyword-based scoring alongside vector similarity.

Backfills existing rows from notion_pages.title and chunk_text prefix.
"""

from alembic import op

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add columns with safe defaults
    op.execute("ALTER TABLE notion_embeddings ADD COLUMN IF NOT EXISTS page_title TEXT NOT NULL DEFAULT ''")
    op.execute("ALTER TABLE notion_embeddings ADD COLUMN IF NOT EXISTS heading_context TEXT NOT NULL DEFAULT ''")

    # 2. Backfill page_title from notion_pages.title
    op.execute(
        "UPDATE notion_embeddings e "
        "SET page_title = p.title "
        "FROM notion_pages p "
        "WHERE e.page_id = p.id AND e.page_title = ''"
    )

    # 3. Backfill heading_context from chunk_text bracket prefix.
    #    Prefix format: [Title > # Heading > ## Sub] body
    #    Extract content between [ and ] using substr+position (no regex),
    #    split on ' > ', keep only parts starting with '#'.
    op.execute("""
        UPDATE notion_embeddings
        SET heading_context = sub.hctx
        FROM (
            SELECT e.id,
                   string_agg(part, ' > ' ORDER BY ordinality) AS hctx
            FROM notion_embeddings e,
                 LATERAL unnest(
                     string_to_array(
                         substr(e.chunk_text, 2,
                                position(']' in e.chunk_text) - 2),
                         ' > '
                     )
                 ) WITH ORDINALITY AS t(part, ordinality)
            WHERE e.chunk_text LIKE '[%%'
              AND position(']' in e.chunk_text) > 1
              AND part LIKE '#%%'
            GROUP BY e.id
        ) sub
        WHERE notion_embeddings.id = sub.id
          AND notion_embeddings.heading_context = ''
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE notion_embeddings DROP COLUMN IF EXISTS heading_context")
    op.execute("ALTER TABLE notion_embeddings DROP COLUMN IF EXISTS page_title")
