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

import httpx
import pytest
import pytest_asyncio

from .conftest import make_real_agent, record_score
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
    return make_real_agent(pool_in_tx)


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


# ===========================================================================
# Extended judge tests — new scenarios for LLM benchmark
# ===========================================================================


# ---------------------------------------------------------------------------
# Search & fetch tools (MCP-dependent)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("FEATURE_SEARCH", "").lower() != "true",
    reason="FEATURE_SEARCH not enabled",
)
class TestSearchToolJudge:
    async def test_web_search(self, real_agent):
        """Agent should use mcp__searxng__search for web research."""
        result = await run_and_judge(
            agent=real_agent,
            message="Recherchiere aktuelle Nachrichten zu KI",
        )
        record_score("web_search", result["scores"])
        assert result["scores"]["tool_selection"] >= SCORE_THRESHOLD, (
            f"tool_selection={result['scores']['tool_selection']}: "
            f"{result['reasoning']}"
        )

    async def test_fetch_url(self, real_agent):
        """Agent should use mcp__fetch__fetch_url to read a URL."""
        result = await run_and_judge(
            agent=real_agent,
            message="Lies diese Seite: https://example.com",
        )
        record_score("fetch_url", result["scores"])
        assert result["scores"]["tool_selection"] >= SCORE_THRESHOLD, (
            f"tool_selection={result['scores']['tool_selection']}: "
            f"{result['reasoning']}"
        )


# ---------------------------------------------------------------------------
# Notion RAG (feature-gated)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("FEATURE_NOTION", "").lower() != "true",
    reason="FEATURE_NOTION not enabled",
)
class TestNotionToolJudge:
    async def test_notion_search(self, real_agent):
        """Agent should use search_notion for knowledge base queries."""
        result = await run_and_judge(
            agent=real_agent,
            message="Suche in meinen Notion-Notizen nach Projektplan",
        )
        record_score("notion_search", result["scores"])
        assert result["scores"]["tool_selection"] >= SCORE_THRESHOLD, (
            f"tool_selection={result['scores']['tool_selection']}: "
            f"{result['reasoning']}"
        )


# ---------------------------------------------------------------------------
# Weather tools (MCP-dependent)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("MCP_TOOLS_AVAILABLE", "").lower() != "true",
    reason="MCP tools not available",
)
class TestWeatherToolJudge:
    async def test_weather_forecast(self, real_agent):
        """Agent should use weather tool for forecast questions."""
        result = await run_and_judge(
            agent=real_agent,
            message="Wie wird das Wetter morgen?",
        )
        record_score("weather_forecast", result["scores"])
        assert result["scores"]["tool_selection"] >= SCORE_THRESHOLD, (
            f"tool_selection={result['scores']['tool_selection']}: "
            f"{result['reasoning']}"
        )

    async def test_weather_current(self, real_agent):
        """Agent should use weather tool for current weather."""
        result = await run_and_judge(
            agent=real_agent,
            message="Wie ist das Wetter gerade?",
        )
        record_score("weather_current", result["scores"])
        assert result["scores"]["tool_selection"] >= SCORE_THRESHOLD, (
            f"tool_selection={result['scores']['tool_selection']}: "
            f"{result['reasoning']}"
        )


# ---------------------------------------------------------------------------
# Messaging tools
# ---------------------------------------------------------------------------


class TestMessagingJudge:
    async def test_send_whatsapp(self, real_agent, seed_contact):
        """Agent should use send_whatsapp to send a message."""
        result = await run_and_judge(
            agent=real_agent,
            message="Sende Max eine WhatsApp: Bin in 10 Min da",
        )
        record_score("send_whatsapp", result["scores"])
        assert result["scores"]["tool_selection"] >= SCORE_THRESHOLD, (
            f"tool_selection={result['scores']['tool_selection']}: "
            f"{result['reasoning']}"
        )

    @pytest.mark.skipif(
        not os.environ.get("SIGNAL_PHONE", ""),
        reason="Signal not configured (SIGNAL_PHONE not set)",
    )
    async def test_send_signal(self, real_agent, seed_contact):
        """Agent should use send_signal to send a Signal message."""
        result = await run_and_judge(
            agent=real_agent,
            message="Sende Max eine Signal-Nachricht: Treffen verschoben",
        )
        record_score("send_signal", result["scores"])
        assert result["scores"]["tool_selection"] >= SCORE_THRESHOLD, (
            f"tool_selection={result['scores']['tool_selection']}: "
            f"{result['reasoning']}"
        )

    async def test_get_whatsapp_messages(self, real_agent):
        """Agent should use get_whatsapp_messages to read messages."""
        result = await run_and_judge(
            agent=real_agent,
            message="Was hat Julia geschrieben?",
        )
        record_score("get_whatsapp_messages", result["scores"])
        assert result["scores"]["tool_selection"] >= SCORE_THRESHOLD, (
            f"tool_selection={result['scores']['tool_selection']}: "
            f"{result['reasoning']}"
        )


# ---------------------------------------------------------------------------
# Calendar — create event
# ---------------------------------------------------------------------------


class TestCalendarExtJudge:
    async def test_create_event(self, real_agent):
        """Agent should use create_event for scheduling."""
        result = await run_and_judge(
            agent=real_agent,
            message="Erstelle einen Termin: Zahnarzt morgen 14 Uhr",
        )
        record_score("create_event", result["scores"])
        assert result["scores"]["tool_selection"] >= SCORE_THRESHOLD, (
            f"tool_selection={result['scores']['tool_selection']}: "
            f"{result['reasoning']}"
        )


# ---------------------------------------------------------------------------
# Task listing
# ---------------------------------------------------------------------------


class TestTasksExtJudge:
    async def test_list_tasks(self, real_agent):
        """Agent should use list_tasks for open tasks query."""
        result = await run_and_judge(
            agent=real_agent,
            message="Welche Aufgaben sind offen?",
        )
        record_score("list_tasks", result["scores"])
        assert result["scores"]["tool_selection"] >= SCORE_THRESHOLD, (
            f"tool_selection={result['scores']['tool_selection']}: "
            f"{result['reasoning']}"
        )


# ---------------------------------------------------------------------------
# Memory — remember + recall
# ---------------------------------------------------------------------------


class TestMemoryExtJudge:
    async def test_remember_and_recall(self, real_agent):
        """Agent should use remember then recall for stored facts."""
        chat_id = "judge-memory-recall"

        # Step 1: remember
        result_remember = await run_and_judge(
            agent=real_agent,
            message="Merk dir: Mein WLAN-Passwort ist SuperSecret123",
            chat_id=chat_id,
        )
        record_score("remember_wifi", result_remember["scores"])
        assert result_remember["scores"]["tool_selection"] >= SCORE_THRESHOLD, (
            f"tool_selection={result_remember['scores']['tool_selection']}: "
            f"{result_remember['reasoning']}"
        )

        # Step 2: recall (same chat_id for context)
        result_recall = await run_and_judge(
            agent=real_agent,
            message="Was war nochmal mein WLAN-Passwort?",
            chat_id=chat_id,
        )
        record_score("recall_wifi", result_recall["scores"])
        assert result_recall["scores"]["tool_selection"] >= SCORE_THRESHOLD, (
            f"tool_selection={result_recall['scores']['tool_selection']}: "
            f"{result_recall['reasoning']}"
        )


# ---------------------------------------------------------------------------
# No tool needed — direct answers
# ---------------------------------------------------------------------------


class TestNoToolNeededJudge:
    async def test_general_knowledge(self, real_agent):
        """General knowledge question — no tool needed."""
        result = await run_and_judge(
            agent=real_agent,
            message="Was ist die Hauptstadt von Frankreich?",
        )
        record_score("no_tool_knowledge", result["scores"])
        assert result["scores"]["personality"] >= SCORE_THRESHOLD, (
            f"personality={result['scores']['personality']}: {result['reasoning']}"
        )
        assert result["scores"]["language"] >= SCORE_THRESHOLD

    async def test_explanation(self, real_agent):
        """Explanation request — no tool needed."""
        result = await run_and_judge(
            agent=real_agent,
            message="Erklaere mir was Docker ist",
        )
        record_score("no_tool_explanation", result["scores"])
        assert result["scores"]["response_quality"] >= SCORE_THRESHOLD, (
            f"response_quality={result['scores']['response_quality']}: "
            f"{result['reasoning']}"
        )
        assert result["scores"]["language"] >= SCORE_THRESHOLD

    async def test_thanks(self, real_agent):
        """Simple thanks — no tool needed."""
        result = await run_and_judge(
            agent=real_agent,
            message="Danke!",
        )
        record_score("no_tool_thanks", result["scores"])
        assert result["scores"]["personality"] >= SCORE_THRESHOLD, (
            f"personality={result['scores']['personality']}: {result['reasoning']}"
        )


# ---------------------------------------------------------------------------
# Ambiguous requests
# ---------------------------------------------------------------------------


class TestAmbiguousJudge:
    async def test_whats_new(self, real_agent):
        """Ambiguous: could check calendar, tasks, or smalltalk."""
        result = await run_and_judge(
            agent=real_agent,
            message="Was gibt's Neues?",
        )
        record_score("ambiguous_whats_new", result["scores"])
        # Any reasonable response is acceptable
        assert result["scores"]["personality"] >= SCORE_THRESHOLD, (
            f"personality={result['scores']['personality']}: {result['reasoning']}"
        )
        assert result["scores"]["language"] >= SCORE_THRESHOLD

    async def test_contact_person(self, real_agent, seed_contact):
        """Ambiguous: could use WhatsApp or Signal."""
        result = await run_and_judge(
            agent=real_agent,
            message="Kontaktiere Max",
        )
        record_score("ambiguous_contact", result["scores"])
        assert result["scores"]["personality"] >= SCORE_THRESHOLD, (
            f"personality={result['scores']['personality']}: {result['reasoning']}"
        )


# ---------------------------------------------------------------------------
# Multi-tool — sequential tool calls
# ---------------------------------------------------------------------------


class TestMultiToolJudge:
    async def test_remember_and_create_event(self, real_agent):
        """Agent should use both remember and create_event."""
        result = await run_and_judge(
            agent=real_agent,
            message=(
                "Merk dir dass ich morgen Zahnarzt habe "
                "und erstelle einen Termin dafuer"
            ),
        )
        record_score("multi_remember_event", result["scores"])
        assert result["scores"]["tool_selection"] >= SCORE_THRESHOLD, (
            f"tool_selection={result['scores']['tool_selection']}: "
            f"{result['reasoning']}"
        )
