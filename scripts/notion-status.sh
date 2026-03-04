#!/usr/bin/env bash
# Quick status check for Notion RAG pipeline
set -euo pipefail

DB_CONTAINER="niles_evolution_postgres"
DB_USER="evolution"
DB_NAME="evolution_db"

psql_cmd() {
  docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -c "$1" 2>&1
}

echo "=== Notion RAG Status ==="
echo ""

echo "-- Pages --"
psql_cmd "
SELECT
  COUNT(*)                                          AS total_pages,
  COUNT(*) FILTER (WHERE embedded_at IS NOT NULL)   AS embedded,
  COUNT(*) FILTER (WHERE content_text != ''
                   AND embedded_at IS NULL)          AS pending,
  COUNT(*) FILTER (WHERE content_text = '')          AS empty
FROM notion_pages;
"

echo "-- Embeddings --"
psql_cmd "
SELECT
  COUNT(*)              AS total_chunks,
  COUNT(DISTINCT page_id) AS pages_with_chunks
FROM notion_embeddings;
"

echo "-- Last Sync --"
psql_cmd "
SELECT
  MAX(synced_at)   AS last_sync,
  MAX(embedded_at) AS last_embed
FROM notion_pages;
"

echo "-- Sample Search (top 3 largest pages) --"
psql_cmd "
SELECT p.title, COUNT(e.id) AS chunks
FROM notion_pages p
JOIN notion_embeddings e ON e.page_id = p.id
GROUP BY p.title
ORDER BY chunks DESC
LIMIT 3;
"
