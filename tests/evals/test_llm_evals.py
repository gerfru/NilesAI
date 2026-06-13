# SPDX-License-Identifier: AGPL-3.0-only
"""LLM behavioral eval suite against a live Ollama instance.

Run with:   pytest -m llm_eval --tb=short
Skip in CI: pytest -m "not llm_eval"

Tests verify that the LLM selects the correct tool (or no tool) for a set of
representative queries.  Tool execution is mocked so no real services are
needed — only the LLM itself must be reachable.
"""

import json
import os
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from niles.agent.core import NilesAgent
from niles.config import Settings

GOLDEN_DATASET = json.loads((Path(__file__).parent / "golden_dataset.json").read_text())

_OLLAMA_URL = os.environ.get("LLM_BASE_URL", "http://localhost:11434/v1")


def _ollama_reachable() -> bool:
    try:
        httpx.get(f"{_OLLAMA_URL}/models", timeout=3)
        return True
    except Exception:
        return False


OLLAMA_AVAILABLE = _ollama_reachable()


def _make_eval_agent() -> NilesAgent:
    """NilesAgent connected to real Ollama; no real DB or service connections."""
    settings = Settings(
        _env_file=None,
        postgres_password="eval",  # pragma: allowlist secret
        evolution_api_key="eval",  # pragma: allowlist secret
        niles_api_key="eval",  # pragma: allowlist secret
        credential_encryption_optional=True,
        llm_base_url=_OLLAMA_URL,
        vikunja_api_url="http://vikunja:3456/api/v1",
    )
    contacts = AsyncMock()
    whatsapp = AsyncMock()
    memory = AsyncMock()
    memory.list_all = AsyncMock(return_value=[])
    history = AsyncMock()
    history.get_recent = AsyncMock(return_value=[])
    history.add_message = AsyncMock()

    agent = NilesAgent(
        config=settings,
        contacts=contacts,
        whatsapp=whatsapp,
        memory=memory,
        history=history,
    )
    return agent


async def _run_case(agent: NilesAgent, query: str) -> tuple[str, list[str]]:
    """Run one eval query; return (response, list_of_called_tool_names)."""
    called_tools: list[str] = []

    original_execute = agent._execute_tool_call

    async def _capturing_execute(tool_call, chat_id: str = "") -> dict:
        called_tools.append(tool_call.function.name)
        return {"result": "eval mock — ignoriere dieses Ergebnis und antworte dem Benutzer."}

    agent._execute_tool_call = _capturing_execute  # type: ignore[method-assign]
    try:
        response = await agent.process_event({"from": "web-user-1", "content": query, "metadata": {}})
    finally:
        agent._execute_tool_call = original_execute  # type: ignore[method-assign]

    return response or "", called_tools


@pytest.mark.llm_eval
@pytest.mark.skipif(not OLLAMA_AVAILABLE, reason=f"Ollama not reachable at {_OLLAMA_URL}")
@pytest.mark.asyncio
class TestGoldenDataset:
    """Run every case in golden_dataset.json and assert behavioral expectations."""

    async def _assert_case(self, agent: NilesAgent, case: dict) -> None:
        response, called = await _run_case(agent, case["input"])

        expected_tool = case.get("expect_tool_called")
        expect_no_tool = case.get("expect_no_tool", False)

        if expect_no_tool:
            allowed = set(case.get("allow_tools", []))
            unexpected = [t for t in called if t not in allowed]
            assert unexpected == [], (
                f"[{case['id']}] Expected NO tool call, got: {called}\nQuery: {case['input']!r}\nResponse: {response!r}"
            )
        elif expected_tool:
            assert expected_tool in called, (
                f"[{case['id']}] Expected tool {expected_tool!r} to be called, got: {called}\n"
                f"Query: {case['input']!r}\nResponse: {response!r}"
            )

    @pytest.fixture(autouse=True)
    def agent(self):
        self._agent = _make_eval_agent()

    async def test_whatsapp_send_contact(self):
        await self._assert_case(self._agent, next(c for c in GOLDEN_DATASET if c["id"] == "whatsapp-send-contact"))

    async def test_calendar_query_tomorrow(self):
        await self._assert_case(self._agent, next(c for c in GOLDEN_DATASET if c["id"] == "calendar-query-tomorrow"))

    async def test_contact_lookup_number(self):
        await self._assert_case(self._agent, next(c for c in GOLDEN_DATASET if c["id"] == "contact-lookup-number"))

    async def test_task_list_open(self):
        await self._assert_case(self._agent, next(c for c in GOLDEN_DATASET if c["id"] == "task-list-open"))

    async def test_create_task_simple(self):
        await self._assert_case(self._agent, next(c for c in GOLDEN_DATASET if c["id"] == "create-task-simple"))

    async def test_complete_task(self):
        await self._assert_case(self._agent, next(c for c in GOLDEN_DATASET if c["id"] == "complete-task"))

    async def test_memory_store(self):
        await self._assert_case(self._agent, next(c for c in GOLDEN_DATASET if c["id"] == "memory-store"))

    async def test_memory_recall(self):
        await self._assert_case(self._agent, next(c for c in GOLDEN_DATASET if c["id"] == "memory-recall"))

    async def test_create_calendar_event(self):
        await self._assert_case(self._agent, next(c for c in GOLDEN_DATASET if c["id"] == "create-calendar-event"))

    async def test_whatsapp_read_messages(self):
        await self._assert_case(self._agent, next(c for c in GOLDEN_DATASET if c["id"] == "whatsapp-read-messages"))

    async def test_calendar_next_week(self):
        await self._assert_case(self._agent, next(c for c in GOLDEN_DATASET if c["id"] == "calendar-next-week"))

    async def test_whatsapp_to_explicit_number(self):
        await self._assert_case(
            self._agent, next(c for c in GOLDEN_DATASET if c["id"] == "whatsapp-to-explicit-number")
        )

    async def test_create_task_with_project(self):
        await self._assert_case(self._agent, next(c for c in GOLDEN_DATASET if c["id"] == "create-task-with-project"))

    async def test_calendar_specific_date(self):
        await self._assert_case(self._agent, next(c for c in GOLDEN_DATASET if c["id"] == "calendar-specific-date"))

    async def test_memory_store_key_value(self):
        await self._assert_case(self._agent, next(c for c in GOLDEN_DATASET if c["id"] == "memory-store-key-value"))

    async def test_chat_greeting_no_tool(self):
        await self._assert_case(self._agent, next(c for c in GOLDEN_DATASET if c["id"] == "chat-greeting"))

    async def test_chat_factual_question_no_tool(self):
        await self._assert_case(self._agent, next(c for c in GOLDEN_DATASET if c["id"] == "chat-factual-question"))

    async def test_chat_explanation_no_tool(self):
        await self._assert_case(self._agent, next(c for c in GOLDEN_DATASET if c["id"] == "chat-explanation"))

    async def test_chat_thanks_no_tool(self):
        await self._assert_case(self._agent, next(c for c in GOLDEN_DATASET if c["id"] == "chat-thanks"))

    async def test_chat_math_no_tool(self):
        await self._assert_case(self._agent, next(c for c in GOLDEN_DATASET if c["id"] == "chat-math"))
