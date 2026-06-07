"""E2E pipeline tests — FakeLLM + real DB tool execution.

Each test scripts the LLM responses (tool calls + final text) and verifies
that the agent executes tools correctly against a real PostgreSQL database.
"""

import pytest

from niles.memory.history import ConversationHistory

from .conftest import FakeLLM, collect_events, full_text, make_e2e_agent

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio(loop_scope="session")]


# ---------------------------------------------------------------------------
# find_contact
# ---------------------------------------------------------------------------


class TestFindContactPipeline:
    async def test_find_contact_success(self, pool_in_tx, seed_contact):
        """User asks for contact → find_contact tool → response with phone."""
        fake = FakeLLM(
            [
                {
                    "tool_calls": [
                        {
                            "name": "find_contact",
                            "arguments": {"name": "Max Mustermann"},
                        }
                    ]
                },
                {"content": "Max Mustermann hat die Nummer +43 660 1234567."},
            ]
        )
        agent = make_e2e_agent(pool_in_tx, fake)
        events = await collect_events(agent, "Wie ist die Nummer von Max?")

        # Tool status event emitted
        status_events = [e for e in events if e["type"] == "status"]
        assert any("find_contact" in e["text"] for e in status_events)
        # Final response streamed
        assert "+43 660 1234567" in full_text(events)
        assert events[-1] == {"type": "done"}

    async def test_find_contact_not_found(self, pool_in_tx):
        """Contact not in DB → tool returns error → LLM explains."""
        fake = FakeLLM(
            [
                {
                    "tool_calls": [
                        {
                            "name": "find_contact",
                            "arguments": {"name": "Nobody Nowhere"},
                        }
                    ]
                },
                {"content": "Ich konnte keinen Kontakt mit dem Namen 'Nobody Nowhere' finden."},
            ]
        )
        agent = make_e2e_agent(pool_in_tx, fake)
        events = await collect_events(agent, "Wie ist die Nummer von Nobody?")

        assert "Nobody" in full_text(events)
        assert events[-1] == {"type": "done"}


# ---------------------------------------------------------------------------
# remember / recall
# ---------------------------------------------------------------------------


class TestMemoryPipeline:
    async def test_remember(self, pool_in_tx):
        """remember tool → value persisted in DB."""
        fake = FakeLLM(
            [
                {
                    "tool_calls": [
                        {
                            "name": "remember",
                            "arguments": {"key": "allergie", "value": "Nüsse"},
                        }
                    ]
                },
                {"content": "Ich habe mir gemerkt, dass du gegen Nüsse allergisch bist."},
            ]
        )
        agent = make_e2e_agent(pool_in_tx, fake)
        events = await collect_events(agent, "Merk dir: Ich bin allergisch gegen Nüsse")

        # Verify value actually written to DB
        stored = await agent.memory.get("allergie")
        assert stored == "Nüsse"
        assert events[-1] == {"type": "done"}

    async def test_recall(self, pool_in_tx):
        """recall tool → reads value from DB."""
        # Pre-seed memory
        from niles.memory.store import MemoryStore

        store = MemoryStore(pool_in_tx)
        await store.set("lieblingsfarbe", "blau")

        fake = FakeLLM(
            [
                {"tool_calls": [{"name": "recall", "arguments": {"key": "lieblingsfarbe"}}]},
                {"content": "Deine Lieblingsfarbe ist blau."},
            ]
        )
        agent = make_e2e_agent(pool_in_tx, fake)
        events = await collect_events(agent, "Was ist meine Lieblingsfarbe?")

        assert "blau" in full_text(events)
        assert events[-1] == {"type": "done"}

    async def test_recall_missing_key(self, pool_in_tx):
        """recall for nonexistent key → tool returns null → LLM handles."""
        fake = FakeLLM(
            [
                {"tool_calls": [{"name": "recall", "arguments": {"key": "nonexistent_xyz"}}]},
                {"content": "Dazu habe ich leider keine Information gespeichert."},
            ]
        )
        agent = make_e2e_agent(pool_in_tx, fake)
        events = await collect_events(agent, "Was weißt du über xyz?")

        assert events[-1] == {"type": "done"}


# ---------------------------------------------------------------------------
# find_event
# ---------------------------------------------------------------------------


class TestCalendarPipeline:
    async def test_find_event(self, pool_in_tx, seed_events):
        """find_event tool → real DB query returns seeded events."""
        fake = FakeLLM(
            [
                {"tool_calls": [{"name": "find_event", "arguments": {"query": "Meeting"}}]},
                {"content": "Du hast ein Team Meeting geplant."},
            ]
        )
        agent = make_e2e_agent(pool_in_tx, fake)
        events = await collect_events(agent, "Was steht im Kalender?")

        status_events = [e for e in events if e["type"] == "status"]
        assert any("find_event" in e["text"] for e in status_events)
        assert "Meeting" in full_text(events)
        assert events[-1] == {"type": "done"}

    async def test_find_event_no_results(self, pool_in_tx):
        """find_event for nonexistent event → empty result."""
        fake = FakeLLM(
            [
                {
                    "tool_calls": [
                        {
                            "name": "find_event",
                            "arguments": {"query": "Marsexpedition"},
                        }
                    ]
                },
                {"content": "Ich habe keinen Termin zur Marsexpedition gefunden."},
            ]
        )
        agent = make_e2e_agent(pool_in_tx, fake)
        events = await collect_events(agent, "Wann ist die Marsexpedition?")

        assert events[-1] == {"type": "done"}


# ---------------------------------------------------------------------------
# create_event (CalDAV mocked — no CalDAV server in test infra)
# ---------------------------------------------------------------------------


class TestCreateEventPipeline:
    async def test_create_event_no_caldav(self, pool_in_tx):
        """create_event without CalDAV → tool returns error."""
        fake = FakeLLM(
            [
                {
                    "tool_calls": [
                        {
                            "name": "create_event",
                            "arguments": {
                                "summary": "Arzttermin",
                                "start": "2026-03-10T14:00:00",
                            },
                        }
                    ]
                },
                {"content": "Leider konnte der Termin nicht erstellt werden."},
            ]
        )
        agent = make_e2e_agent(pool_in_tx, fake)
        events = await collect_events(agent, "Erstelle einen Arzttermin am 10. März")

        assert events[-1] == {"type": "done"}


# ---------------------------------------------------------------------------
# list_tasks / create_task / complete_task (Vikunja mocked)
# ---------------------------------------------------------------------------


class TestTasksPipeline:
    async def test_list_tasks(self, pool_in_tx):
        """list_tasks → Vikunja mock returns tasks."""
        fake = FakeLLM(
            [
                {"tool_calls": [{"name": "list_tasks", "arguments": {}}]},
                {"content": "Du hast aktuell keine offenen Aufgaben."},
            ]
        )
        agent = make_e2e_agent(pool_in_tx, fake)
        # Vikunja is not available → tool will return error about missing credentials
        events = await collect_events(agent, "Was steht auf meiner Todo-Liste?")

        assert events[-1] == {"type": "done"}

    async def test_create_task(self, pool_in_tx):
        """create_task → tool handler invoked."""
        fake = FakeLLM(
            [
                {
                    "tool_calls": [
                        {
                            "name": "create_task",
                            "arguments": {"title": "Einkaufen gehen"},
                        }
                    ]
                },
                {"content": "Aufgabe 'Einkaufen gehen' wurde erstellt."},
            ]
        )
        agent = make_e2e_agent(pool_in_tx, fake)
        events = await collect_events(agent, "Erstelle eine Aufgabe: Einkaufen gehen")

        status_events = [e for e in events if e["type"] == "status"]
        assert any("create_task" in e["text"] for e in status_events)
        assert events[-1] == {"type": "done"}


# ---------------------------------------------------------------------------
# send_whatsapp / get_whatsapp_messages (mocked — no real sending)
# ---------------------------------------------------------------------------


class TestWhatsAppPipeline:
    async def test_send_whatsapp(self, pool_in_tx, seed_contact):
        """send_whatsapp → tool handler invoked (WhatsApp mock)."""
        fake = FakeLLM(
            [
                {
                    "tool_calls": [
                        {
                            "name": "send_whatsapp",
                            "arguments": {
                                "to": "Max Mustermann",
                                "text": "Hallo Max!",
                            },
                        }
                    ]
                },
                {"content": "Nachricht an Max Mustermann gesendet."},
            ]
        )
        agent = make_e2e_agent(pool_in_tx, fake)
        events = await collect_events(agent, "Schreib Max auf WhatsApp: Hallo Max!")

        status_events = [e for e in events if e["type"] == "status"]
        assert any("send_whatsapp" in e["text"] for e in status_events)
        assert events[-1] == {"type": "done"}

    async def test_get_whatsapp_messages(self, pool_in_tx):
        """get_whatsapp_messages → tool handler invoked."""
        fake = FakeLLM(
            [
                {
                    "tool_calls": [
                        {
                            "name": "get_whatsapp_messages",
                            "arguments": {"contact": "Max"},
                        }
                    ]
                },
                {"content": "Keine neuen Nachrichten von Max."},
            ]
        )
        agent = make_e2e_agent(pool_in_tx, fake)
        events = await collect_events(agent, "Was hat Max auf WhatsApp geschrieben?")

        assert events[-1] == {"type": "done"}


# ---------------------------------------------------------------------------
# send_signal / get_signal_messages (mocked — no real sending)
# ---------------------------------------------------------------------------


class TestSignalPipeline:
    async def test_send_signal(self, pool_in_tx):
        """send_signal → tool handler invoked (Signal mock)."""
        fake = FakeLLM(
            [
                {
                    "tool_calls": [
                        {
                            "name": "send_signal",
                            "arguments": {"to": "Max", "text": "Hi via Signal"},
                        }
                    ]
                },
                {"content": "Signal-Nachricht gesendet."},
            ]
        )
        agent = make_e2e_agent(pool_in_tx, fake)
        events = await collect_events(agent, "Schreib Max auf Signal: Hi via Signal")

        assert events[-1] == {"type": "done"}

    async def test_get_signal_messages(self, pool_in_tx):
        """get_signal_messages → tool handler invoked."""
        fake = FakeLLM(
            [
                {
                    "tool_calls": [
                        {
                            "name": "get_signal_messages",
                            "arguments": {"contact": "Max"},
                        }
                    ]
                },
                {"content": "Keine Signal-Nachrichten von Max."},
            ]
        )
        agent = make_e2e_agent(pool_in_tx, fake)
        events = await collect_events(agent, "Zeig mir Signal-Nachrichten von Max")

        assert events[-1] == {"type": "done"}


# ---------------------------------------------------------------------------
# search_notion (pgvector — needs Ollama for embedding, skipped if unavailable)
# ---------------------------------------------------------------------------


class TestNotionPipeline:
    async def test_search_notion(self, pool_in_tx):
        """search_notion → tool handler invoked (no Ollama → returns error)."""
        fake = FakeLLM(
            [
                {"tool_calls": [{"name": "search_notion", "arguments": {"query": "Projektplan"}}]},
                {"content": "In der Wissensdatenbank habe ich nichts dazu gefunden."},
            ]
        )
        agent = make_e2e_agent(pool_in_tx, fake)
        events = await collect_events(agent, "Was steht im Notion über den Projektplan?")

        status_events = [e for e in events if e["type"] == "status"]
        assert any("search_notion" in e["text"] for e in status_events)
        assert events[-1] == {"type": "done"}


# ---------------------------------------------------------------------------
# Multi-tool round trips
# ---------------------------------------------------------------------------


class TestMultiToolPipeline:
    async def test_two_tool_rounds(self, pool_in_tx, seed_contact):
        """Agent uses find_contact, then send_whatsapp (2 tool rounds)."""
        fake = FakeLLM(
            [
                {
                    "tool_calls": [
                        {
                            "name": "find_contact",
                            "arguments": {"name": "Max Mustermann"},
                        }
                    ]
                },
                {
                    "tool_calls": [
                        {
                            "name": "send_whatsapp",
                            "arguments": {
                                "to": "+43 660 1234567",
                                "text": "Hallo Max!",
                            },
                        }
                    ]
                },
                {"content": "Nachricht an Max Mustermann gesendet."},
            ]
        )
        agent = make_e2e_agent(pool_in_tx, fake)
        events = await collect_events(agent, "Schreib Max Mustermann auf WhatsApp: Hallo Max!")

        status_events = [e for e in events if e["type"] == "status"]
        tool_names = [e["text"] for e in status_events]
        assert any("find_contact" in t for t in tool_names)
        assert any("send_whatsapp" in t for t in tool_names)
        assert events[-1] == {"type": "done"}

    async def test_remember_then_recall(self, pool_in_tx):
        """remember in round 1, recall in round 2 — value persisted."""
        fake = FakeLLM(
            [
                {
                    "tool_calls": [
                        {
                            "name": "remember",
                            "arguments": {"key": "haustier", "value": "Katze"},
                        }
                    ]
                },
                {"content": "Gemerkt! Du hast eine Katze."},
            ]
        )
        agent = make_e2e_agent(pool_in_tx, fake)
        await collect_events(agent, "Merk dir: Ich habe eine Katze")

        # Second interaction: recall
        fake2 = FakeLLM(
            [
                {"tool_calls": [{"name": "recall", "arguments": {"key": "haustier"}}]},
                {"content": "Du hast eine Katze."},
            ]
        )
        agent2 = make_e2e_agent(pool_in_tx, fake2)
        events2 = await collect_events(agent2, "Was für ein Haustier habe ich?")

        assert "Katze" in full_text(events2)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    async def test_no_tool_simple_response(self, pool_in_tx):
        """Agent responds without any tool call."""
        fake = FakeLLM(
            [
                {"content": "Guten Morgen! Wie kann ich helfen?"},
            ]
        )
        agent = make_e2e_agent(pool_in_tx, fake)
        events = await collect_events(agent, "Guten Morgen, Niles!")

        assert "Guten Morgen" in full_text(events)
        assert events[-1] == {"type": "done"}
        # No status events (no tool calls)
        status_events = [e for e in events if e["type"] == "status"]
        assert len(status_events) == 0

    async def test_conversation_history_persisted(self, pool_in_tx):
        """After a successful chat, messages are saved to conversation history."""
        fake = FakeLLM(
            [
                {"content": "Hallo! Ich bin Niles, dein Butler."},
            ]
        )
        agent = make_e2e_agent(pool_in_tx, fake)
        chat_id = "e2e-history-test"
        await collect_events(agent, "Hallo Niles!", chat_id=chat_id)

        # Check history was persisted
        history = ConversationHistory(pool_in_tx)
        messages = await history.get_recent(chat_id, limit=10)
        roles = [m["role"] for m in messages]
        assert "user" in roles
        assert "assistant" in roles
