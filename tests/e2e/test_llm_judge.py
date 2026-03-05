"""Claude-as-Judge tests — real Ollama LLM evaluated by Claude.

These tests run the agent with the real Ollama LLM (no FakeLLM) and use
the Claude API to evaluate whether the agent selected the right tools,
passed correct arguments, and generated a helpful German-language response.

Requirements:
- Ollama running with the configured model
- PostgreSQL with test data
- ANTHROPIC_API_KEY environment variable set
"""

from __future__ import annotations

import os
from unittest.mock import patch

import httpx
import pytest
import pytest_asyncio

from niles.actions.calendar import CalendarAction
from niles.actions.contacts import ContactsAction
from niles.agent.core import NilesAgent
from niles.config import Settings
from niles.memory.history import ConversationHistory
from niles.memory.store import MemoryStore

from .judge import run_and_judge

pytestmark = [
    pytest.mark.llm_judge,
    pytest.mark.asyncio(loop_scope="session"),
]

SCORE_THRESHOLD = 7


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def ollama_available():
    """Skip if Ollama is not reachable."""
    llm_url = os.environ.get("LLM_BASE_URL", "http://127.0.0.1:11434/v1")
    ollama_url = llm_url.removesuffix("/v1")
    async with httpx.AsyncClient(timeout=5) as client:
        try:
            resp = await client.get(f"{ollama_url}/api/tags")
            resp.raise_for_status()
        except (httpx.ConnectError, httpx.HTTPError):
            pytest.skip(f"Ollama not reachable at {ollama_url}")


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def anthropic_available():
    """Skip if ANTHROPIC_API_KEY is not set."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set")


@pytest_asyncio.fixture(loop_scope="session")
async def real_agent(pool_in_tx, ollama_available, anthropic_available):
    """NilesAgent with real Ollama LLM + real DB."""
    settings = Settings(
        _env_file=None,
        postgres_password="test",
        evolution_api_key="test",
        niles_api_key="test",
    )

    from unittest.mock import AsyncMock

    contacts = ContactsAction(pool_in_tx)
    memory = MemoryStore(pool_in_tx)
    history = ConversationHistory(pool_in_tx)
    calendar = CalendarAction(pool_in_tx, timezone="Europe/Vienna")

    with patch("niles.agent.core.load_system_prompt", return_value="Du bist Niles."):
        agent = NilesAgent(
            config=settings,
            contacts=contacts,
            whatsapp=AsyncMock(),
            memory=memory,
            history=history,
            calendar=calendar,
        )
    return agent


# ---------------------------------------------------------------------------
# Contact tests
# ---------------------------------------------------------------------------


class TestContactsJudge:
    async def test_find_contact(self, real_agent, seed_contact):
        """Ollama should use find_contact to look up a phone number."""
        result = await run_and_judge(
            agent=real_agent,
            message="Wie ist die Telefonnummer von Max Mustermann?",
        )
        assert result["scores"]["tool_selection"] >= SCORE_THRESHOLD, (
            f"tool_selection={result['scores']['tool_selection']}: "
            f"{result['reasoning']}"
        )
        assert result["scores"]["response_quality"] >= SCORE_THRESHOLD


# ---------------------------------------------------------------------------
# Memory tests
# ---------------------------------------------------------------------------


class TestMemoryJudge:
    async def test_remember(self, real_agent):
        """Ollama should use remember to store a fact."""
        result = await run_and_judge(
            agent=real_agent,
            message="Merk dir bitte: Mein Lieblingsgericht ist Wiener Schnitzel",
        )
        assert result["scores"]["tool_selection"] >= SCORE_THRESHOLD, (
            f"tool_selection={result['scores']['tool_selection']}: "
            f"{result['reasoning']}"
        )


# ---------------------------------------------------------------------------
# Calendar tests
# ---------------------------------------------------------------------------


class TestCalendarJudge:
    async def test_find_event(self, real_agent, seed_events):
        """Ollama should use find_event to check the calendar."""
        result = await run_and_judge(
            agent=real_agent,
            message="Was steht morgen im Kalender?",
        )
        assert result["scores"]["tool_selection"] >= SCORE_THRESHOLD, (
            f"tool_selection={result['scores']['tool_selection']}: "
            f"{result['reasoning']}"
        )


# ---------------------------------------------------------------------------
# No tool needed
# ---------------------------------------------------------------------------


class TestNoToolJudge:
    async def test_greeting(self, real_agent):
        """Greetings need no tool — agent should reply directly."""
        result = await run_and_judge(
            agent=real_agent,
            message="Guten Morgen, Niles!",
        )
        assert result["scores"]["personality"] >= SCORE_THRESHOLD, (
            f"personality={result['scores']['personality']}: {result['reasoning']}"
        )
        assert result["scores"]["language"] >= SCORE_THRESHOLD


# ---------------------------------------------------------------------------
# Task tests
# ---------------------------------------------------------------------------


class TestTasksJudge:
    async def test_create_task(self, real_agent):
        """Ollama should use create_task."""
        result = await run_and_judge(
            agent=real_agent,
            message="Erstelle eine Aufgabe: Einkaufen gehen",
        )
        assert result["scores"]["tool_selection"] >= SCORE_THRESHOLD, (
            f"tool_selection={result['scores']['tool_selection']}: "
            f"{result['reasoning']}"
        )
