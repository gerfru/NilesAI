"""Tests for the context-window budget (W9): history trim, num_ctx, MCP cap."""

from unittest.mock import AsyncMock, Mock, patch

from niles.agent.context import ContextBuilder
from niles.agent.core import NilesAgent
from niles.config import Settings
from niles.tokens import count_tokens


def _settings(**overrides):
    defaults = dict(
        _env_file=None,
        postgres_password="test",  # pragma: allowlist secret
        evolution_api_key="test",  # pragma: allowlist secret
        niles_api_key="test",  # pragma: allowlist secret
    )
    defaults.update(overrides)
    return Settings(**defaults)


def _ctx(config):
    return ContextBuilder(
        config=config,
        contacts=AsyncMock(),
        whatsapp=AsyncMock(),
        memory=AsyncMock(),
        history=AsyncMock(),
        base_prompt="Du bist Niles.",
    )


class TestHistoryBudget:
    async def test_trims_history_to_token_budget(self):
        ctx = _ctx(_settings(llm_num_ctx=1500, llm_max_tokens=1000))
        ctx.memory.list_all = AsyncMock(return_value=[])
        ctx.get_calendar_source_names = AsyncMock(return_value=[])
        history = [{"role": "user", "content": "lange nachricht " * 30} for _ in range(40)]
        ctx.history.get_recent = AsyncMock(return_value=history)

        _, messages, _ = await ctx.prepare_messages({"from": "web-user-1", "content": "hi"}, [])

        non_system = [m for m in messages if m["role"] != "system"]
        # final current message + a heavily trimmed history (far below 40)
        assert messages[0]["role"] == "system"
        assert non_system[-1] == {"role": "user", "content": "hi"}
        assert len(non_system) - 1 < 40

    async def test_keeps_history_when_budget_large(self):
        ctx = _ctx(_settings(llm_num_ctx=32000, llm_max_tokens=1000))
        ctx.memory.list_all = AsyncMock(return_value=[])
        ctx.get_calendar_source_names = AsyncMock(return_value=[])
        history = [{"role": "user", "content": "kurz"} for _ in range(5)]
        ctx.history.get_recent = AsyncMock(return_value=history)

        _, messages, _ = await ctx.prepare_messages({"from": "web-user-1", "content": "hi"}, [])

        non_system = [m for m in messages if m["role"] != "system"]
        assert len(non_system) - 1 == 5


class TestNumCtx:
    async def test_num_ctx_passed_via_extra_body(self):
        with (
            patch("niles.agent.core.AsyncOpenAI"),
            patch("niles.agent.core.load_system_prompt", return_value="sp"),
        ):
            agent = NilesAgent(
                config=_settings(llm_num_ctx=4242),
                contacts=AsyncMock(),
                whatsapp=AsyncMock(),
                memory=AsyncMock(),
                history=AsyncMock(),
            )
        agent.llm = Mock()
        agent.llm.chat.completions.create = AsyncMock(return_value="ok")
        await agent._llm_create(model="m", messages=[])
        kwargs = agent.llm.chat.completions.create.call_args.kwargs
        assert kwargs["extra_body"]["options"]["num_ctx"] == 4242


class TestMcpTokenCap:
    async def test_large_result_truncated_to_token_cap(self):
        from niles.agent.tools.mcp import handle_mcp_tool

        ctx = Mock()
        ctx.config.mcp_max_result_tokens = 5
        ctx.mcp.is_mcp_tool.return_value = True
        ctx.mcp.call_tool = AsyncMock(return_value="wort " * 200)
        out = await handle_mcp_tool("mcp__weather__forecast", {}, ctx)
        assert "[truncated]" in out["result"]
        body = out["result"].split("\n...[truncated]")[0]
        assert count_tokens(body) <= 5
