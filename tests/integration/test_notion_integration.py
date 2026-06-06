"""Integration tests for NotionRetriever (pgvector + Ollama)."""

import pytest
import pytest_asyncio

from niles.actions.notion import NotionRetriever
from niles.sync.ollama_embedder import OllamaEmbedder

from .conftest import OLLAMA_BASE_URL, SingleConnectionPool

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]


@pytest_asyncio.fixture(loop_scope="session")
async def embedder(ollama_available):
    """OllamaEmbedder connected to real Ollama."""
    ollama_url = OLLAMA_BASE_URL.removesuffix("/v1")
    emb = OllamaEmbedder(ollama_base_url=ollama_url)
    yield emb
    await emb.close()


class TestOllamaEmbedder:
    async def test_embed_returns_vector(self, embedder):
        result = await embedder.embed("This is a test sentence")
        assert result is not None
        assert isinstance(result, list)
        assert len(result) == 768

    async def test_embed_with_query_prefix(self, embedder):
        result = await embedder.embed("test query", prefix="search_query: ")
        assert result is not None
        assert len(result) == 768

    async def test_embed_with_document_prefix(self, embedder):
        result = await embedder.embed("document text", prefix="search_document: ")
        assert result is not None
        assert len(result) == 768


class TestNotionRetriever:
    async def test_search_empty_db(self, pool_in_tx, embedder):
        retriever = NotionRetriever(pool_in_tx, embedder)
        results = await retriever.search("test query")
        assert results == []

    async def test_search_with_seeded_data(self, db_conn, embedder):
        # Uses db_conn directly (not pool_in_tx) because we construct a
        # SingleConnectionPool inline for the NotionRetriever — both the
        # seeding INSERTs and the search query run on the same connection
        # within the same rolled-back transaction.

        # Force sequential scan — pgvector's HNSW index uses approximate
        # nearest-neighbor search and may miss rows inserted within an
        # uncommitted transaction (the index graph still contains deleted
        # nodes and the new node may be unreachable via graph traversal).
        await db_conn.execute("SET LOCAL enable_indexscan = OFF")

        # Clear existing data so production embeddings don't drown out
        # the test document.  The outer transaction rolls this back.
        await db_conn.execute("DELETE FROM notion_embeddings")
        await db_conn.execute("DELETE FROM notion_pages")

        unique_text = "Xylophon-Reparaturanleitung für linkshändige Astronauten"
        page_title = "IntegTest Xylophon Handbuch"

        # Seed a Notion page
        await db_conn.execute(
            """
            INSERT INTO notion_pages (id, title, content_text, content_md5, url,
                                      synced_at, embedded_at)
            VALUES ('test-page-integ', $1, $2,
                    'abc123', 'https://notion.so/test', NOW(), NOW())
            """,
            page_title,
            unique_text,
        )
        # Generate real embedding for the document
        doc_embedding = await embedder.embed(
            unique_text,
            prefix="search_document: ",
        )
        assert doc_embedding is not None
        assert len(doc_embedding) == 768

        await db_conn.execute(
            """
            INSERT INTO notion_embeddings (page_id, chunk_index, chunk_text, embedding)
            VALUES ('test-page-integ', 0, $1, $2::vector)
            """,
            unique_text,
            str(doc_embedding),
        )

        # Search with a query that should match our unique document
        pool = SingleConnectionPool(db_conn)
        retriever = NotionRetriever(pool, embedder, similarity_threshold=0.0)
        results = await retriever.search("Xylophon Reparatur Astronauten")
        # Our unique document must appear in the results
        titles = [r["page_title"] for r in results]
        assert page_title in titles, (
            f"Expected '{page_title}' in results, got: {titles}"
        )
        match = next(r for r in results if r["page_title"] == page_title)
        assert match["similarity"] > 0.1
