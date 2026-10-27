"""Langfuse SDK compatibility tests with synthetic LLM responses."""

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from openai import AsyncOpenAI

from niles.agent.core import NilesAgent
from tests.helpers import make_test_settings


def _make_agent(**overrides):
    settings = make_test_settings(
        llm_base_url="http://llm.test/v1",
        llm_model="test-model",
        langfuse_host=overrides.get("langfuse_host", ""),
        langfuse_public_key=overrides.get("langfuse_public_key", ""),
        langfuse_secret_key=overrides.get("langfuse_secret_key", ""),
    )
    history = AsyncMock()
    history.get_recent.return_value = []
    memory = AsyncMock()
    memory.list_all.return_value = []
    with patch("niles.agent.core.load_system_prompt", return_value="Synthetic test assistant."):
        return NilesAgent(
            config=settings,
            contacts=AsyncMock(),
            whatsapp=AsyncMock(),
            memory=memory,
            history=history,
        )


@pytest.mark.parametrize(
    "config",
    [
        {},
        {"langfuse_host": "http://langfuse.test"},
        {"langfuse_host": "http://langfuse.test", "langfuse_public_key": "pk-lf-test"},
    ],
)
async def test_tracing_requires_complete_configuration(config):
    with patch("builtins.__import__", wraps=__import__) as imports:
        agent = _make_agent(**config)
    try:
        assert agent._OpenAI is AsyncOpenAI
        assert not any(call.args[0].startswith("langfuse") for call in imports.call_args_list)
    finally:
        await agent.llm.close()


async def test_missing_tracing_package_warns_and_keeps_local_client(caplog, monkeypatch):
    original_import = __import__
    monkeypatch.setenv("LANGFUSE_HOST", "http://langfuse.test")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")

    def without_langfuse(name, *args, **kwargs):
        if name.startswith("langfuse"):
            raise ModuleNotFoundError("Synthetic missing optional package")
        return original_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=without_langfuse):
        agent = _make_agent(
            langfuse_host="http://langfuse.test",
            langfuse_public_key="pk-lf-test",
            langfuse_secret_key="sk-lf-test",  # pragma: allowlist secret
        )
    try:
        assert agent._OpenAI is AsyncOpenAI
        assert "LLM tracing disabled" in caplog.text
        assert "uv sync --extra tracing" in caplog.text
    finally:
        await agent.llm.close()


@pytest.fixture(scope="module")
def tracing_client():
    langfuse = pytest.importorskip("langfuse")
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    client = langfuse.Langfuse(
        public_key="pk-lf-test",
        secret_key="sk-lf-test",  # pragma: allowlist secret
        base_url="http://langfuse.test",
        tracer_provider=TracerProvider(),
        span_exporter=exporter,
    )
    yield client, exporter
    client.shutdown()


@pytest.mark.parametrize("streaming", [False, True])
async def test_real_sdk_records_agent_generation(tracing_client, monkeypatch, streaming):
    client, exporter = tracing_client
    client.flush()
    exporter.clear()
    requests = []

    async def handle_request(transport, request):
        assert request.url == "http://llm.test/v1/chat/completions"
        body = json.loads(request.content)
        requests.append(body)
        completion = {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 1,
            "model": "test-model",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "Hello."}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15},
        }
        if not body.get("stream", False):
            return httpx.Response(200, json=completion)
        chunks = [
            {
                **{key: completion[key] for key in ("id", "created", "model")},
                "object": "chat.completion.chunk",
                "choices": [{"index": 0, "delta": {"role": "assistant", "content": "Hello."}, "finish_reason": None}],
            },
            {
                **{key: completion[key] for key in ("id", "created", "model")},
                "object": "chat.completion.chunk",
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            },
            {
                **{key: completion[key] for key in ("id", "created", "model")},
                "object": "chat.completion.chunk",
                "choices": [],
                "usage": completion["usage"],
            },
        ]
        data = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=data)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", handle_request)
    monkeypatch.setenv("LANGFUSE_HOST", "http://langfuse.test")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    agent = _make_agent(
        langfuse_host="http://langfuse.test",
        langfuse_public_key="pk-lf-test",
        langfuse_secret_key="sk-lf-test",  # pragma: allowlist secret
    )
    event = {"type": "web", "from": "web-user-1", "content": "Say hello."}
    try:
        if streaming:
            events = [item async for item in agent.process_event_stream(event)]
            assert events[-1] == {"type": "done"}
            assert "".join(item["text"] for item in events if item["type"] == "chunk") == "Hello."
        else:
            assert await agent.process_event(event) == "Hello."
        agent.history.add_message.assert_any_await("web-user-1", "assistant", "Hello.")
        assert len(requests) == 1
        assert requests[0].get("stream", False) is streaming
        client.flush()
        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        attributes = spans[0].attributes
        assert attributes["langfuse.observation.type"] == "generation"
        assert attributes["langfuse.observation.model.name"] == "test-model"
        assert "Say hello." in attributes["langfuse.observation.input"]
        assert "Hello." in attributes["langfuse.observation.output"]
        usage = json.loads(attributes["langfuse.observation.usage_details"])
        assert usage["prompt_tokens"] == 12
        assert usage["completion_tokens"] == 3
    finally:
        await agent.llm.close()
