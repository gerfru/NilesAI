# Niles AI — Notion RAG Pipeline

> **Version:** 1.0
> **Created:** 2026-03-03
> **Status:** Draft — ready for review

---

## 1. Overview

### 1.1 Goal

Niles gains read-only access to a Notion workspace as a knowledge base. Users can query their Notion content via natural language — either through the existing chat interface (agent tool) or via a dedicated "Notion Search" button in the Web UI.

### 1.2 Why RAG (Not Direct API per Query)

A local 8B model cannot reliably decide *when* to call a Notion search tool among 15+ existing tools. RAG with pre-indexed embeddings provides:

- **Deterministic retrieval** — similarity search always returns results, no tool-calling gamble.
- **Offline-capable** — after sync, queries work without Notion API calls.
- **Token-efficient** — only relevant chunks enter the LLM context, not entire pages.
- **Privacy** — embeddings and content are stored locally in PostgreSQL.

### 1.3 Why Not MCP (For Now)

The official Notion MCP server (`@notionhq/notion-mcp-server`) is optimized for **write operations** (create pages, add comments, update databases). It requires Node.js as an additional dependency and adds ~20 tools to the agent's tool list, which degrades tool selection quality on small local models.

**Recommendation:** Start with RAG for read access. MCP can be added later as a separate phase for write operations if needed.

### 1.4 Scope

| In Scope | Out of Scope |
|----------|-------------|
| Notion page and database content sync | Writing/creating Notion pages |
| Local embedding via Ollama | Cloud embedding services |
| pgvector similarity search | Separate vector DB (Qdrant, ChromaDB) |
| Agent tool `search_notion` | Full-text Notion search passthrough |
| Web UI "Notion Search" button | Notion OAuth (uses Internal Integration) |
| Settings UI for configuration | Multi-workspace support |

### 1.5 Architecture

```text
Notion API (Cloud)
     |
     | HTTPS (read-only, Internal Integration Token)
     v
+--------------------------------------------------+
|  Niles Core (FastAPI :8000)                      |
|                                                  |
|  sync/notion.py ------> notion_pages (PG)        |
|       |                                          |
|       v                                          |
|  sync/notion_embeddings.py                       |
|       | Ollama embedding model                   |
|       v                                          |
|  notion_embeddings (PG + pgvector)               |
|       ^                                          |
|       |                                          |
|  agent/tools/notion.py (search_notion)           |
|       |                                          |
|  actions/notion.py (NotionRetriever)             |
|       |                                          |
|  web/_notion.py (UI: status, config, search)     |
+--------------------------------------------------+
```

---

## 2. Prerequisites

### 2.1 Notion Internal Integration

1. Go to `https://www.notion.so/profile/integrations`
2. Click "New Integration"
3. Name: `Niles AI` (or similar)
4. Capabilities: **Read content** only (no update, no insert)
5. Copy the Internal Integration Secret (`ntn_****`)
6. On each Notion page/database to index: "..." → "Connect to integration" → select `Niles AI`

**Security:** Read-only token. Niles cannot modify or delete any Notion content. This aligns with the no-deletion policy.

### 2.2 Ollama Embedding Model

```bash
ollama pull nomic-embed-text
```

Alternative: `mxbai-embed-large` (1024 dimensions, slightly better quality, more RAM).

| Model | Dimensions | Size | Quality |
|-------|-----------|------|---------|
| `nomic-embed-text` | 768 | 274 MB | Good for general use |
| `mxbai-embed-large` | 1024 | 670 MB | Better semantic quality |

**Recommendation:** Start with `nomic-embed-text` (smaller, faster on M4).

### 2.3 pgvector Extension

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

Delivered via Alembic migration (see §4.1). The official PostgreSQL 15 Docker image supports pgvector after `apt install postgresql-15-pgvector` inside the container, or by switching to the `pgvector/pgvector:pg15` image.

**Docker image change:** Replace `postgres:15` with `pgvector/pgvector:pg15` in `docker-compose.yml`. This image includes pgvector pre-installed. No other configuration changes needed.

---

## 3. Configuration

### 3.1 Settings (`config.py`)

New fields on `Settings`:

```python
# Notion (RAG Knowledge Base)
notion_token: str = ""              # NOTION_TOKEN — Internal Integration Secret
notion_sync_interval: int = 30      # NOTION_SYNC_INTERVAL — minutes between syncs
notion_embedding_model: str = "nomic-embed-text-v2-moe"  # NOTION_EMBEDDING_MODEL
notion_chunk_size: int = 600        # NOTION_CHUNK_SIZE — tokens per chunk
notion_chunk_overlap: int = 100     # NOTION_CHUNK_OVERLAP — overlap between chunks
notion_similarity_threshold: float = 0.3  # NOTION_SIMILARITY_THRESHOLD — minimum cosine similarity
feature_notion: bool = False        # FEATURE_NOTION — master toggle
```

| Field | Default | Env Variable | Required |
|-------|---------|-------------|----------|
| `notion_token` | `""` | `NOTION_TOKEN` | Yes (when `feature_notion=true`) |
| `notion_sync_interval` | `30` | `NOTION_SYNC_INTERVAL` | No |
| `notion_embedding_model` | `"nomic-embed-text-v2-moe"` | `NOTION_EMBEDDING_MODEL` | No |
| `notion_chunk_size` | `600` | `NOTION_CHUNK_SIZE` | No |
| `notion_chunk_overlap` | `100` | `NOTION_CHUNK_OVERLAP` | No |
| `notion_similarity_threshold` | `0.3` | `NOTION_SIMILARITY_THRESHOLD` | No |
| `feature_notion` | `false` | `FEATURE_NOTION` | No |

### 3.2 Runtime Settings (Settings UI)

Add to `EDITABLE_SETTINGS` in `settings_store.py`:

```python
"feature_notion",
"notion_token",
"notion_sync_interval",
"notion_embedding_model",
"notion_chunk_size",
"notion_chunk_overlap",
"notion_similarity_threshold",
```

### 3.3 .env.example

```bash
# Notion RAG (optional)
# NOTION_TOKEN=ntn_****
# FEATURE_NOTION=true
# NOTION_SYNC_INTERVAL=30
# NOTION_EMBEDDING_MODEL=nomic-embed-text-v2-moe
```

---

## 4. Database Schema

### 4.1 Alembic Migration

File: `alembic/versions/XXX_add_notion_rag.py`

```python
"""Add Notion RAG tables and pgvector extension."""
from alembic import op

revision = "XXX"
down_revision = "<current_head>"

def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.execute("""
        CREATE TABLE IF NOT EXISTS notion_pages (
            id              TEXT PRIMARY KEY,        -- Notion page/database ID (UUID without dashes)
            title           TEXT NOT NULL DEFAULT '',
            parent_id       TEXT,                    -- Parent page/database ID
            object_type     TEXT NOT NULL DEFAULT 'page',  -- 'page' or 'database'
            content_text    TEXT NOT NULL DEFAULT '',       -- Flattened plaintext content
            content_md5     TEXT NOT NULL DEFAULT '',       -- MD5 of content_text (change detection)
            url             TEXT NOT NULL DEFAULT '',       -- Notion URL for source attribution
            last_edited     TIMESTAMPTZ,             -- Notion's last_edited_time
            synced_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            embedded_at     TIMESTAMPTZ              -- NULL = needs (re-)embedding
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
            embedding       vector(768),              -- Match embedding model dimensions
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

def downgrade():
    op.execute("DROP TABLE IF EXISTS notion_embeddings")
    op.execute("DROP TABLE IF EXISTS notion_pages")
    # Note: Do NOT drop the vector extension (other features might use it)
```

**Note on vector index:** `ivfflat` with `lists = 100` is suitable for up to ~100K chunks. For smaller workspaces (<1000 pages), a sequential scan may be faster — pgvector falls back automatically. The index can be rebuilt with different parameters if needed.

**Note on embedding dimensions:** The `vector(768)` column matches `nomic-embed-text`. If switching to `mxbai-embed-large` (1024 dimensions), the column must be altered and all embeddings regenerated. This is handled by the embedding pipeline (§6).

---

## 5. Notion Sync (`sync/notion.py`)

### 5.1 Overview

Periodic sync of Notion pages and databases into `notion_pages`. The sync:

1. Fetches all pages/databases accessible to the integration
2. Retrieves block content for each page (recursively)
3. Converts Notion blocks to plaintext
4. Upserts into `notion_pages` with MD5 change detection
5. Marks changed pages for re-embedding (`embedded_at = NULL`)

### 5.2 Dependencies

```
notion-client>=2.0.0    # Official Notion SDK (async support via httpx)
```

Add to `pyproject.toml` under `dependencies`.

### 5.3 Module: `src/niles/sync/notion.py`

```python
"""Notion workspace sync — fetches pages and converts to plaintext."""

import hashlib
import logging
from datetime import datetime, timezone

import asyncpg
from notion_client import AsyncClient

logger = logging.getLogger(__name__)

# Block types that contain readable text
_TEXT_BLOCK_TYPES = {
    "paragraph", "heading_1", "heading_2", "heading_3",
    "bulleted_list_item", "numbered_list_item", "to_do",
    "toggle", "callout", "quote", "code",
}

# Maximum pages per sync run (safety limit)
_MAX_PAGES = 2000

# Maximum block depth for recursive content fetch
_MAX_DEPTH = 5


class NotionSync:
    """Synchronizes Notion workspace content into PostgreSQL."""

    def __init__(self, pool: asyncpg.Pool, token: str):
        self._pool = pool
        self._client = AsyncClient(auth=token)
        self._stats = {"pages_synced": 0, "pages_unchanged": 0, "errors": 0}

    async def sync_all(self) -> dict:
        """Full sync: discover all pages, fetch content, upsert.

        Returns stats dict with pages_synced, pages_unchanged, errors.
        """
        self._stats = {"pages_synced": 0, "pages_unchanged": 0, "errors": 0}

        # 1. Search for all pages accessible to the integration
        pages = await self._discover_pages()

        # 2. For each page: fetch content, compute MD5, upsert if changed
        for page in pages:
            try:
                await self._sync_page(page)
            except Exception:
                logger.exception("Failed to sync page %s", page.get("id", "?"))
                self._stats["errors"] += 1

        logger.info(
            "Notion sync complete: %d synced, %d unchanged, %d errors",
            self._stats["pages_synced"],
            self._stats["pages_unchanged"],
            self._stats["errors"],
        )
        return self._stats

    async def _discover_pages(self) -> list[dict]:
        """Search Notion for all accessible pages and databases."""
        results = []
        cursor = None
        while len(results) < _MAX_PAGES:
            kwargs = {"page_size": 100}
            if cursor:
                kwargs["start_cursor"] = cursor
            response = await self._client.search(**kwargs)
            results.extend(response.get("results", []))
            if not response.get("has_more"):
                break
            cursor = response.get("next_cursor")
        logger.info("Discovered %d Notion objects", len(results))
        return results

    async def _sync_page(self, page: dict) -> None:
        """Fetch content for a single page and upsert if changed."""
        page_id = page["id"].replace("-", "")
        object_type = page.get("object", "page")
        title = self._extract_title(page)
        url = page.get("url", "")
        last_edited = page.get("last_edited_time")

        # Quick check: skip if last_edited hasn't changed
        existing = await self._pool.fetchrow(
            "SELECT last_edited, content_md5 FROM notion_pages WHERE id = $1",
            page_id,
        )
        if existing and existing["last_edited"] and last_edited:
            if str(existing["last_edited"]) == str(last_edited):
                self._stats["pages_unchanged"] += 1
                return

        # Fetch block content (pages only, not databases)
        content = ""
        if object_type == "page":
            content = await self._fetch_page_content(page["id"])

        content_md5 = hashlib.md5(content.encode()).hexdigest()

        # Skip if content hasn't actually changed
        if existing and existing["content_md5"] == content_md5:
            self._stats["pages_unchanged"] += 1
            # Still update last_edited timestamp
            await self._pool.execute(
                "UPDATE notion_pages SET last_edited = $2, synced_at = NOW() WHERE id = $1",
                page_id, last_edited,
            )
            return

        # Upsert page (mark for re-embedding by setting embedded_at = NULL)
        await self._pool.execute(
            """
            INSERT INTO notion_pages (id, title, parent_id, object_type,
                                      content_text, content_md5, url,
                                      last_edited, synced_at, embedded_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW(), NULL)
            ON CONFLICT (id) DO UPDATE SET
                title = $2, parent_id = $3, object_type = $4,
                content_text = $5, content_md5 = $6, url = $7,
                last_edited = $8, synced_at = NOW(), embedded_at = NULL
            """,
            page_id, title, self._extract_parent_id(page), object_type,
            content, content_md5, url, last_edited,
        )
        self._stats["pages_synced"] += 1

    async def _fetch_page_content(self, page_id: str, depth: int = 0) -> str:
        """Recursively fetch all text blocks of a page."""
        if depth > _MAX_DEPTH:
            return ""

        blocks = []
        cursor = None
        while True:
            kwargs = {"block_id": page_id, "page_size": 100}
            if cursor:
                kwargs["start_cursor"] = cursor
            response = await self._client.blocks.children.list(**kwargs)
            blocks.extend(response.get("results", []))
            if not response.get("has_more"):
                break
            cursor = response.get("next_cursor")

        lines = []
        for block in blocks:
            text = self._block_to_text(block)
            if text:
                lines.append(text)
            # Recurse into children (toggles, nested lists, etc.)
            if block.get("has_children"):
                child_text = await self._fetch_page_content(block["id"], depth + 1)
                if child_text:
                    lines.append(child_text)

        return "\n".join(lines)

    @staticmethod
    def _block_to_text(block: dict) -> str:
        """Extract plaintext from a single Notion block."""
        block_type = block.get("type", "")
        if block_type not in _TEXT_BLOCK_TYPES:
            return ""
        data = block.get(block_type, {})
        rich_text = data.get("rich_text", [])
        return "".join(rt.get("plain_text", "") for rt in rich_text)

    @staticmethod
    def _extract_title(page: dict) -> str:
        """Extract title from page or database properties."""
        # Database title
        if page.get("object") == "database":
            title_parts = page.get("title", [])
            return "".join(t.get("plain_text", "") for t in title_parts)
        # Page title (property named "title" or "Name")
        props = page.get("properties", {})
        for prop in props.values():
            if prop.get("type") == "title":
                title_parts = prop.get("title", [])
                return "".join(t.get("plain_text", "") for t in title_parts)
        return ""

    @staticmethod
    def _extract_parent_id(page: dict) -> str | None:
        """Extract parent page/database ID."""
        parent = page.get("parent", {})
        parent_type = parent.get("type", "")
        if parent_type == "page_id":
            return parent["page_id"].replace("-", "")
        if parent_type == "database_id":
            return parent["database_id"].replace("-", "")
        return None

    async def test_connection(self) -> tuple[bool, str]:
        """Test Notion API connectivity. Returns (ok, message)."""
        try:
            response = await self._client.search(page_size=1)
            count = len(response.get("results", []))
            return True, f"Verbunden. {count}+ Seiten zugänglich."
        except Exception as exc:
            return False, f"Verbindung fehlgeschlagen: {exc}"
```

### 5.4 Sync Job Registration (`main.py`)

In `lifespan()`, after existing scheduler jobs:

```python
# Notion RAG sync
notion_sync = None
if settings.feature_notion and settings.notion_token:
    from .sync.notion import NotionSync
    notion_sync = NotionSync(pool, settings.notion_token)
    scheduler.add_job(
        notion_sync.sync_all,
        "interval",
        minutes=settings.notion_sync_interval,
        id="notion_sync",
        max_instances=1,
        misfire_grace_time=600,
    )
    asyncio.create_task(notion_sync.sync_all())
    logger.info(
        "Notion sync scheduled (every %d min)", settings.notion_sync_interval
    )
app.state.notion_sync = notion_sync
```

---

## 6. Embedding Pipeline (`sync/notion_embeddings.py`)

### 6.1 Overview

After sync, changed pages (where `embedded_at IS NULL OR embedded_at < synced_at`) are chunked, embedded via Ollama, and stored in `notion_embeddings`.

### 6.2 Module: `src/niles/sync/notion_embeddings.py`

```python
"""Notion embedding pipeline — chunks pages and generates embeddings."""

import logging
from datetime import datetime, timezone

import asyncpg
import httpx

logger = logging.getLogger(__name__)

# Ollama embedding endpoint
_EMBED_TIMEOUT = 30.0


class NotionEmbeddingPipeline:
    """Chunks Notion pages and generates embeddings via Ollama."""

    def __init__(
        self,
        pool: asyncpg.Pool,
        ollama_base_url: str,
        model: str = "nomic-embed-text",
        chunk_size: int = 600,
        chunk_overlap: int = 100,
    ):
        self._pool = pool
        self._ollama_url = ollama_base_url.rstrip("/").removesuffix("/v1")
        self._model = model
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap

    async def embed_pending(self) -> dict:
        """Process all pages that need (re-)embedding.

        Returns stats dict with pages_embedded, chunks_created, errors.
        """
        stats = {"pages_embedded": 0, "chunks_created": 0, "errors": 0}

        rows = await self._pool.fetch("""
            SELECT id, title, content_text
            FROM notion_pages
            WHERE content_text != ''
              AND (embedded_at IS NULL OR embedded_at < synced_at)
            ORDER BY synced_at DESC
            LIMIT 200
        """)

        for row in rows:
            page_id = row["id"]
            try:
                chunks = self._chunk_text(row["content_text"], row["title"])
                if not chunks:
                    continue

                # Delete old embeddings for this page
                await self._pool.execute(
                    "DELETE FROM notion_embeddings WHERE page_id = $1", page_id
                )

                # Generate embeddings and insert
                for idx, chunk_text in enumerate(chunks):
                    embedding = await self._generate_embedding(chunk_text)
                    if embedding is None:
                        stats["errors"] += 1
                        continue
                    await self._pool.execute(
                        """
                        INSERT INTO notion_embeddings (page_id, chunk_index, chunk_text, embedding)
                        VALUES ($1, $2, $3, $4::vector)
                        """,
                        page_id, idx, chunk_text, str(embedding),
                    )
                    stats["chunks_created"] += 1

                # Mark page as embedded
                await self._pool.execute(
                    "UPDATE notion_pages SET embedded_at = NOW() WHERE id = $1",
                    page_id,
                )
                stats["pages_embedded"] += 1

            except Exception:
                logger.exception("Embedding failed for page %s", page_id)
                stats["errors"] += 1

        logger.info(
            "Embedding complete: %d pages, %d chunks, %d errors",
            stats["pages_embedded"],
            stats["chunks_created"],
            stats["errors"],
        )
        return stats

    def _chunk_text(self, text: str, title: str = "") -> list[str]:
        """Split text into overlapping chunks.

        Each chunk is prefixed with the page title for context.
        Uses character-based splitting with paragraph awareness.
        """
        if not text.strip():
            return []

        prefix = f"[{title}] " if title else ""
        paragraphs = text.split("\n")
        chunks = []
        current_chunk = ""

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            # If adding this paragraph exceeds chunk_size, save current and start new
            if len(current_chunk) + len(para) + 1 > self._chunk_size:
                if current_chunk:
                    chunks.append(prefix + current_chunk.strip())
                # Overlap: keep the last N characters
                if self._chunk_overlap > 0 and current_chunk:
                    current_chunk = current_chunk[-self._chunk_overlap :] + "\n" + para
                else:
                    current_chunk = para
            else:
                current_chunk = current_chunk + "\n" + para if current_chunk else para

        # Don't forget the last chunk
        if current_chunk.strip():
            chunks.append(prefix + current_chunk.strip())

        return chunks

    async def _generate_embedding(self, text: str) -> list[float] | None:
        """Call Ollama embedding API for a single text."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self._ollama_url}/api/embed",
                    json={"model": self._model, "input": text},
                    timeout=_EMBED_TIMEOUT,
                )
                response.raise_for_status()
                data = response.json()
                embeddings = data.get("embeddings", [])
                if embeddings:
                    return embeddings[0]
                return None
        except Exception:
            logger.exception("Ollama embedding request failed")
            return None
```

### 6.3 Pipeline Registration (`main.py`)

The embedding pipeline runs **after each sync**:

```python
# In lifespan(), after notion_sync setup:
notion_embedder = None
if settings.feature_notion and settings.notion_token:
    from .sync.notion_embeddings import NotionEmbeddingPipeline
    notion_embedder = NotionEmbeddingPipeline(
        pool=pool,
        ollama_base_url=settings.llm_base_url,
        model=settings.notion_embedding_model,
        chunk_size=settings.notion_chunk_size,
        chunk_overlap=settings.notion_chunk_overlap,
    )

    # Wrap sync + embed as a single scheduled job
    async def notion_sync_and_embed():
        await notion_sync.sync_all()
        await notion_embedder.embed_pending()

    # Replace the pure sync job with sync+embed
    scheduler.add_job(
        notion_sync_and_embed,
        "interval",
        minutes=settings.notion_sync_interval,
        id="notion_sync",
        max_instances=1,
        misfire_grace_time=600,
    )
    asyncio.create_task(notion_sync_and_embed())

app.state.notion_embedder = notion_embedder
```

---

## 7. Retrieval (`actions/notion.py`)

### 7.1 Module: `src/niles/actions/notion.py`

```python
"""Notion RAG retrieval — semantic search over embedded Notion content."""

import logging

import asyncpg
import httpx

logger = logging.getLogger(__name__)

_EMBED_TIMEOUT = 15.0


class NotionRetriever:
    """Retrieves relevant Notion chunks via pgvector similarity search."""

    def __init__(
        self,
        pool: asyncpg.Pool,
        ollama_base_url: str,
        model: str = "nomic-embed-text",
        similarity_threshold: float = 0.3,
    ):
        self._pool = pool
        self._ollama_url = ollama_base_url.rstrip("/").removesuffix("/v1")
        self._model = model
        self._threshold = similarity_threshold

    async def search(self, query: str, max_results: int = 5) -> list[dict]:
        """Semantic search over Notion embeddings.

        Returns list of dicts with keys:
            chunk_text, page_title, page_url, similarity
        """
        # 1. Embed the query
        embedding = await self._generate_embedding(query)
        if embedding is None:
            return []

        # 2. pgvector similarity search
        rows = await self._pool.fetch(
            """
            SELECT
                e.chunk_text,
                e.chunk_index,
                p.title AS page_title,
                p.url AS page_url,
                1 - (e.embedding <=> $1::vector) AS similarity
            FROM notion_embeddings e
            JOIN notion_pages p ON e.page_id = p.id
            WHERE 1 - (e.embedding <=> $1::vector) > $2
            ORDER BY e.embedding <=> $1::vector
            LIMIT $3
            """,
            str(embedding), self._threshold, max_results,
        )

        results = []
        for row in rows:
            results.append({
                "chunk_text": row["chunk_text"],
                "page_title": row["page_title"],
                "page_url": row["page_url"],
                "similarity": round(float(row["similarity"]), 4),
            })

        logger.info(
            "Notion search for '%s': %d results (threshold %.2f)",
            query[:50], len(results), self._threshold,
        )
        return results

    async def _generate_embedding(self, text: str) -> list[float] | None:
        """Call Ollama embedding API for the query text."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self._ollama_url}/api/embed",
                    json={"model": self._model, "input": text},
                    timeout=_EMBED_TIMEOUT,
                )
                response.raise_for_status()
                data = response.json()
                embeddings = data.get("embeddings", [])
                if embeddings:
                    return embeddings[0]
                return None
        except Exception:
            logger.exception("Ollama embedding request failed for query")
            return None
```

### 7.2 Initialization (`main.py`)

```python
notion_retriever = None
if settings.feature_notion and settings.notion_token:
    from .actions.notion import NotionRetriever
    notion_retriever = NotionRetriever(
        pool=pool,
        ollama_base_url=settings.llm_base_url,
        model=settings.notion_embedding_model,
        similarity_threshold=settings.notion_similarity_threshold,
    )
app.state.notion_retriever = notion_retriever
```

---

## 8. Agent Tool (`agent/tools/notion.py`)

### 8.1 Tool Definition (`agent/core.py`)

Add to `TOOLS` list:

```python
{
    "type": "function",
    "function": {
        "name": "search_notion",
        "description": (
            "Durchsucht die Notion-Wissensdatenbank nach relevanten Inhalten. "
            "Nutze dieses Tool wenn der Benutzer nach Informationen fragt, "
            "die in seinen Notion-Seiten stehen koennten (Dokumentation, "
            "Notizen, Projekte, Wikis)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Suchanfrage in natuerlicher Sprache",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximale Anzahl Ergebnisse (1-10, Standard: 5)",
                },
            },
            "required": ["query"],
        },
    },
},
```

### 8.2 Tool Handler (`agent/tools/notion.py`)

```python
"""Notion RAG search tool."""

from . import ToolContext, register_tool


@register_tool("search_notion")
async def handle_search_notion(
    args: dict, chat_id: str, ctx: ToolContext
) -> dict:
    retriever = getattr(ctx, "notion_retriever", None)
    if not retriever:
        return {"error": "Notion-Integration nicht konfiguriert."}

    query = args.get("query", "")
    max_results = min(int(args.get("max_results", 5)), 10)

    results = await retriever.search(query, max_results=max_results)

    if not results:
        return {"message": "Keine relevanten Notion-Inhalte gefunden.", "results": []}

    # Format for LLM context
    formatted = []
    for r in results:
        formatted.append({
            "source": r["page_title"],
            "url": r["page_url"],
            "content": r["chunk_text"],
            "relevance": r["similarity"],
        })

    return {
        "message": f"{len(formatted)} relevante Notion-Abschnitte gefunden.",
        "results": formatted,
    }
```

### 8.3 Registration

Add to `agent/tools/__init__.py`:

```python
from . import notion  # noqa: F401 — register search_notion
```

### 8.4 ToolContext Extension

Add `notion_retriever` to the `ToolContext` dataclass in `agent/tools/__init__.py`:

```python
@dataclass
class ToolContext:
    # ... existing fields ...
    notion_retriever: Any = None  # actions.notion.NotionRetriever
```

And in `NilesAgent._tool_context()`:

```python
notion_retriever=getattr(self, "notion_retriever", None),
```

### 8.5 Registered Tools Table Update

| Tool | Parameters | Description |
|------|-----------|-------------|
| `search_notion` | `query: str, max_results?: int` | Semantic search over Notion knowledge base. Feature flag: `feature_notion`. |

### 8.6 Data Integrity (No Deletions)

Add row to the no-deletion matrix:

| Integration | Read | Create | Modify | Delete |
|-------------|------|--------|--------|--------|
| Notion (API) | Yes | No | No | No |

---

## 9. Web UI

### 9.1 Settings Page (`web/_notion.py`)

New module: `src/niles/sources/web/_notion.py`

Endpoints:

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/notion/status` | Returns connection status, sync stats |
| POST | `/api/notion/connect` | Save token, test connection, trigger initial sync |
| POST | `/api/notion/disconnect` | Remove token, clear notion_pages and notion_embeddings |
| POST | `/api/notion/sync` | Trigger manual sync + embed |

**Settings card in `settings.html`:**

```
Notion (Wissensdatenbank)
├── Status: Verbunden / Nicht konfiguriert
├── Token: [ntn_****] [Connect] / [Disconnect]
├── Letzte Sync: 2026-03-03 14:30 (42 Seiten, 380 Chunks)
├── Sync-Intervall: [30] Minuten
└── [Jetzt synchronisieren]
```

Pattern: Same as `_contacts.py` (CardDAV connect/disconnect with status fragment).

### 9.2 Chat UI — Notion Search Button

**Approach:** Add a toggle button next to the chat input (similar pattern to how `feature_search` could work as a toggle). When active, the user's message is **pre-processed** before being sent to the agent:

1. User types query and clicks "Send" with Notion toggle active
2. Frontend sends `POST /api/notion/search` with the query
3. Backend retrieves top-5 chunks via `NotionRetriever`
4. Chunks are prepended to the user message as context:
   ```
   [Notion-Kontext]
   Quelle: Project Wiki (https://notion.so/...)
   > Relevant content chunk here...

   Quelle: Meeting Notes (https://notion.so/...)
   > Another relevant chunk...

   [Frage]
   User's original question
   ```
5. The enriched message is sent to the normal `/chat` endpoint
6. The LLM receives the Notion context and can answer based on it

**Alternative approach (simpler):** No special button — rely entirely on the `search_notion` agent tool. The LLM decides when to search Notion based on the query. This is simpler but less reliable with 8B models.

**Recommendation:** Implement both. The button provides a deterministic "always search Notion" path. The agent tool provides an automatic "search when relevant" path. The button is more important for reliability.

**Endpoint:**

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/notion/search` | Direct search, returns formatted chunks as JSON |

```python
@router.post("/api/notion/search")
async def notion_search(request: Request, query: str = Form(...)):
    """Direct Notion search (bypasses LLM tool selection)."""
    retriever = request.app.state.notion_retriever
    if not retriever:
        raise HTTPException(404, "Notion not configured")
    results = await retriever.search(query, max_results=5)
    return {"results": results}
```

### 9.3 UI Element (chat.html)

Add a toggle button in the chat input area:

```html
<!-- Notion context toggle (next to send button) -->
<button id="notion-toggle"
        class="px-2 py-1 text-xs rounded border
               {% if feature_notion %}
               border-purple-400 text-purple-600 hover:bg-purple-50
               {% else %}hidden{% endif %}"
        title="Notion-Kontext einbeziehen"
        onclick="toggleNotionContext(this)">
    📚 Notion
</button>
```

When toggled on (active state with filled background), the JavaScript in `app.js` intercepts the send action:

1. Call `/api/notion/search` with the query
2. Prepend results to the message
3. Submit enriched message to `/chat`

---

## 10. Testing

### 10.1 Test Files

| File | Coverage |
|------|----------|
| `tests/test_notion_sync.py` | NotionSync: discover, content extraction, MD5 change detection, upsert |
| `tests/test_notion_embeddings.py` | Chunking logic, embedding pipeline, pending detection |
| `tests/test_notion_retriever.py` | Search, threshold filtering, empty results |
| `tests/test_notion_tool.py` | Agent tool handler, feature flag, error cases |
| `tests/test_notion_web.py` | Web endpoints: connect, disconnect, status, search |

### 10.2 Test Approach

- Mock `notion_client.AsyncClient` for API calls
- Mock Ollama embedding endpoint (`httpx` responses)
- Use real `asyncpg` fixtures for database tests (or mock `pool.fetch`/`pool.execute`)
- Test chunking logic with various text lengths and edge cases
- Test MD5 change detection (no unnecessary re-embedding)
- Test pgvector queries with known embedding vectors

### 10.3 Example Test

```python
class TestNotionSync:
    async def test_block_to_text_paragraph(self):
        block = {
            "type": "paragraph",
            "paragraph": {
                "rich_text": [
                    {"plain_text": "Hello "},
                    {"plain_text": "World"},
                ]
            },
        }
        assert NotionSync._block_to_text(block) == "Hello World"

    async def test_block_to_text_unsupported_type(self):
        block = {"type": "image", "image": {}}
        assert NotionSync._block_to_text(block) == ""

    async def test_extract_title_from_page(self):
        page = {
            "object": "page",
            "properties": {
                "Name": {
                    "type": "title",
                    "title": [{"plain_text": "My Page"}],
                }
            },
        }
        assert NotionSync._extract_title(page) == "My Page"
```

---

## 11. Deployment Changes

### 11.1 Docker Image (`docker-compose.yml`)

Replace PostgreSQL image to include pgvector:

```yaml
evolution_postgres:
  image: pgvector/pgvector:pg15    # was: postgres:15
  # ... rest unchanged
```

### 11.2 Ollama Model

Add to deployment guide (post-start):

```bash
ollama pull nomic-embed-text
```

### 11.3 .env Changes

```bash
# Add to .env:
FEATURE_NOTION=true
NOTION_TOKEN=ntn_your_integration_secret_here
```

---

## 12. Implementation Plan

### Phase 1: Foundation (config, dependencies, Docker, migration)

#### 1.1 `pyproject.toml` — add dependency
- Add `"notion-client>=2.0.0"` to `dependencies`

#### 1.2 `docker/docker-compose.yml` — pgvector image + env vars
- Replace `postgres:15-alpine@sha256:...` → `pgvector/pgvector:pg15`
- Add to `niles_core` environment block: `FEATURE_NOTION`, `NOTION_TOKEN`, `NOTION_SYNC_INTERVAL`, `NOTION_EMBEDDING_MODEL`

#### 1.3 `.env.example` — new section
- Add commented `NOTION_TOKEN`, `FEATURE_NOTION`, `NOTION_SYNC_INTERVAL`, `NOTION_EMBEDDING_MODEL`

#### 1.4 `src/niles/config.py` — 7 new settings fields
- Add after `searxng_url`: `notion_token`, `notion_sync_interval`, `notion_embedding_model`, `notion_chunk_size`, `notion_chunk_overlap`, `notion_similarity_threshold`, `feature_notion`

#### 1.5 `src/niles/settings_store.py` — EDITABLE_SETTINGS
- Add all 7 notion fields to the `EDITABLE_SETTINGS` set

#### 1.6 `alembic/versions/003_add_notion_rag.py` — new migration
- `CREATE EXTENSION IF NOT EXISTS vector`
- `notion_pages` table (id TEXT PK, title, parent_id, object_type, content_text, content_md5, url, last_edited, synced_at, embedded_at)
- `notion_embeddings` table (id SERIAL PK, page_id FK→notion_pages CASCADE, chunk_index, chunk_text, embedding vector(768), created_at; UNIQUE(page_id, chunk_index))
- Indexes: parent_id, needs-embedding partial, ivfflat vector_cosine_ops (lists=100)
- `down_revision = "002"`

### Phase 2: Sync + Embedding Pipeline (new files)

#### 2.1 `src/niles/sync/notion.py` — NotionSync class
- Pattern: follows `sync/carddav.py` (constructor with pool + credentials, async methods)
- `__init__(pool, token)` — creates `notion_client.AsyncClient(auth=token)`
- `sync_all() -> dict` — discover pages via search API, fetch block content recursively, MD5 change detection, upsert into `notion_pages`, mark changed pages for re-embedding
- `test_connection() -> tuple[bool, str]` — single search call to verify API access
- Helper methods: `_discover_pages`, `_sync_page`, `_fetch_page_content` (recursive, max depth 5), `_block_to_text`, `_extract_title`, `_extract_parent_id`

#### 2.2 `src/niles/sync/notion_embeddings.py` — NotionEmbeddingPipeline class
- `__init__(pool, ollama_base_url, model, chunk_size, chunk_overlap)`
- `embed_pending() -> dict` — query pages needing embedding, chunk text, call Ollama `/api/embed`, insert vectors
- `_chunk_text(text, title) -> list[str]` — paragraph-aware splitting with overlap, title prefix per chunk
- `_generate_embedding(text) -> list[float] | None` — httpx POST to Ollama

### Phase 3: Retrieval + Agent Tool

#### 3.1 `src/niles/actions/notion.py` — NotionRetriever class (new file)
- `__init__(pool, ollama_base_url, model, similarity_threshold)`
- `search(query, max_results=5) -> list[dict]` — embed query, pgvector cosine similarity search, return `{chunk_text, page_title, page_url, similarity}`

#### 3.2 `src/niles/agent/tools/notion.py` — search_notion handler (new file)
- `@register_tool("search_notion")` with standard signature `(args, chat_id, ctx) -> dict`
- Gets `ctx.notion_retriever`, calls `search()`, formats results

#### 3.3 `src/niles/agent/tools/__init__.py` — two changes
- Add `notion_retriever: Any = None` to `ToolContext` dataclass
- Add `notion` to the side-effect import line

#### 3.4 `src/niles/agent/core.py` — two changes
- Add `search_notion` tool definition to `TOOLS` list (before closing `]`)
- Add `notion_retriever=getattr(self, "notion_retriever", None)` to `_tool_context()`

#### 3.5 `src/niles/agent/context.py` — conditional tool filtering
- After the Signal tool filter, add filter to remove `search_notion` when `feature_notion` is disabled. Pattern: same as Vikunja/Signal filters above it.

### Phase 4: Lifespan Wiring

#### 4.1 `src/niles/main.py` — initialize Notion components
- After `scheduler.start()`, add feature-gated block:
  - Create `NotionSync`, `NotionEmbeddingPipeline`, `NotionRetriever`
  - Define `notion_sync_and_embed()` wrapper
  - Register interval scheduler job (`notion_sync`, misfire_grace_time=600)
  - Fire initial sync via `asyncio.create_task()`
  - Wire retriever into agent: `agent.notion_retriever = notion_retriever`
- Add to `app.state`: `notion_sync`, `notion_embedder`, `notion_retriever`

#### 4.2 `src/niles/types.py` — extend AppState protocol
- Add TYPE_CHECKING imports for `NotionSync`, `NotionEmbeddingPipeline`, `NotionRetriever`
- Add 3 optional fields to `AppState`

### Phase 5: Web UI

#### 5.1 `src/niles/sources/web/_notion.py` — new module
- Follow `_contacts.py` connect/disconnect pattern exactly
- Endpoints:
  - `GET /api/notion/status` — returns fragment with connection state, page/chunk counts, last sync
  - `POST /api/notion/connect` — takes token, tests connection, persists settings, creates instances, registers scheduler job, triggers initial sync, wires retriever into agent
  - `POST /api/notion/disconnect` — removes settings, DELETE FROM both tables, removes scheduler job, sets agent.notion_retriever = None
  - `POST /api/notion/sync` — triggers manual sync+embed
  - `POST /api/notion/search` — direct search endpoint for chat toggle (returns JSON)

#### 5.2 `src/niles/sources/web/__init__.py` — register module
- Add `_notion` to side-effect imports
- Add re-exports for the 5 route functions

#### 5.3 `src/niles/templates/fragments/notion_status.html` — new fragment
- Two-state template (connected vs. disconnected), following `carddav_status.html` pattern
- Connected: masked token, page count, chunk count, last sync, Sync/Disconnect buttons
- Disconnected: token input + Connect button

#### 5.4 `src/niles/templates/settings.html` — add Notion card
- New card section between "Kontakte (CardDAV)" and "ADMINISTRATION" divider
- `hx-get="/ui/api/notion/status"` with `hx-trigger="load"` for status fragment

#### 5.5 `src/niles/sources/web/_core.py` — settings dict
- Add `"feature_notion"` to `_safe_settings_dict()` return

#### 5.6 `src/niles/sources/web/_chat.py` — notion_search param + context injection
- Add `notion_search: bool = Form(default=False)` parameter to `chat_stream()`
- Guard: `if not settings.feature_notion: notion_search = False`
- When `notion_search=True`: pre-fetch top-5 chunks via `NotionRetriever.search()`, prepend as `[Notion-Kontext]` block to user message before passing to agent
- Pass `feature_notion` to chat template context in `chat_page()`

#### 5.7 `src/niles/templates/chat.html` — Notion toggle button
- Add after web search toggle, before send button
- Same pattern: `data-notion-toggle`, `aria-pressed`, hidden input `notion_search=false`
- Book icon SVG, gated by `{% if feature_notion %}`

#### 5.8 `src/niles/static/js/app.js` — toggle handler
- Add click handler for `[data-notion-toggle]` (same pattern as web search toggle)
- Include `notion_search` parameter in stream request

### Phase 6: Tests

#### New test files:

| File | Covers |
|------|--------|
| `tests/test_notion_sync.py` | Block-to-text extraction, title extraction, MD5 change detection, page upsert, pagination, recursive content, test_connection |
| `tests/test_notion_embeddings.py` | Chunking (short/long/empty/overlap/title prefix), embed pipeline, Ollama error handling, old embeddings deleted |
| `tests/test_notion_retriever.py` | Search happy path, threshold filtering, empty results, embedding failure, max_results |
| `tests/test_notion_tool.py` | Tool handler success/no-retriever/no-results/max-results-cap |
| `tests/test_notion_web.py` | Status/connect/disconnect/sync/search endpoints (mock Request pattern from test_web.py) |

#### Mocking strategy:
- **Notion API**: Mock `notion_client.AsyncClient` (search, blocks.children.list)
- **Ollama**: Mock `httpx.AsyncClient` POST responses with fake 768-dim vectors
- **Database**: Mock `asyncpg.Pool` with `AsyncMock`
- **Chunking**: Pure function tests, no mocking

### Phase 7: Documentation

- `docs/Niles-Core-Spec.md` — add `search_notion` to tools table, Notion to components, new settings
- `docs/Deployment.md` — Notion setup section (integration token, `ollama pull nomic-embed-text`)
- `docs/LEGAL.md` — `notion-client` MIT license, Notion API terms
- `README.md` — features list + stack table

### Files Summary

**New files (13):**
- `src/niles/sync/notion.py`
- `src/niles/sync/notion_embeddings.py`
- `src/niles/actions/notion.py`
- `src/niles/agent/tools/notion.py`
- `src/niles/sources/web/_notion.py`
- `src/niles/templates/fragments/notion_status.html`
- `alembic/versions/003_add_notion_rag.py`
- `tests/test_notion_sync.py`
- `tests/test_notion_embeddings.py`
- `tests/test_notion_retriever.py`
- `tests/test_notion_tool.py`
- `tests/test_notion_web.py`

**Modified files (16):**
- `pyproject.toml`
- `docker/docker-compose.yml`
- `.env.example`
- `src/niles/config.py`
- `src/niles/settings_store.py`
- `src/niles/agent/tools/__init__.py`
- `src/niles/agent/core.py`
- `src/niles/agent/context.py`
- `src/niles/main.py`
- `src/niles/types.py`
- `src/niles/sources/web/__init__.py`
- `src/niles/sources/web/_core.py`
- `src/niles/sources/web/_chat.py`
- `src/niles/templates/settings.html`
- `src/niles/templates/chat.html`
- `src/niles/static/js/app.js`

### Verification

1. **Unit tests**: `pytest tests/test_notion_*.py -v` — all 5 new test files pass
2. **Full suite**: `pytest tests/ -v` — no regressions in existing 586 tests
3. **Migration**: Start postgres with pgvector image, run `alembic upgrade head`, verify tables + extension exist
4. **Integration** (manual, with real Notion token):
   - Set `FEATURE_NOTION=true` + `NOTION_TOKEN=ntn_...` in `.env`
   - Start app, verify initial sync runs (check logs)
   - Open Settings → Notion card shows connected status with page count
   - Open Chat → Notion toggle visible, ask question about Notion content
   - Verify search results appear in agent response
5. **Ruff**: `ruff check src/niles/ tests/` — no lint errors

---

## 13. Future Considerations (Out of Scope)

- **Notion MCP for write access** — Add `@notionhq/notion-mcp-server` as MCP server in `mcp_servers.yaml` for creating/editing pages. Separate feature flag.
- **Incremental sync** — Use Notion's `last_edited_time` filter to only fetch recently changed pages instead of full search.
- **Database row content** — Currently, database rows are fetched as pages. Structured database queries (filter, sort) could be added as a separate tool.
- **Multi-workspace** — Support multiple Notion integrations (different tokens per user).
- **Embedding model hot-swap** — When changing the embedding model, automatically trigger full re-embedding of all pages.
- **Hybrid search** — Combine pgvector similarity with PostgreSQL full-text search (`tsvector`) for better results on exact keyword matches.