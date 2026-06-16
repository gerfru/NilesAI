# Retrieval-Augmented Generation (RAG)

> **Version:** 1.0
> **Updated:** 2026-03-12

This document covers both **general RAG concepts** (Section 1--2) and the **Niles-specific implementation** (Section 3--6). It serves as a reference for understanding why specific design choices were made and how the pipeline works end-to-end.

---

## Table of Contents

1. [Introduction](#1-introduction)
2. [RAG Pipeline -- Fundamentals](#2-rag-pipeline----fundamentals)
3. [Niles Implementation](#3-niles-implementation)
4. [Design Decisions & Trade-offs](#4-design-decisions--trade-offs)
5. [Configuration Reference](#5-configuration-reference)
6. [Troubleshooting](#6-troubleshooting)

---

## 1. Introduction

### 1.1 What is RAG?

Retrieval-Augmented Generation combines a **retrieval system** (finding relevant documents) with a **generative model** (producing answers). Instead of relying solely on the LLM's training data, RAG fetches real-time context from a knowledge base and injects it into the prompt.

```text
User Query
    |
    v
[Retrieval] --> Find relevant documents from knowledge base
    |
    v
[Augmentation] --> Inject retrieved context into LLM prompt
    |
    v
[Generation] --> LLM produces grounded answer with sources
```

### 1.2 Why RAG?

Three main approaches exist for giving an LLM domain knowledge:

| Approach | Pros | Cons | Best For |
|----------|------|------|----------|
| **Prompting** | Zero cost, instant | Limited context window, no updates | Static, small knowledge |
| **Fine-tuning** | Deep knowledge integration | Expensive, needs retraining, hallucination risk | Style/behavior changes |
| **RAG** | Always current, verifiable sources, no retraining | Retrieval quality matters, added complexity | Dynamic knowledge bases |

RAG is the right choice when:
- Knowledge changes frequently (wiki pages, notes, docs)
- Users need verifiable sources (links back to originals)
- Privacy requires local processing (no data sent to cloud for training)
- The knowledge base is too large for the context window

### 1.3 The RAG Pipeline

Every RAG system follows the same high-level pipeline:

```text
Data Source --> Ingest --> Chunk --> Embed --> Store --> Retrieve --> Inject --> Generate
```

Each step has multiple strategies with different trade-offs. The following sections cover each step in detail.

---

## 2. RAG Pipeline -- Fundamentals

### 2.1 Data Ingestion

Data ingestion connects the knowledge source to the RAG pipeline. The key decisions are *what* to ingest and *when* to re-ingest.

**Source types:**

| Source | Method | Example |
|--------|--------|---------|
| APIs | Poll or webhook | Notion API, Confluence API |
| Files | File watcher or scan | Markdown files, PDFs |
| Databases | Change data capture | PostgreSQL logical replication |
| Web | Crawl | Sitemap-based crawling |

**Change detection strategies:**

| Strategy | Freshness | Complexity | Best For |
|----------|-----------|------------|----------|
| **Polling + hash** | Minutes | Low | APIs without webhooks |
| **Webhooks** | Real-time | Medium | Services that support them |
| **Last-modified timestamp** | Minutes | Low | File systems, APIs with timestamps |
| **Full re-sync** | On-demand | Lowest | Small datasets, initial loads |

### 2.2 Chunking

Chunking splits documents into pieces small enough to embed meaningfully. The chunking strategy has the single largest impact on retrieval quality.

#### Strategies

**Fixed-size (character/token based)**

Split text at every N characters or tokens, optionally with overlap.

```text
[chunk 1: chars 0-500] [chunk 2: chars 400-900] [chunk 3: chars 800-1300]
                        ↑ overlap
```

- Pros: Simple, predictable chunk sizes, uniform embedding dimensions
- Cons: Splits mid-sentence, ignores document structure
- Best for: Unstructured text, log files, transcripts

**Recursive splitting**

Try splitting by paragraph first, then sentence, then character. Popular in LangChain.

- Pros: Respects natural text boundaries better than fixed-size
- Cons: Variable chunk sizes, still structure-unaware
- Best for: Prose documents, articles, emails

**Semantic splitting**

Use embeddings to detect meaning shifts. Split where consecutive sentences have low similarity.

- Pros: Semantically coherent chunks
- Cons: Expensive (requires embedding every sentence), unpredictable sizes
- Best for: Long documents with topic changes, research papers

**Document-structure-aware**

Use the document's own structure (headings, sections, HTML tags) as split boundaries.

```text
# Setup          --> Section 1 (with heading context)
Install deps...

## Configuration --> Section 2 (inherits # Setup context)
Edit config...

# Usage          --> Section 3 (new top-level context)
Run the app...
```

- Pros: Natural boundaries, heading context for retrieval, preserves author's structure
- Cons: Requires structured input (Markdown, HTML), variable chunk sizes
- Best for: Wiki pages, documentation, Notion content, structured notes

#### Overlap

Overlap copies the last N characters of chunk K into the beginning of chunk K+1. This prevents information loss at chunk boundaries.

- Too little overlap (0): Hard cuts lose context
- Too much overlap (>30%): Redundant embeddings, wasted storage
- Sweet spot: 15--20% of chunk size

#### Hierarchical chunking

Instead of one chunk level, create two:

- **Level 0 (summary):** One LLM-generated summary per page (broad context)
- **Level 1 (detail):** Fine-grained chunks (specific information)

At retrieval time, both levels compete. When a detail chunk matches, its page's summary chunk gets a small boost -- providing broader context alongside the specific match.

#### Decision guide

| Data Type | Recommended Strategy | Chunk Size | Overlap |
|-----------|---------------------|------------|---------|
| Wiki / Notion pages | Document-structure-aware | 400--800 chars | 100 chars |
| Plain text / transcripts | Recursive or fixed-size | 500--1000 chars | 100--200 chars |
| Code files | AST-based or function-level | Per function | None |
| PDFs (unstructured) | Fixed-size with sentence boundaries | 500--800 chars | 100 chars |
| Chat logs | Message-based (per turn or group) | Per conversation | None |
| Research papers | Section-based (abstract, methods, results) | Per section | 100 chars |

### 2.3 Embedding

Embeddings convert text into dense numerical vectors where semantically similar texts are close together in vector space.

#### How it works

```text
"How to install Python" --> [0.12, -0.34, 0.56, ..., 0.78]  (768 dimensions)
"Python setup guide"    --> [0.11, -0.33, 0.55, ..., 0.77]  (similar vector)
"Recipe for pizza"      --> [0.89, 0.12, -0.67, ..., -0.23] (different vector)
```

Similarity is measured by cosine distance: 1.0 = identical, 0.0 = unrelated.

#### Model comparison

| Model | Dimensions | Local | Cost | Quality |
|-------|-----------|-------|------|---------|
| nomic-embed-text | 768 | Yes (Ollama) | Free | Good for general text |
| all-MiniLM-L6-v2 | 384 | Yes (SBERT) | Free | Fast, lower quality |
| text-embedding-3-small | 1536 | No (OpenAI) | $0.02/1M tokens | High quality |
| text-embedding-3-large | 3072 | No (OpenAI) | $0.13/1M tokens | Highest quality |
| Cohere embed-v3 | 1024 | No (Cohere) | $0.10/1M tokens | Multi-language |

Key trade-offs:
- **Dimensions:** Higher = more nuanced but more storage. 768 is the sweet spot for local models.
- **Local vs. cloud:** Local is free and private but slower. Cloud is fast but costs money and sends data externally.
- **Task prefixes:** Some models (nomic-embed-text, E5) require prefixes like `"search_document: "` for indexing and `"search_query: "` for queries. This tells the model whether the text is a document to be found or a question looking for answers. Omitting prefixes degrades quality significantly.

#### Batch vs. single embedding

- **Single:** Embed one text at a time. Simpler, lower memory, higher latency per batch.
- **Batch:** Embed many texts in one request. Higher throughput, better GPU utilization.
- For indexing pipelines: batch is preferred (process hundreds of chunks).
- For query time: single is fine (one query at a time).

### 2.4 Vector Storage

Vector databases store embeddings and enable fast similarity search.

#### Options

| Type | Examples | Pros | Cons |
|------|----------|------|------|
| **Purpose-built** | Pinecone, Weaviate, Qdrant, Milvus | Optimized for vectors, rich features | Extra infrastructure to manage |
| **DB extensions** | pgvector (PostgreSQL), sqlite-vss | Reuse existing DB, SQL joins | Fewer vector-specific features |
| **In-memory** | FAISS, Annoy | Fastest retrieval | No persistence, RAM-limited |

**Decision:** If you already run PostgreSQL, pgvector eliminates an entire service from your stack. For <100k vectors, the performance difference is negligible.

#### Index types (pgvector)

| Index | Build Time | Query Speed | Recall | Best For |
|-------|-----------|-------------|--------|----------|
| **Flat** (no index) | None | Slow (exact) | 100% | <10k vectors, development |
| **IVFFlat** | Fast | Fast | 80--95% (depends on `probes`) | 10k--1M, when you can tune `probes` |
| **HNSW** | Slow | Fast | 95--99% | Any size, best default choice |

IVFFlat partitions vectors into `lists` clusters and only searches `probes` of them at query time. With default `probes=1` and `lists=100`, only 1% of vectors are searched -- missing most results. HNSW (Hierarchical Navigable Small World) builds a multi-layer graph and provides consistently high recall without parameter tuning.

**Recommendation:** Use HNSW unless you have a specific reason not to. The slightly slower build time is a one-time cost, and the query-time recall is dramatically better than IVFFlat with default settings.

### 2.5 Retrieval

Retrieval finds the most relevant chunks for a user query.

#### Strategies

**Pure vector search (semantic)**

Embed the query, find nearest neighbors by cosine similarity.

- Pros: Understands meaning, handles paraphrases
- Cons: Weak on exact names/titles, typo-sensitive
- Best for: Natural language questions, conceptual queries

**Keyword search (lexical)**

Traditional full-text search (BM25, PostgreSQL `tsvector`).

- Pros: Exact term matching, handles named entities well
- Cons: No semantic understanding, misses paraphrases
- Best for: Searching for specific terms, product names, code identifiers

**Hybrid search**

Combine vector and keyword scores. Two common fusion methods:

- **Reciprocal Rank Fusion (RRF):** Merge ranked lists from both methods
- **Weighted sum:** `score = α * vector_score + (1-α) * keyword_score`

- Pros: Best of both worlds
- Cons: More complex, needs score calibration
- Best for: Production systems with mixed query types

**Lightweight hybrid: post-retrieval keyword boost**

A simpler alternative to full hybrid search. Run vector search first, then boost results whose metadata (title, headings) matches query keywords.

```text
Vector search --> Top 15 candidates --> Keyword boost on metadata --> Re-rank --> Top 5
```

- Pros: No second index needed, minimal complexity, works well for structured metadata
- Cons: Only boosts results already in the candidate set
- Best for: Structured documents with meaningful titles, small-to-medium collections

**Reranking**

Use a cross-encoder model as a second-stage ranker. More accurate but slower.

- Pros: Highest accuracy, considers query-document interaction
- Cons: Slow (can't be pre-computed), requires additional model
- Best for: High-stakes search, when top-1 accuracy matters

#### Decision guide

| Query Type | Best Approach |
|-----------|---------------|
| "What is X?" (conceptual) | Pure vector |
| "Find the Mindset page" (named entity) | Keyword or hybrid |
| Mixed queries, production use | Hybrid or vector + keyword boost |
| High-stakes, accuracy-critical | Hybrid + reranking |

### 2.6 Context Injection (Prompt Engineering)

The final step injects retrieved chunks into the LLM prompt.

#### Key considerations

**Relevance filtering:** Don't inject chunks below a similarity threshold. Low-quality context confuses the LLM more than no context.

**Ordering:** Present chunks sorted by relevance (highest first). LLMs attend more to the beginning and end of context.

**Source attribution:** Include source URLs/titles so the LLM can cite them. This makes answers verifiable.

**Prompt design:**

| Style | Example | Trade-off |
|-------|---------|-----------|
| **Strict** | "Answer ONLY from the provided context." | Fewer hallucinations, may refuse valid questions |
| **Soft** | "Base your answer on the provided context." | More helpful, slightly higher hallucination risk |
| **Guided** | "Use the context. If nothing is relevant, say so." | Best balance for most use cases |

---

## 3. Niles Implementation

### 3.1 Architecture Overview

```text
Notion API
    |
    v
[Sync]                      src/niles/sync/notion.py
  MD5 change detection
  Page hierarchy crawl
    |
    v
notion_pages table          PostgreSQL
    |
    v
[Chunk]                     src/niles/sync/notion_embeddings.py
  Markdown-aware splitting
  Heading hierarchy tracking
  Breadcrumb prefixing
  Code block masking
    |
    v
[Embed]                     src/niles/sync/ollama_embedder.py
  Ollama + nomic-embed-text-v2-moe
  768-dim vectors
  Task prefixes
    |
    v
notion_embeddings table     PostgreSQL + pgvector
  HNSW index
    |
    v
[Retrieve]                  src/niles/actions/notion.py
  Cosine similarity search
  Auto-merge scoring
  Keyword boost
  Per-page deduplication
    |
    v
[Inject]                    src/niles/sources/web/_chat.py
  Context formatting
  Source attribution
    |
    v
[Generate]                  Ollama LLM (llama3.1:8b)
  Grounded answer
  Markdown source links
```

### 3.2 Data Ingestion

**Module:** `src/niles/sync/notion.py` -- `NotionSync`

The sync module connects to Notion via Internal Integration Token and crawls the page hierarchy recursively.

**Change detection:** MD5 hash of page content. Each synced page gets a `content_md5` in the `notion_pages` table. On re-sync, the hash is compared -- unchanged pages skip re-embedding.

**Storage:** `notion_pages` table with columns:
- `id` (Notion page UUID), `title`, `parent_id` (for hierarchy)
- `content_text` (extracted plain text with markdown structure)
- `content_md5` (for change detection)
- `synced_at`, `embedded_at` (for tracking pipeline state)
- `url` (for source attribution in search results)

**Scheduling:** Auto-sync runs on a configurable interval via `APScheduler`. Manual sync can be triggered from the Settings UI.

### 3.3 Chunking

**Module:** `src/niles/sync/notion_embeddings.py` -- `NotionEmbeddingPipeline`

Niles uses **document-structure-aware chunking** because Notion pages are inherently structured with headings.

**Pipeline:**

1. **`_split_by_headings(text)`** -- Split on `# / ## / ###` lines into sections. Track heading hierarchy so `## Sub` under `# Main` gets context `"# Main > ## Sub"`. Code blocks are masked (`_mask_code_blocks`) so bash comments like `# install deps` don't trigger false splits.

2. **`_split_section(body)`** -- Within each section, split by paragraph boundaries respecting `chunk_size` with `chunk_overlap`. These are configurable via the `notion_chunk_size` (default: 600 chars) and `notion_chunk_overlap` (default: 100 chars) settings; the `NotionEmbeddingPipeline.__init__` only supplies the fallback defaults. No overlap across section boundaries.

3. **Prefix each chunk** with breadcrumb context: `[Wiki > Setup > # Installation] actual content here`

4. **Filter junk** -- `_is_useful_chunk()` drops chunks that are mostly ASCII art or box-drawing characters (alphanumeric ratio < 40%).

**Output:** `ChunkInfo(text, page_title, heading_context)` -- structured metadata carried through the pipeline.

**Breadcrumbs:** `_build_breadcrumbs()` walks up to 2 ancestors via `parent_id` to build page hierarchy context. Example: page "Installation" under "Migration Guide" under "ThemisEcho" gets breadcrumb `"ThemisEcho > Migration Guide > Installation"`.

**Hierarchical levels:**
- **Level 0 (summary):** If a `NotionSummarizer` is configured, pages longer than 100 chars get an LLM-generated 2--4 sentence summary. This provides broad page context for retrieval.
- **Level 1 (detail):** Fine-grained chunks as described above. Always generated.

### 3.4 Embedding

**Module:** `src/niles/sync/ollama_embedder.py` -- `OllamaEmbedder`

- **Model:** `nomic-embed-text-v2-moe` running locally via Ollama
- **Dimensions:** 768
- **Connection:** Persistent `httpx.AsyncClient` for connection pooling. The embedder reuses the `llm_base_url` setting (there is no separate `OLLAMA_BASE_URL`) and calls the `/api/embed` endpoint, e.g. `http://host.docker.internal:11434/api/embed`

**Task prefixes** (required by nomic-embed-text-v2-moe for optimal retrieval):
- `"search_document: "` -- prepended when indexing chunks
- `"search_query: "` -- prepended when embedding user queries

**Metadata columns:** Each embedding row stores `page_title` and `heading_context` alongside the vector. This enables keyword-based scoring at retrieval time without a second index.

### 3.5 Vector Storage

**Database:** PostgreSQL 15 with `pgvector` extension

**Table:** `notion_embeddings`

| Column | Type | Purpose |
|--------|------|---------|
| `id` | SERIAL | Surrogate primary key |
| `page_id` | TEXT | FK to notion_pages |
| `chunk_level` | SMALLINT | 0 = summary, 1 = detail |
| `chunk_index` | INT | Position within page |
| `chunk_text` | TEXT | Full chunk with prefix |
| `embedding` | VECTOR(768) | nomic-embed-text-v2-moe vector |
| `page_title` | TEXT | Breadcrumb for keyword boost |
| `heading_context` | TEXT | Heading hierarchy for keyword boost |
| `created_at` | TIMESTAMPTZ | For freshness tracking |

**Primary key:** `id SERIAL PRIMARY KEY`. The tuple `(page_id, chunk_level, chunk_index)` is a UNIQUE constraint (upsert-safe), not the primary key.

**Index:** HNSW with `m=16, ef_construction=64` using cosine distance operator (`vector_cosine_ops`).

Why HNSW over IVFFlat: During development, the original IVFFlat index with `lists=100` and default `probes=1` caused the retriever to miss 99% of results. HNSW provides >95% recall without parameter tuning.

### 3.6 Retrieval & Scoring

**Module:** `src/niles/actions/notion.py` -- `NotionRetriever`

The retriever uses a **multi-stage scoring pipeline** combining vector similarity with structural metadata boosts.

**Step 1 -- Vector search:**
```sql
SELECT ... , 1 - (embedding <=> $1::vector) AS similarity
FROM notion_embeddings
WHERE 1 - (embedding <=> $1::vector) > $threshold
ORDER BY embedding <=> $1::vector
LIMIT $internal_limit
```

- Threshold: 0.30 (configurable)
- Internal limit: `max_results * 3` (over-fetches for scoring headroom)

**Step 2 -- Keyword extraction:**

`_extract_keywords(query)` strips German and English stop words, punctuation, and short tokens (<2 chars). Example: `"was steht unter Mindset?"` → `["mindset"]`.

**Step 3 -- Composite scoring:**

Four additive boosts, applied on top of the base cosine similarity:

| Boost | Value | Trigger |
|-------|-------|---------|
| Multi-hit | +0.05 | 2+ detail chunks from same page in results |
| Summary | +0.03 | Summary chunk has detail hits from same page |
| Title keyword | +0.15 | Query keyword found in `page_title` |
| Heading keyword | +0.08 | Query keyword found in `heading_context` |

Boosts stack additively and are capped at 1.0.

Example: Query `"was steht unter Mindset?"` with keyword `["mindset"]` hitting a page titled "Mindset":
- Base vector similarity: 0.31
- Title keyword boost: +0.15
- Final score: 0.46 (now ranks above an unrelated page at 0.45)

**Step 4 -- Per-page deduplication:**

Maximum per page: 1 summary + 2 detail chunks. Prevents one long page from dominating all result slots.

**Step 5 -- Return top N results** with `chunk_text`, `page_title`, `page_url`, `similarity`.

### 3.7 Context Injection

**Module:** `src/niles/sources/web/_chat.py`

When Notion search returns results, the chat handler:

1. Strips the `[breadcrumb > heading]` prefix from chunk text (presented separately)
2. Formats each result with source link, section heading, and relevance score
3. Wraps everything in a `[Notion-Kontext]` block
4. Uses a **guided prompt style** (see `src/niles/agent/prompts.py`):
   - "Base your answer on the provided Notion sections"
   - "If no section is relevant, say so"
   - "Cite sources as Markdown links"

---

## 4. Design Decisions & Trade-offs

### Why pgvector instead of a dedicated vector DB?

Niles already runs PostgreSQL for all other data. Adding Pinecone or Qdrant would mean another service to manage, another failure point, and another backup to maintain. For <100k vectors, pgvector with HNSW performs well enough. The trade-off is fewer vector-specific features (no built-in filtering, no automatic sharding).

### Why local embedding instead of cloud APIs?

Privacy is a core principle. Notion pages contain personal notes, work documents, and private information. Sending this to OpenAI or Cohere for embedding would violate the "100% local" guarantee. The quality difference between nomic-embed-text-v2-moe (768d, local) and text-embedding-3-small (1536d, cloud) exists but is acceptable for a personal knowledge base.

### Why keyword boost instead of full hybrid search?

Full hybrid would require a second index (`tsvector` + GIN) and score fusion logic. The keyword boost approach is simpler: it only runs on the ~15 candidates already returned by vector search, checking if query keywords appear in the structured `page_title` and `heading_context` columns. This solves the specific problem (named entity queries like "Mindset") without the complexity of maintaining a parallel retrieval path.

**Upgrade path:** If the knowledge base grows significantly, the existing `page_title` and `heading_context` TEXT columns can be replaced with a `tsvector GENERATED ALWAYS AS (...)` column + GIN index for SQL-side full-text search.

### Why document-structure-aware chunking?

Notion content is inherently structured with headings. Using fixed-size chunking would discard this structure, splitting mid-section and losing the heading context that makes chunks retrievable. Markdown-aware splitting preserves the author's organization and embeds heading hierarchy into each chunk's context prefix.

### Why HNSW instead of IVFFlat?

IVFFlat with default settings (`probes=1`) only searches 1 out of N clusters. During development, this caused the retriever to miss the correct result entirely (Mindset page not found despite 0.55 similarity). HNSW provides consistently high recall (>95%) without requiring `probes` tuning. The trade-off is slower index builds, but for <20k vectors this is negligible.

---

## 5. Configuration Reference

| Setting | Default | Description |
|---------|---------|-------------|
| `NOTION_TOKEN` | -- | Internal Integration Token (required) |
| `llm_base_url` | `http://host.docker.internal:11434` | Ollama API endpoint (shared with the LLM; the embedder appends `/api/embed`) |
| `notion_embedding_model` | `nomic-embed-text-v2-moe` | Embedding model name |
| `notion_similarity_threshold` | `0.30` | Minimum cosine similarity for results |
| `notion_sync_interval` | `30` | Minutes between automatic syncs; `0` disables the scheduler |
| `notion_chunk_size` | `600` | Characters per chunk (default supplied by `NotionEmbeddingPipeline.__init__`) |
| `notion_chunk_overlap` | `100` | Overlap between chunks (default supplied by `NotionEmbeddingPipeline.__init__`) |

For setup instructions, see [Deployment.md Section 12](Deployment.md#12-notion-knowledge-base-rag).

---

## 6. Troubleshooting

### Search returns no results

1. **Check embeddings exist:** `SELECT COUNT(*) FROM notion_embeddings;`
2. **Check index type:** `SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'notion_embeddings';` -- should show HNSW, not IVFFlat.
3. **Check embedding dimensions:** `SELECT vector_dims(embedding) FROM notion_embeddings LIMIT 1;` -- should return 768.
4. **Test direct similarity:** `SELECT chunk_text, 1 - (embedding <=> (SELECT embedding FROM notion_embeddings LIMIT 1)) AS sim FROM notion_embeddings ORDER BY sim DESC LIMIT 5;`

### Wrong results ranked first

- **Typo sensitivity:** Embedding models treat "Mindest" (German: minimum) and "Mindset" (English: attitude) as completely different words. Check spelling.
- **Keyword boost not firing:** Verify `page_title` and `heading_context` are populated: `SELECT page_title, heading_context FROM notion_embeddings WHERE page_title != '' LIMIT 5;`
- **Threshold too high:** Lower `notion_similarity_threshold` (default: 0.30).

### Embeddings not updating after page changes

- Check `embedded_at < synced_at` for pending pages: `SELECT COUNT(*) FROM notion_pages WHERE content_text != '' AND (embedded_at IS NULL OR embedded_at < synced_at);`
- Force re-embed: Call `force_reembed()` from the Settings UI or API.

For more troubleshooting, see [Deployment.md -- Troubleshooting](Deployment.md#troubleshooting).
