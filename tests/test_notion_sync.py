"""Tests for Notion workspace sync (sync/notion.py)."""

import hashlib
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from niles.sync.notion import NotionSync, _TEXT_BLOCK_TYPES


# ---------- Helpers ----------------------------------------------------------


def _page(
    page_id="abc123",
    title="Test Page",
    object_type="page",
    last_edited="2026-01-15T10:00:00.000Z",
    url="https://notion.so/test",
    parent_type="workspace",
    parent_id=None,
):
    """Build a minimal Notion API page dict."""
    parent = {"type": parent_type}
    if parent_type == "page_id":
        parent["page_id"] = parent_id or "parent-id-1234"
    elif parent_type == "database_id":
        parent["database_id"] = parent_id or "db-id-5678"

    return {
        "id": page_id,
        "object": object_type,
        "url": url,
        "last_edited_time": last_edited,
        "parent": parent,
        "properties": {
            "title": {
                "type": "title",
                "title": [{"plain_text": title}],
            }
        },
    }


def _block(block_type, text, has_children=False, block_id="blk1"):
    """Build a minimal Notion API block dict."""
    return {
        "id": block_id,
        "type": block_type,
        "has_children": has_children,
        block_type: {"rich_text": [{"plain_text": text}]},
    }


def _sync(pool=None):
    """Create a NotionSync with mocked pool and client."""
    p = pool or AsyncMock()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "niles.sync.notion.AsyncClient",
            lambda auth: MagicMock(),
        )
        sync = NotionSync(p, "ntn_test_token")
    sync._client = AsyncMock()
    return sync, p


# ---------- _block_to_text ---------------------------------------------------


class TestBlockToText:
    def test_paragraph(self):
        block = _block("paragraph", "Hello world")
        assert NotionSync._block_to_text(block) == "Hello world"

    def test_heading_1(self):
        block = _block("heading_1", "Section Title")
        assert NotionSync._block_to_text(block) == "# Section Title"

    def test_heading_2(self):
        block = _block("heading_2", "Sub Title")
        assert NotionSync._block_to_text(block) == "## Sub Title"

    def test_heading_3(self):
        block = _block("heading_3", "Detail")
        assert NotionSync._block_to_text(block) == "### Detail"

    def test_bulleted_list(self):
        block = _block("bulleted_list_item", "Item one")
        assert NotionSync._block_to_text(block) == "- Item one"

    def test_numbered_list(self):
        block = _block("numbered_list_item", "Step one")
        assert NotionSync._block_to_text(block) == "1. Step one"

    def test_to_do_unchecked(self):
        block = _block("to_do", "Buy milk")
        block["to_do"]["checked"] = False
        assert NotionSync._block_to_text(block) == "- [ ] Buy milk"

    def test_to_do_checked(self):
        block = _block("to_do", "Done task")
        block["to_do"]["checked"] = True
        assert NotionSync._block_to_text(block) == "- [x] Done task"

    def test_quote(self):
        block = _block("quote", "Important note")
        assert NotionSync._block_to_text(block) == "> Important note"

    def test_callout(self):
        block = _block("callout", "Warning here")
        assert NotionSync._block_to_text(block) == "> Warning here"

    def test_code_block(self):
        block = _block("code", "print('hi')")
        assert NotionSync._block_to_text(block) == "```\nprint('hi')\n```"

    def test_code_block_with_language(self):
        block = _block("code", "print('hi')")
        block["code"]["language"] = "python"
        assert NotionSync._block_to_text(block) == "```python\nprint('hi')\n```"

    def test_unsupported_block_returns_empty(self):
        block = _block("image", "ignored")
        assert NotionSync._block_to_text(block) == ""

    def test_empty_rich_text(self):
        block = {"type": "paragraph", "paragraph": {"rich_text": []}}
        assert NotionSync._block_to_text(block) == ""

    def test_multiple_rich_text_segments(self):
        block = {
            "type": "paragraph",
            "paragraph": {
                "rich_text": [
                    {"plain_text": "Hello "},
                    {"plain_text": "world"},
                ]
            },
        }
        assert NotionSync._block_to_text(block) == "Hello world"

    def test_all_text_types_produce_output(self):
        for bt in _TEXT_BLOCK_TYPES:
            block = _block(bt, "test")
            result = NotionSync._block_to_text(block)
            assert "test" in result, f"{bt} should contain 'test' but got: {result}"


# ---------- _extract_title ---------------------------------------------------


class TestExtractTitle:
    def test_page_title(self):
        page = _page(title="My Page")
        assert NotionSync._extract_title(page) == "My Page"

    def test_database_title(self):
        page = {
            "object": "database",
            "title": [{"plain_text": "My DB"}],
            "properties": {},
        }
        assert NotionSync._extract_title(page) == "My DB"

    def test_missing_title_returns_empty(self):
        page = {"object": "page", "properties": {}}
        assert NotionSync._extract_title(page) == ""

    def test_multi_segment_title(self):
        page = {
            "object": "page",
            "properties": {
                "Name": {
                    "type": "title",
                    "title": [
                        {"plain_text": "Part "},
                        {"plain_text": "Two"},
                    ],
                }
            },
        }
        assert NotionSync._extract_title(page) == "Part Two"


# ---------- _extract_parent_id -----------------------------------------------


class TestExtractParentId:
    def test_page_parent(self):
        page = _page(parent_type="page_id", parent_id="aaaa-bbbb")
        assert NotionSync._extract_parent_id(page) == "aaaabbbb"

    def test_database_parent(self):
        page = _page(parent_type="database_id", parent_id="cccc-dddd")
        assert NotionSync._extract_parent_id(page) == "ccccdddd"

    def test_workspace_parent(self):
        page = _page(parent_type="workspace")
        assert NotionSync._extract_parent_id(page) is None


# ---------- _discover_pages --------------------------------------------------


class TestDiscoverPages:
    async def test_single_page(self):
        sync, _pool = _sync()
        sync._client.search = AsyncMock(return_value={"results": [_page()], "has_more": False})
        pages = await sync._discover_pages()
        assert len(pages) == 1

    async def test_pagination(self):
        sync, _pool = _sync()
        sync._client.search = AsyncMock(
            side_effect=[
                {
                    "results": [_page(page_id=f"p{i}") for i in range(100)],
                    "has_more": True,
                    "next_cursor": "cur1",
                },
                {
                    "results": [_page(page_id="p100")],
                    "has_more": False,
                },
            ]
        )
        pages = await sync._discover_pages()
        assert len(pages) == 101
        # Second call should have start_cursor
        call_kwargs = sync._client.search.call_args_list[1][1]
        assert call_kwargs["start_cursor"] == "cur1"


# ---------- _sync_page -------------------------------------------------------


class TestSyncPage:
    async def test_upsert_new_page(self):
        sync, pool = _sync()
        pool.fetchrow.return_value = None  # Not in DB yet
        sync._client.blocks.children.list = AsyncMock(
            return_value={
                "results": [_block("paragraph", "Hello")],
                "has_more": False,
            }
        )
        page = _page()
        await sync._sync_page(page)

        pool.execute.assert_called_once()
        sql = pool.execute.call_args[0][0]
        assert "INSERT INTO notion_pages" in sql
        assert sync._stats["pages_synced"] == 1

    async def test_skip_unchanged_last_edited(self):
        sync, pool = _sync()
        pool.fetchrow.return_value = {
            "last_edited": datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc),
            "content_md5": "abc",
        }
        page = _page(last_edited="2026-01-15T10:00:00.000Z")
        await sync._sync_page(page)

        pool.execute.assert_not_called()
        assert sync._stats["pages_unchanged"] == 1

    async def test_skip_unchanged_md5(self):
        sync, pool = _sync()
        content = "Hello"
        md5 = hashlib.md5(content.encode()).hexdigest()  # noqa: S324
        pool.fetchrow.return_value = {
            "last_edited": "2026-01-14T10:00:00.000Z",
            "content_md5": md5,
        }
        sync._client.blocks.children.list = AsyncMock(
            return_value={
                "results": [_block("paragraph", content)],
                "has_more": False,
            }
        )
        page = _page(last_edited="2026-01-15T10:00:00.000Z")
        await sync._sync_page(page)

        # Should only update last_edited, not synced_at (to avoid re-embedding)
        assert pool.execute.call_count == 1
        sql = pool.execute.call_args[0][0]
        assert "UPDATE notion_pages SET last_edited" in sql
        assert "synced_at" not in sql
        assert sync._stats["pages_unchanged"] == 1

    async def test_database_object_has_no_content_fetch(self):
        sync, pool = _sync()
        pool.fetchrow.return_value = None
        page = _page(object_type="database")
        page["object"] = "database"
        page["title"] = [{"plain_text": "My DB"}]
        await sync._sync_page(page)

        # blocks.children.list should NOT be called for databases
        sync._client.blocks.children.list.assert_not_called()


# ---------- _fetch_page_content ----------------------------------------------


class TestFetchPageContent:
    async def test_simple_content(self):
        sync, _pool = _sync()
        sync._client.blocks.children.list = AsyncMock(
            return_value={
                "results": [
                    _block("paragraph", "Line 1"),
                    _block("heading_1", "Title"),
                ],
                "has_more": False,
            }
        )
        result = await sync._fetch_page_content("page1")
        assert "Line 1" in result
        assert "# Title" in result

    async def test_recursive_children(self):
        sync, _pool = _sync()
        parent_block = _block("toggle", "Toggle", has_children=True, block_id="toggle1")
        child_block = _block("paragraph", "Nested text")

        sync._client.blocks.children.list = AsyncMock(
            side_effect=[
                {"results": [parent_block], "has_more": False},
                {"results": [child_block], "has_more": False},
            ]
        )
        result = await sync._fetch_page_content("page1")
        assert "Toggle" in result
        assert "Nested text" in result

    async def test_max_depth_stops_recursion(self):
        sync, _pool = _sync()
        result = await sync._fetch_page_content("page1", depth=6)
        assert result == ""
        sync._client.blocks.children.list.assert_not_called()


# ---------- test_connection ---------------------------------------------------


class TestTestConnection:
    async def test_success(self):
        sync, _pool = _sync()
        sync._client.search = AsyncMock(return_value={"results": [_page()]})
        ok, msg = await sync.test_connection()
        assert ok is True
        assert "1+" in msg

    async def test_failure(self):
        sync, _pool = _sync()
        sync._client.search = AsyncMock(side_effect=Exception("Invalid token"))
        ok, msg = await sync.test_connection()
        assert ok is False
        assert "fehlgeschlagen" in msg


# ---------- sync_all ----------------------------------------------------------


class TestSyncAll:
    async def test_counts_errors(self):
        sync, pool = _sync()
        sync._client.search = AsyncMock(return_value={"results": [_page()], "has_more": False})
        pool.fetchrow.side_effect = Exception("DB error")

        stats = await sync.sync_all()
        assert stats["errors"] == 1
        assert stats["pages_synced"] == 0
