"""Deterministic LLM replacement for E2E pipeline tests.

FakeLLM simulates an OpenAI-compatible streaming API.  It takes a list of
scripted responses and replays them in order, one per
``llm.chat.completions.create()`` call.

Each response is either:
- ``{"content": "text"}``       → text-only reply (finish_reason="stop")
- ``{"tool_calls": [{"name": "find_contact", "arguments": {"name": "Max"}}]}``
    → tool call round (finish_reason="tool_calls")
"""

from __future__ import annotations

import json
from types import SimpleNamespace


class FakeLLM:
    """Scripted LLM that yields deterministic streaming chunks.

    Usage::

        fake = FakeLLM([
            {"tool_calls": [{"name": "recall", "arguments": {"key": "x"}}]},
            {"content": "The value is 42."},
        ])
        agent.llm = fake
    """

    def __init__(self, responses: list[dict]):
        self._responses = list(responses)
        self._call_index = 0
        # Mirror OpenAI client attribute path: llm.chat.completions.create
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create),
        )
        # Recorded calls for test assertions
        self.calls: list[dict] = []

    async def _create(self, *, model, messages, **kwargs):
        """Return the next scripted response as an async chunk generator."""
        self.calls.append(
            {
                "model": model,
                "messages": messages,
                "tools": kwargs.get("tools"),
            }
        )
        if self._call_index >= len(self._responses):
            raise RuntimeError(
                f"FakeLLM exhausted: {len(self._responses)} responses scripted, "
                f"but call #{self._call_index + 1} was made"
            )
        response = self._responses[self._call_index]
        self._call_index += 1

        if "tool_calls" in response:
            return _stream_tool_calls(response["tool_calls"])
        return _stream_text(response.get("content", ""))


# ---------------------------------------------------------------------------
# Streaming helpers — yield SimpleNamespace chunks matching OpenAI format
# ---------------------------------------------------------------------------


def _make_chunk(
    content=None,
    tool_calls=None,
    finish_reason=None,
):
    """Build a single streaming chunk (mimics ChatCompletionChunk)."""
    delta = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice])


def _make_tool_call_delta(index, tc_id, name, arguments):
    """Build a tool-call delta fragment."""
    func = SimpleNamespace(name=name, arguments=arguments)
    return SimpleNamespace(index=index, id=tc_id, function=func)


async def _stream_text(content: str):
    """Yield text content as streaming chunks, then finish_reason='stop'."""
    if content:
        yield _make_chunk(content=content)
    yield _make_chunk(finish_reason="stop")


async def _stream_tool_calls(tool_calls: list[dict]):
    """Yield tool calls as streaming chunks, then finish_reason='tool_calls'.

    Each tool call dict has: ``{"name": str, "arguments": dict}``
    """
    for idx, tc in enumerate(tool_calls):
        tc_id = f"fake_call_{idx}"
        args_json = (
            json.dumps(tc["arguments"], ensure_ascii=False) if isinstance(tc["arguments"], dict) else tc["arguments"]
        )
        yield _make_chunk(
            tool_calls=[_make_tool_call_delta(idx, tc_id, tc["name"], args_json)],
        )
    yield _make_chunk(finish_reason="tool_calls")
