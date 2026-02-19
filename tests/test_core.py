"""Tests for NilesAgent.process_event_stream (SSE streaming pipeline)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from niles.agent.core import MAX_TOOL_ROUNDS, NilesAgent
from niles.config import Settings


# --- Helpers ---


def _make_settings(**overrides):
    defaults = dict(
        _env_file=None,
        postgres_password="test",
        evolution_api_key="test",
        niles_api_key="test",
    )
    defaults.update(overrides)
    return Settings(**defaults)


def _make_delta(content=None, tool_calls=None, finish_reason=None):
    """Build a mock streaming chunk (ChatCompletionChunk)."""
    delta = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice])


def _make_tool_call_delta(index, tc_id=None, name=None, arguments=None):
    """Build a mock tool-call delta fragment."""
    func = None
    if name is not None or arguments is not None:
        func = SimpleNamespace(name=name, arguments=arguments)
    return SimpleNamespace(index=index, id=tc_id, function=func)


async def _aiter(items):
    """Turn a list into an async iterator (simulates streaming response)."""
    for item in items:
        yield item


def _make_agent(history=None, memory=None):
    """Build a NilesAgent with mocked dependencies."""
    config = _make_settings()
    contacts = AsyncMock()
    whatsapp = AsyncMock()
    mem = memory or AsyncMock()
    mem.list_all = AsyncMock(return_value={})
    hist = history or AsyncMock()
    hist.get_recent = AsyncMock(return_value=[])
    hist.add_message = AsyncMock()

    with patch("niles.agent.core.load_system_prompt", return_value="system prompt"):
        agent = NilesAgent(
            config=config,
            contacts=contacts,
            whatsapp=whatsapp,
            memory=mem,
            history=hist,
        )
    return agent


async def _collect(async_gen):
    """Collect all items from an async generator."""
    items = []
    async for item in async_gen:
        items.append(item)
    return items


# --- Tests ---


class TestProcessEventStream:
    """Unit tests for NilesAgent.process_event_stream."""

    async def test_simple_text_response(self):
        """Simple query with no tool calls yields chunks + done."""
        agent = _make_agent()

        chunks = [
            _make_delta(content="Hello "),
            _make_delta(content="world!"),
            _make_delta(finish_reason="stop"),
        ]
        agent.llm = AsyncMock()
        agent.llm.chat.completions.create = AsyncMock(return_value=_aiter(chunks))

        event = {"type": "web", "from": "test-chat", "content": "Hi"}
        events = await _collect(agent.process_event_stream(event))

        # Should yield two chunks + done
        assert events[0] == {"type": "chunk", "text": "Hello "}
        assert events[1] == {"type": "chunk", "text": "world!"}
        assert events[-1] == {"type": "done"}

    async def test_saves_messages_on_success(self):
        """Both user and assistant messages saved after successful response."""
        history = AsyncMock()
        history.get_recent = AsyncMock(return_value=[])
        history.add_message = AsyncMock()
        agent = _make_agent(history=history)

        chunks = [
            _make_delta(content="Response"),
            _make_delta(finish_reason="stop"),
        ]
        agent.llm = AsyncMock()
        agent.llm.chat.completions.create = AsyncMock(return_value=_aiter(chunks))

        event = {"type": "web", "from": "test-chat", "content": "Hello"}
        await _collect(agent.process_event_stream(event))

        # User and assistant messages saved together
        calls = history.add_message.call_args_list
        assert len(calls) == 2
        assert calls[0].args == ("test-chat", "user", "Hello")
        assert calls[1].args == ("test-chat", "assistant", "Response")

    async def test_empty_response_yields_fallback(self):
        """Fallback chunk yielded and no history saved when LLM returns empty."""
        history = AsyncMock()
        history.get_recent = AsyncMock(return_value=[])
        history.add_message = AsyncMock()
        agent = _make_agent(history=history)

        chunks = [
            _make_delta(finish_reason="stop"),
        ]
        agent.llm = AsyncMock()
        agent.llm.chat.completions.create = AsyncMock(return_value=_aiter(chunks))

        event = {"type": "web", "from": "test-chat", "content": "Hello"}
        events = await _collect(agent.process_event_stream(event))

        assert any("keine Antwort" in e.get("text", "") for e in events)
        assert events[-1] == {"type": "done"}
        history.add_message.assert_not_called()

    async def test_no_save_on_llm_error(self):
        """No orphaned messages when LLM call fails."""
        history = AsyncMock()
        history.get_recent = AsyncMock(return_value=[])
        history.add_message = AsyncMock()
        agent = _make_agent(history=history)

        agent.llm = AsyncMock()
        agent.llm.chat.completions.create = AsyncMock(
            side_effect=RuntimeError("LLM down"),
        )

        event = {"type": "web", "from": "test-chat", "content": "Hello"}
        events = await _collect(agent.process_event_stream(event))

        # Should yield error chunk + done
        assert any("Entschuldigung" in e.get("text", "") for e in events)
        assert events[-1] == {"type": "done"}
        history.add_message.assert_not_called()

    async def test_tool_call_reassembly(self):
        """Tool-call deltas are reassembled and executed correctly."""
        agent = _make_agent()

        # First LLM call: returns tool call in fragments
        tool_chunks = [
            _make_delta(
                tool_calls=[_make_tool_call_delta(0, tc_id="call_1", name="recall")],
            ),
            _make_delta(
                tool_calls=[_make_tool_call_delta(0, arguments='{"ke')],
            ),
            _make_delta(
                tool_calls=[_make_tool_call_delta(0, arguments='y": "foo"}')],
            ),
            _make_delta(finish_reason="tool_calls"),
        ]

        # Second LLM call: returns text response
        text_chunks = [
            _make_delta(content="The value is bar"),
            _make_delta(finish_reason="stop"),
        ]

        create_mock = AsyncMock(side_effect=[_aiter(tool_chunks), _aiter(text_chunks)])
        agent.llm = AsyncMock()
        agent.llm.chat.completions.create = create_mock

        # Mock the tool execution
        agent.memory.get = AsyncMock(return_value="bar")

        event = {"type": "web", "from": "test-chat", "content": "What is foo?"}
        events = await _collect(agent.process_event_stream(event))

        # Should have status event for recall, then text chunks, then done
        assert any(e.get("type") == "status" and "recall" in e.get("text", "") for e in events)
        assert any(e.get("type") == "chunk" and "bar" in e.get("text", "") for e in events)
        assert events[-1] == {"type": "done"}

        # LLM called twice (tool round + final response)
        assert create_mock.call_count == 2

        # Both user and assistant messages saved after tool resolution
        calls = agent.history.add_message.call_args_list
        assert len(calls) == 2
        assert calls[0].args == ("test-chat", "user", "What is foo?")
        assert calls[1].args == ("test-chat", "assistant", "The value is bar")

    async def test_max_tool_rounds_reached(self):
        """Yields error when MAX_TOOL_ROUNDS is exhausted."""
        agent = _make_agent()

        # Every LLM call returns a tool call (infinite loop scenario)
        def make_tool_stream():
            return _aiter([
                _make_delta(
                    tool_calls=[_make_tool_call_delta(0, tc_id="call_x", name="recall")],
                ),
                _make_delta(
                    tool_calls=[_make_tool_call_delta(0, arguments='{"key": "x"}')],
                ),
                _make_delta(finish_reason="tool_calls"),
            ])

        agent.llm = AsyncMock()
        agent.llm.chat.completions.create = AsyncMock(side_effect=[
            make_tool_stream() for _ in range(MAX_TOOL_ROUNDS)
        ])
        agent.memory.get = AsyncMock(return_value="val")

        event = {"type": "web", "from": "test-chat", "content": "loop"}
        events = await _collect(agent.process_event_stream(event))

        # Should end with error message + done
        assert any("nicht abschliessen" in e.get("text", "") for e in events)
        assert events[-1] == {"type": "done"}
