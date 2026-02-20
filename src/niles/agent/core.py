"""Niles agent core – event processing with LLM tool-call loop."""

import json
import logging
import time
from types import SimpleNamespace

import httpx
from openai import AsyncOpenAI

from ..actions.calendar import CalendarAction
from ..actions.contacts import ContactsAction
from ..actions.whatsapp import WhatsAppAction
from ..config import Settings
from ..mcp.client import MCPManager
from ..sync.manager import CalendarSourceManager
from ..memory.history import ConversationHistory
from ..memory.store import MemoryStore
from ..whatsapp_store import WhatsAppSessionStore
from .prompts import build_system_prompt, load_system_prompt

logger = logging.getLogger(__name__)

# Tool definitions in OpenAI function-calling format
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "find_contact",
            "description": "Sucht einen Kontakt nach Name und gibt alle Telefonnummern (phone = bevorzugte, phones = alle mit Typ) und Email zurück.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Name des Kontakts (oder Teil davon)",
                    }
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_whatsapp",
            "description": "Sendet eine WhatsApp-Nachricht an eine Telefonnummer oder einen Kontaktnamen.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {
                        "type": "string",
                        "description": "Telefonnummer (z.B. '436601234567') oder Kontaktname",
                    },
                    "text": {
                        "type": "string",
                        "description": "Nachrichtentext",
                    },
                },
                "required": ["to", "text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remember",
            "description": "Speichert einen Fakt oder eine Information dauerhaft im Gedächtnis. Nutze einen kurzen, beschreibenden Schlüssel.",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "Kurzer Schlüssel (z.B. 'zahnarzt_termin', 'lieblings_essen')",
                    },
                    "value": {
                        "type": "string",
                        "description": "Der zu merkende Inhalt",
                    },
                },
                "required": ["key", "value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recall",
            "description": "Ruft eine gespeicherte Information aus dem Gedächtnis ab.",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "Schlüssel der gespeicherten Information",
                    },
                },
                "required": ["key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_event",
            "description": "Liest bestehende Kalendertermine aus der Datenbank. Nutze dieses Tool wenn der Benutzer nach Terminen fragt, wissen will wann etwas stattfindet, oder seinen Kalender sehen will. Wenn nur date_from angegeben wird, werden automatisch nur Termine an diesem Tag zurueckgegeben.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Suchbegriff (Name, Ort, Beschreibung). Leer lassen fuer reine Datumssuche.",
                    },
                    "date_from": {
                        "type": "string",
                        "description": "Startdatum (ISO-Format, z.B. '2026-02-20'). Bei 'morgen' oder einem einzelnen Tag NUR date_from setzen, NICHT date_to.",
                    },
                    "date_to": {
                        "type": "string",
                        "description": "Enddatum (ISO-Format). Nur setzen bei expliziten Zeitraeumen wie 'diese Woche' oder 'naechste 7 Tage'. NICHT setzen bei Fragen nach einem einzelnen Tag.",
                    },
                    "calendar": {
                        "type": "string",
                        "description": "Name des Kalenders in dem gesucht werden soll (optional). Bei Geburtstags-Fragen den Geburtstags-Kalender verwenden.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_event",
            "description": "Erstellt einen NEUEN Kalendertermin via CalDAV. Nur verwenden wenn der Benutzer explizit einen neuen Termin anlegen will.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Titel des Termins",
                    },
                    "start": {
                        "type": "string",
                        "description": "Startzeit (ISO-Format, z.B. '2026-02-20T14:00')",
                    },
                    "end": {
                        "type": "string",
                        "description": "Endzeit (ISO-Format). Optional, Standard: 1 Stunde nach Start.",
                    },
                    "description": {
                        "type": "string",
                        "description": "Beschreibung des Termins. Optional.",
                    },
                    "location": {
                        "type": "string",
                        "description": "Ort des Termins. Optional.",
                    },
                },
                "required": ["summary", "start"],
            },
        },
    },
]

MAX_TOOL_ROUNDS = 5
MAX_MCP_RESULT_SIZE = 100_000  # 100 KB limit for MCP tool results


class NilesAgent:
    """
    Event processing pipeline:
    1. Receive event
    2. Load conversation history and memory context
    3. Build messages (system prompt + history + user message)
    4. Call LLM with tools
    5. Execute tool calls if any
    6. Feed results back to LLM
    7. Save conversation history
    8. Return final response
    """

    def __init__(
        self,
        config: Settings,
        contacts: ContactsAction,
        whatsapp: WhatsAppAction,
        memory: MemoryStore,
        history: ConversationHistory,
        mcp_manager: MCPManager | None = None,
        calendar: CalendarAction | None = None,
        calendar_manager: CalendarSourceManager | None = None,
        wa_store: WhatsAppSessionStore | None = None,
    ):
        self.config = config
        self.llm = AsyncOpenAI(
            base_url=config.llm_base_url,
            api_key="not-needed",
        )
        self.model = config.llm_model
        self.contacts = contacts
        self.whatsapp = whatsapp
        self.memory = memory
        self.history = history
        self.mcp = mcp_manager
        self.calendar = calendar
        self.calendar_manager = calendar_manager
        self.wa_store = wa_store
        self.base_prompt = load_system_prompt()
        # Cached calendar source names (refreshed every 5 minutes)
        self._source_names_cache: list[str] = []
        self._source_names_ts: float = 0.0
        # Pending phone choice: chat_id → {phones, text, contact_name}
        self._pending_phone_choices: dict[str, dict] = {}

    async def _resolve_wa_instance(self, chat_id: str) -> str | None:
        """Look up per-user WhatsApp instance from chat_id."""
        if self.wa_store and chat_id.startswith("web-user-"):
            try:
                uid = int(chat_id.split("-", 2)[2])
                session = await self.wa_store.get_session(uid)
                if session and session["status"] == "connected":
                    return session["instance_name"]
            except (ValueError, IndexError):
                pass
        return None

    async def _handle_phone_choice(self, chat_id: str, content: str) -> str | None:
        """If user is responding to a phone choice prompt, send directly.

        Returns the reply text if handled, or None if not a pending choice.
        """
        if chat_id not in self._pending_phone_choices:
            return None

        # Expire stale choices (5 min TTL)
        pending_peek = self._pending_phone_choices[chat_id]
        if time.monotonic() > pending_peek.get("expires_at", float("inf")):
            del self._pending_phone_choices[chat_id]
            return None

        # Accept "1", "2", "1.", "2." etc.
        stripped = content.strip().rstrip(".")
        if not stripped.isdigit():
            # Not a number selection — clear pending state and let LLM handle
            del self._pending_phone_choices[chat_id]
            return None

        choice_idx = int(stripped) - 1
        pending = self._pending_phone_choices[chat_id]  # peek, don't pop yet

        if choice_idx < 0 or choice_idx >= len(pending["phones"]):
            count = len(pending["phones"])
            return f"Ungültige Auswahl. Bitte wähle 1 bis {count}."

        self._pending_phone_choices.pop(chat_id)  # valid choice — remove state
        phone = pending["phones"][choice_idx]["number"]
        instance = await self._resolve_wa_instance(chat_id)

        result = await self.whatsapp.send_message(
            to=phone, text=pending["text"], instance=instance,
        )
        if "error" not in result:
            return f"Nachricht an {pending['contact_name']} (00{phone}) gesendet."
        return f"Fehler beim Senden: {result['error']}"

    async def _prepare_messages(self, event: dict) -> tuple[str, list[dict], list]:
        """Shared setup for process_event and process_event_stream.

        Builds the messages list but does NOT persist the user message to
        history.  Callers save both user and assistant messages together
        after a successful LLM response to avoid orphaned records.

        Returns (chat_id, messages, all_tools).
        """
        chat_id = event["from"]

        memories = await self.memory.list_all()
        source_names = await self._get_calendar_source_names()

        system_prompt = build_system_prompt(
            self.base_prompt,
            memories,
            timezone=self.config.timezone,
            calendar_sources=source_names,
        )

        history_messages = await self.history.get_recent(chat_id)
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend({"role": m["role"], "content": m["content"]} for m in history_messages)
        messages.append({"role": "user", "content": event["content"]})

        all_tools = TOOLS + (self.mcp.get_openai_tools() if self.mcp else [])
        return chat_id, messages, all_tools

    _SOURCE_CACHE_TTL = 300  # 5 minutes

    async def _get_calendar_source_names(self) -> list[str]:
        """Return enabled calendar source names, cached with a 5-minute TTL."""
        if not self.calendar_manager:
            return []
        now = time.monotonic()
        if now - self._source_names_ts < self._SOURCE_CACHE_TTL:
            return self._source_names_cache
        try:
            sources = await self.calendar_manager.get_sources()
            self._source_names_cache = [
                s["name"] for s in sources if s.get("enabled", True)
            ]
            self._source_names_ts = now
        except Exception:
            logger.warning("Failed to load calendar sources for prompt")
        return self._source_names_cache

    async def process_event_stream(self, event: dict):
        """Async generator: yields status updates + streamed text chunks.

        Every LLM call uses stream=True so even simple queries (no tool calls)
        are delivered word-by-word.  When the LLM requests tool calls, the
        streamed deltas are accumulated, tools executed, and the loop repeats.

        Yields dicts with:
          {"type": "status", "text": "find_contact..."}
          {"type": "chunk",  "text": "partial text"}
          {"type": "done"}
        """
        chat_id = event["from"]

        # Intercept pending phone choice (bypass LLM entirely)
        reply = await self._handle_phone_choice(chat_id, event["content"])
        if reply is not None:
            await self.history.add_message(chat_id, "user", event["content"])
            await self.history.add_message(chat_id, "assistant", reply)
            yield {"type": "chunk", "text": reply}
            yield {"type": "done"}
            return

        chat_id, messages, all_tools = await self._prepare_messages(event)

        for _ in range(MAX_TOOL_ROUNDS):
            try:
                stream = await self.llm.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=all_tools,
                    temperature=0.7,
                    stream=True,
                )
            except Exception as e:
                logger.error("LLM call failed: %s", e)
                yield {"type": "chunk", "text": "Entschuldigung, ich konnte die Anfrage nicht verarbeiten."}
                yield {"type": "done"}
                return

            # Consume the stream, accumulating text content and tool-call deltas
            full_content = ""
            tool_calls_by_idx: dict[int, dict] = {}
            finish_reason = None

            async for chunk in stream:
                choice = chunk.choices[0]
                finish_reason = choice.finish_reason or finish_reason

                if choice.delta.content:
                    full_content += choice.delta.content
                    yield {"type": "chunk", "text": choice.delta.content}

                if choice.delta.tool_calls:
                    for tc_delta in choice.delta.tool_calls:
                        idx = tc_delta.index
                        if idx not in tool_calls_by_idx:
                            tool_calls_by_idx[idx] = {"id": "", "name": "", "arguments": ""}
                        if tc_delta.id:
                            tool_calls_by_idx[idx]["id"] = tc_delta.id
                        if tc_delta.function:
                            if tc_delta.function.name:
                                tool_calls_by_idx[idx]["name"] += tc_delta.function.name
                            if tc_delta.function.arguments:
                                tool_calls_by_idx[idx]["arguments"] += tc_delta.function.arguments

            # No tool calls → text was already streamed, save and finish
            if finish_reason != "tool_calls" or not tool_calls_by_idx:
                if full_content:
                    await self.history.add_message(chat_id, "user", event["content"])
                    await self.history.add_message(chat_id, "assistant", full_content)
                else:
                    logger.warning("LLM returned empty streaming response for event: %s", event.get("content", "")[:100])
                    yield {"type": "chunk", "text": "Entschuldigung, ich habe keine Antwort erhalten."}
                yield {"type": "done"}
                return

            # Tool calls detected → build assistant message and execute tools
            assistant_msg = {
                "role": "assistant",
                "content": full_content or None,
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {"name": tc["name"], "arguments": tc["arguments"]},
                    }
                    for tc in (tool_calls_by_idx[i] for i in sorted(tool_calls_by_idx))
                ],
            }
            messages.append(assistant_msg)

            for tc_dict in assistant_msg["tool_calls"]:
                yield {"type": "status", "text": f"{tc_dict['function']['name']}..."}
                tool_call = SimpleNamespace(
                    id=tc_dict["id"],
                    function=SimpleNamespace(
                        name=tc_dict["function"]["name"],
                        arguments=tc_dict["function"]["arguments"],
                    ),
                )
                result = await self._execute_tool_call(tool_call, chat_id)
                logger.info("Tool result [%s]: %s", tool_call.id, result)

                # choose_phone → bypass LLM, send list directly to user
                if isinstance(result, dict) and "choose_phone" in result:
                    text = result["choose_phone"]
                    await self.history.add_message(chat_id, "user", event["content"])
                    await self.history.add_message(chat_id, "assistant", text)
                    yield {"type": "chunk", "text": text}
                    yield {"type": "done"}
                    return

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result, ensure_ascii=False),
                })
        else:
            yield {"type": "chunk", "text": "Ich konnte die Anfrage nicht abschliessen."}

        yield {"type": "done"}

    async def process_event(self, event: dict) -> str:
        """
        Main entry point for all events.

        Args:
            event: {"type": str, "from": str, "content": str, "metadata": dict}

        Returns:
            Response text
        """
        chat_id = event["from"]

        # Intercept pending phone choice (bypass LLM entirely)
        reply = await self._handle_phone_choice(chat_id, event["content"])
        if reply is not None:
            await self.history.add_message(chat_id, "user", event["content"])
            await self.history.add_message(chat_id, "assistant", reply)
            return reply

        chat_id, messages, all_tools = await self._prepare_messages(event)

        # Tool-call loop: LLM may request multiple rounds of tool calls
        for _ in range(MAX_TOOL_ROUNDS):
            try:
                response = await self.llm.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=all_tools,
                    temperature=0.7,
                )
            except Exception as e:
                logger.error("LLM call failed: %s", e)
                return "Entschuldigung, ich konnte die Anfrage nicht verarbeiten."

            choice = response.choices[0]

            # No tool calls – return the text response
            if choice.finish_reason != "tool_calls" or not choice.message.tool_calls:
                content = choice.message.content or ""
                if not content:
                    logger.warning("LLM returned empty response for event: %s", event.get("content", "")[:100])
                # Save both messages together to avoid orphaned records
                if content:
                    await self.history.add_message(chat_id, "user", event["content"])
                    await self.history.add_message(chat_id, "assistant", content)
                return content

            # Append assistant message with tool calls (serialize to dict)
            messages.append(choice.message.model_dump(exclude_unset=True))

            # Execute each tool call and append results
            for tool_call in choice.message.tool_calls:
                result = await self._execute_tool_call(tool_call, chat_id)
                logger.info("Tool result [%s]: %s", tool_call.id, result)

                # choose_phone → bypass LLM, send list directly to user
                if isinstance(result, dict) and "choose_phone" in result:
                    text = result["choose_phone"]
                    await self.history.add_message(chat_id, "user", event["content"])
                    await self.history.add_message(chat_id, "assistant", text)
                    return text

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )

        logger.warning("Max tool rounds reached")
        return "Ich konnte die Anfrage nicht abschließen."

    async def _execute_tool_call(self, tool_call, chat_id: str = "") -> dict:
        """Execute a single tool call and return the result."""
        name = tool_call.function.name
        try:
            args = json.loads(tool_call.function.arguments)
        except json.JSONDecodeError:
            return {"error": "Invalid arguments"}

        logger.info("Tool call [%s]: %s(%s)", tool_call.id, name, args)

        if name == "find_contact":
            contact = await self.contacts.find_by_name(args["name"])
            if contact:
                return contact
            return {"error": f"Kontakt '{args['name']}' nicht gefunden"}

        if name == "send_whatsapp":
            if not self.config.feature_tool_send_whatsapp:
                logger.info("send_whatsapp tool disabled via feature flag")
                return {"error": "WhatsApp senden ist derzeit deaktiviert"}

            to = args["to"]
            text = args["text"]

            # If 'to' looks like a name (not a number), resolve it first
            if not to.replace("+", "").replace(" ", "").isdigit():
                contact = await self.contacts.find_by_name(to)
                if not contact:
                    return {"error": f"Kontakt '{args['to']}' nicht gefunden"}
                phones = contact.get("phones", [])
                if len(phones) > 1:
                    # Multiple numbers — store state and ask user to choose
                    self._pending_phone_choices[chat_id] = {
                        "phones": phones,
                        "text": text,
                        "contact_name": contact["full_name"],
                        "expires_at": time.monotonic() + 300,
                    }
                    lines = [f"Es gibt mehrere Nummern für {contact['full_name']}:"]
                    for i, p in enumerate(phones, 1):
                        lines.append(f"{i}. 00{p['number']} ({p['type']})")
                    return {"choose_phone": "\n".join(lines)}
                if not contact.get("phone"):
                    return {"error": f"Kontakt '{args['to']}' hat keine Telefonnummer"}
                to = contact["phone"]

            instance = await self._resolve_wa_instance(chat_id)

            result = await self.whatsapp.send_message(
                to=to, text=text, instance=instance,
            )
            return {"status": "sent", "to": to} if "error" not in result else result

        if name == "remember":
            await self.memory.set(args["key"], args["value"])
            return {"status": "saved", "key": args["key"]}

        if name == "recall":
            value = await self.memory.get(args["key"])
            if value is not None:
                return {"key": args["key"], "value": value}
            return {"error": f"Nichts gespeichert unter '{args['key']}'"}

        if name == "find_event":
            if not self.calendar:
                return {"error": "Kalender ist nicht konfiguriert"}
            events = await self.calendar.find_by_query(
                query=args.get("query", ""),
                date_from=args.get("date_from", ""),
                date_to=args.get("date_to", ""),
                calendar=args.get("calendar", ""),
            )
            if events:
                return {"events": events, "count": len(events)}
            return {"error": "Keine Termine gefunden"}

        if name == "create_event":
            if not self.calendar_manager:
                return {"error": "Kalender ist nicht konfiguriert"}
            try:
                writable = await self.calendar_manager.get_writable_source()
                if not writable:
                    return {"error": "Kein beschreibbarer Kalender konfiguriert"}
                return await self.calendar_manager.create_event(
                    source=writable,
                    summary=args["summary"],
                    dtstart_str=args["start"],
                    dtend_str=args.get("end"),
                    description=args.get("description", ""),
                    location=args.get("location", ""),
                )
            except httpx.HTTPError as e:
                logger.error("HTTP error creating event: %s", e)
                return {"error": "Termin konnte nicht erstellt werden (Netzwerkfehler)"}
            except Exception as e:
                logger.error("Failed to create event: %s", e)
                return {"error": "Termin konnte nicht erstellt werden"}

        # MCP tools (prefixed with mcp__)
        if self.mcp and self.mcp.is_mcp_tool(name):
            try:
                result_text = await self.mcp.call_tool(name, args)
                if len(result_text) > MAX_MCP_RESULT_SIZE:
                    result_text = result_text[:MAX_MCP_RESULT_SIZE] + "\n...[truncated]"
                return {"result": result_text}
            except Exception as e:
                logger.error("MCP tool call failed [%s]: %s", name, e)
                return {"error": f"MCP tool error: {e}"}

        return {"error": f"Unknown tool: {name}"}
