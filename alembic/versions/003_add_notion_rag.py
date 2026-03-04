"""Add Notion RAG tables and pgvector extension.

Revision ID: 003
Revises: 002
Create Date: 2026-03-04

Creates the pgvector extension and two tables for the Notion RAG pipeline:
- notion_pages: synced Notion page content with MD5 change detection
- notion_embeddings: chunked text with vector embeddings for similarity search
"""

from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.execute("""
        CREATE TABLE IF NOT EXISTS notion_pages (
            id              TEXT PRIMARY KEY,
            title           TEXT NOT NULL DEFAULT '',
            parent_id       TEXT,
            object_type     TEXT NOT NULL DEFAULT 'page',
            content_text    TEXT NOT NULL DEFAULT '',
            content_md5     TEXT NOT NULL DEFAULT '',
            url             TEXT NOT NULL DEFAULT '',
            last_edited     TIMESTAMPTZ,
            synced_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            embedded_at     TIMESTAMPTZ
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_notion_pages_parent
        ON notion_pages (parent_id)
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_notion_pages_needs_embedding
        ON notion_pages (id) WHERE embedded_at IS NULL OR embedded_at < synced_at
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS notion_embeddings (
            id              SERIAL PRIMARY KEY,
            page_id         TEXT NOT NULL REFERENCES notion_pages(id) ON DELETE CASCADE,
            chunk_index     INTEGER NOT NULL,
            chunk_text      TEXT NOT NULL,
            embedding       vector(768),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (page_id, chunk_index)
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_notion_embeddings_vector
        ON notion_embeddings
        USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS notion_embeddings")
    op.execute("DROP TABLE IF EXISTS notion_pages")
    # Do NOT drop the vector extension (other features might use it)
