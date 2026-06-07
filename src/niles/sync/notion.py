"""Notion workspace sync — fetches pages and converts to plaintext."""

import hashlib
import logging
from datetime import datetime

import asyncpg
from notion_client import AsyncClient

logger = logging.getLogger(__name__)

# Block types that contain readable text
_TEXT_BLOCK_TYPES = {
    "paragraph",
    "heading_1",
    "heading_2",
    "heading_3",
    "bulleted_list_item",
    "numbered_list_item",
    "to_do",
    "toggle",
    "callout",
    "quote",
    "code",
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
        results: list[dict] = []
        cursor = None
        while len(results) < _MAX_PAGES:
            kwargs: dict = {"page_size": 100}
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
        last_edited_str = page.get("last_edited_time")
        last_edited = datetime.fromisoformat(last_edited_str) if last_edited_str else None

        # Quick check: skip if last_edited hasn't changed
        existing = await self._pool.fetchrow(
            "SELECT last_edited, content_md5 FROM notion_pages WHERE id = $1",
            page_id,
        )
        if existing and existing["last_edited"] and last_edited:
            if existing["last_edited"] == last_edited:
                self._stats["pages_unchanged"] += 1
                return

        # Fetch block content (pages only, not databases)
        content = ""
        if object_type == "page":
            content = await self._fetch_page_content(page["id"])

        content_md5 = hashlib.md5(content.encode()).hexdigest()  # noqa: S324  # nosemgrep: insecure-hash-algorithm-md5

        # Skip if content hasn't actually changed
        if existing and existing["content_md5"] == content_md5:
            self._stats["pages_unchanged"] += 1
            # Update last_edited but keep synced_at unchanged so
            # embedded_at < synced_at doesn't re-trigger embedding
            await self._pool.execute(
                "UPDATE notion_pages SET last_edited = $2 WHERE id = $1",
                page_id,
                last_edited,
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
            page_id,
            title,
            self._extract_parent_id(page),
            object_type,
            content,
            content_md5,
            url,
            last_edited,
        )
        self._stats["pages_synced"] += 1

    async def _fetch_page_content(self, page_id: str, depth: int = 0) -> str:
        """Recursively fetch all text blocks of a page."""
        if depth > _MAX_DEPTH:
            return ""

        blocks: list[dict] = []
        cursor = None
        while True:
            kwargs: dict = {"block_id": page_id, "page_size": 100}
            if cursor:
                kwargs["start_cursor"] = cursor
            response = await self._client.blocks.children.list(**kwargs)
            blocks.extend(response.get("results", []))
            if not response.get("has_more"):
                break
            cursor = response.get("next_cursor")

        lines: list[str] = []
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
        """Extract markdown-formatted text from a single Notion block."""
        block_type = block.get("type", "")
        if block_type not in _TEXT_BLOCK_TYPES:
            return ""
        data = block.get(block_type, {})
        rich_text = data.get("rich_text", [])
        text = "".join(rt.get("plain_text", "") for rt in rich_text)
        if not text:
            return ""
        if block_type == "heading_1":
            return f"# {text}"
        if block_type == "heading_2":
            return f"## {text}"
        if block_type == "heading_3":
            return f"### {text}"
        if block_type == "bulleted_list_item":
            return f"- {text}"
        if block_type == "numbered_list_item":
            return f"1. {text}"
        if block_type == "to_do":
            checked = data.get("checked", False)
            return f"- [{'x' if checked else ' '}] {text}"
        if block_type == "quote" or block_type == "callout":
            return f"> {text}"
        if block_type == "code":
            lang = data.get("language", "")
            return f"```{lang}\n{text}\n```"
        return text

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
            return True, f"Verbunden. {count}+ Seiten zugaenglich."
        except Exception as exc:
            return False, f"Verbindung fehlgeschlagen: {exc}"
