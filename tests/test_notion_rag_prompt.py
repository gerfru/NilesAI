"""Tests for Notion RAG prompt and context builder behaviour."""

from unittest.mock import AsyncMock, MagicMock, patch


from niles.agent.prompts import build_notion_rag_prompt


# ---------- build_notion_rag_prompt ------------------------------------------


class TestBuildNotionRagPrompt:
    def test_prompt_is_short(self):
        prompt = build_notion_rag_prompt()
        # Must stay under 1200 chars (~300 tokens) to leave room for RAG context
        assert len(prompt) < 1200

    def test_no_tool_instructions(self):
        prompt = build_notion_rag_prompt()
        for keyword in [
            "WhatsApp",
            "find_contact",
            "find_event",
            "list_tasks",
            "Vikunja",
            "send_whatsapp",
            "mcp__",
            "Recherche",
            "Kalender",
        ]:
            assert keyword not in prompt, f"RAG prompt should not mention {keyword}"

    def test_contains_rag_rules(self):
        prompt = build_notion_rag_prompt()
        assert "[Notion-Kontext]" in prompt
        assert "Erfinde KEINE" in prompt
        assert "Markdown-Links" in prompt

    def test_contains_date(self):
        prompt = build_notion_rag_prompt(timezone="Europe/Vienna")
        # Should contain a date like "04.03.2026"
        assert "Heute ist" in prompt

    def test_includes_memories(self):
        memories = [
            {"key": "Lieblingsessen", "value": "Schnitzel"},
            {"key": "Name", "value": "Gerald"},
        ]
        prompt = build_notion_rag_prompt(memories=memories)
        assert "Schnitzel" in prompt
        assert "Gerald" in prompt
        assert "Gedaechtnis" in prompt

    def test_no_memories_when_empty(self):
        prompt = build_notion_rag_prompt(memories=[])
        assert "Gedaechtnis" not in prompt

    def test_no_memories_when_none(self):
        prompt = build_notion_rag_prompt(memories=None)
        assert "Gedaechtnis" not in prompt

    def test_invalid_timezone_fallback(self):
        # Should not raise, falls back to Europe/Vienna
        prompt = build_notion_rag_prompt(timezone="Invalid/Zone")
        assert "Heute ist" in prompt


# ---------- prepare_messages with notion_search=True -------------------------


def _make_ctx():
    """Create a minimal ContextBuilder-like mock for testing."""
    from niles.agent.context import ContextBuilder

    config = MagicMock()
    config.timezone = "Europe/Vienna"
    config.vikunja_api_url = None
    config.feature_notion = True

    ctx = ContextBuilder.__new__(ContextBuilder)
    ctx.config = config
    ctx.memory = AsyncMock()
    ctx.memory.list_all.return_value = [{"key": "test", "value": "val"}]
    ctx.history = AsyncMock()
    ctx.history.get_recent.return_value = [
        {"role": "user", "content": "Hallo"},
        {"role": "assistant", "content": "Hi!"},
    ]
    ctx.base_prompt = "Du bist Niles."
    ctx.mcp = None
    ctx.signal = None
    ctx.notion_retriever = None
    ctx._pending_phone_choices = {}
    ctx._pending_confirmations = {}
    return ctx


class TestPrepareMessagesNotionMode:
    async def test_uses_rag_prompt(self):
        ctx = _make_ctx()
        event = {
            "from": "test-chat",
            "content": "[Notion-Kontext]\nISO 9001...\n\n[Frage]\nWas ist ISO 9001?",
            "metadata": {"notion_search": True},
        }

        chat_id, messages, tools = await ctx.prepare_messages(
            event, [{"type": "function", "function": {"name": "find_contact"}}]
        )

        # Should return empty tools
        assert tools == []

        # System prompt should be the minimal RAG prompt, not soul.md
        system_msg = messages[0]
        assert system_msg["role"] == "system"
        assert "Notion-Kontext" in system_msg["content"]
        assert "WhatsApp" not in system_msg["content"]
        assert "find_contact" not in system_msg["content"]

    async def test_limits_history_to_4(self):
        ctx = _make_ctx()
        ctx.history.get_recent.return_value = [{"role": "user", "content": f"msg{i}"} for i in range(4)]
        event = {
            "from": "test-chat",
            "content": "test",
            "metadata": {"notion_search": True},
        }

        await ctx.prepare_messages(event, [])

        ctx.history.get_recent.assert_called_once_with("test-chat", limit=4)

    async def test_normal_mode_uses_full_prompt(self):
        ctx = _make_ctx()
        ctx.history.get_recent.return_value = []
        event = {
            "from": "test-chat",
            "content": "Hallo Niles",
            "metadata": {"notion_search": False},
        }

        with patch(
            "niles.agent.context.build_system_prompt",
            return_value="Du bist Niles. Full prompt.",
        ) as mock_build:
            with patch(
                "niles.agent.context.ContextBuilder.get_calendar_source_names",
                return_value=[],
            ):
                _, messages, _ = await ctx.prepare_messages(event, [])

        mock_build.assert_called_once()
        assert "Full prompt" in messages[0]["content"]

    async def test_normal_mode_uses_default_history_limit(self):
        ctx = _make_ctx()
        ctx.history.get_recent.return_value = []
        event = {
            "from": "test-chat",
            "content": "test",
            "metadata": {"notion_search": False},
        }

        with patch(
            "niles.agent.context.build_system_prompt",
            return_value="prompt",
        ):
            with patch(
                "niles.agent.context.ContextBuilder.get_calendar_source_names",
                return_value=[],
            ):
                await ctx.prepare_messages(event, [])

        # Default limit (no limit=4 kwarg)
        ctx.history.get_recent.assert_called_once_with("test-chat")
