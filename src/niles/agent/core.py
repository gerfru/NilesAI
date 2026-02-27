"""Niles agent core – event processing with LLM tool-call loop."""

import json
import logging
import re
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from types import SimpleNamespace

import httpx
from openai import AsyncOpenAI

from ..metrics import LLM_DURATION, LLM_TOKENS, TOOL_CALLS

from ..actions.calendar import CalendarAction
from ..actions.contacts import ContactsAction, normalize_phone
from ..actions.tasks import TasksAction
from ..actions.signal import SignalAction
from ..actions.whatsapp import WhatsAppAction
from ..config import Settings
from ..mcp.client import MCPManager
from ..sync.manager import CalendarSourceManager
from ..memory.history import ConversationHistory
from ..memory.store import MemoryStore
from ..signal_store import SignalMessageStore
from ..vikunja_store import VikunjaCredentialStore
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
            "name": "get_whatsapp_messages",
            # Summarization instruction (2/3) — keep in sync with:
            # 1/3: config/soul.md "Nachrichten lesen"
            # 3/3: hinweis field in get_whatsapp_messages result below
            "description": (
                "Liest WhatsApp-Nachrichten aus einem Chat (max. 30 Tage). "
                "Suche nach Kontaktname oder Telefonnummer. "
                "Gibt ein Transcript zurueck. "
                "Nach dem Lesen: fasse die wichtigsten Punkte zusammen "
                "(Termine, Abmachungen, offene Fragen, wichtige Infos). "
                "Gib NICHT das rohe Transcript wieder."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "contact": {
                        "type": "string",
                        "description": (
                            "Kontaktname oder Telefonnummer (erforderlich)."
                        ),
                    },
                },
                "required": ["contact"],
            },
        },
    },
    # --- Signal Tools ---
    {
        "type": "function",
        "function": {
            "name": "send_signal",
            "description": "Sendet eine Signal-Nachricht an eine Telefonnummer oder einen Kontaktnamen.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {
                        "type": "string",
                        "description": "Telefonnummer (z.B. '+4366012345678') oder Kontaktname",
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
            "name": "get_signal_messages",
            "description": (
                "Liest Signal-Nachrichten aus einem Chat (max. 30 Tage). "
                "Suche nach Kontaktname oder Telefonnummer. "
                "Gibt ein Transcript zurueck. "
                "Nach dem Lesen: fasse die wichtigsten Punkte zusammen "
                "(Termine, Abmachungen, offene Fragen, wichtige Infos). "
                "Gib NICHT das rohe Transcript wieder."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "contact": {
                        "type": "string",
                        "description": (
                            "Kontaktname oder Telefonnummer (erforderlich)."
                        ),
                    },
                },
                "required": ["contact"],
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
                        "description": "Kalenderquelle zum Filtern (z.B. 'Geburtstage', 'Arbeit'). NUR bei Geburtstags-Fragen oder wenn der Benutzer explizit einen bestimmten Kalender nennt. Bei allgemeinen Fragen wie 'was steht an' NICHT setzen — leer lassen damit alle Kalender durchsucht werden.",
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
    # --- Vikunja Task Tools ---
    {
        "type": "function",
        "function": {
            "name": "list_tasks",
            "description": (
                "Listet offene Aufgaben aus Vikunja. "
                "Ohne Parameter werden alle offenen Aufgaben zurückgegeben."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "project": {
                        "type": "string",
                        "description": (
                            "Projektname zum Filtern. Optional. Leer = alle Projekte."
                        ),
                    },
                    "include_done": {
                        "type": "boolean",
                        "description": (
                            "Auch erledigte Aufgaben anzeigen. Standard: false."
                        ),
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_task",
            "description": (
                "Erstellt eine neue Aufgabe in Vikunja. "
                "Nur verwenden wenn der Benutzer explizit eine Aufgabe "
                "oder ein Todo anlegen will."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Titel der Aufgabe.",
                    },
                    "description": {
                        "type": "string",
                        "description": "Beschreibung der Aufgabe. Optional.",
                    },
                    "due_date": {
                        "type": "string",
                        "description": (
                            "Fälligkeitsdatum (ISO-Format, "
                            "z.B. '2026-02-25T18:00'). Optional."
                        ),
                    },
                    "priority": {
                        "type": "integer",
                        "description": (
                            "Priorität: 0=keine, 1=niedrig, 2=mittel, "
                            "3=hoch, 4=dringend. Standard: 0."
                        ),
                    },
                    "project": {
                        "type": "string",
                        "description": (
                            "Projektname. Optional. Leer = Standard-Projekt."
                        ),
                    },
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "complete_task",
            "description": (
                "Markiert eine Aufgabe als erledigt. "
                "Sucht nach dem Titel in offenen Aufgaben."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": (
                            "Titel oder Teil des Titels der Aufgabe "
                            "die erledigt werden soll."
                        ),
                    },
                },
                "required": ["title"],
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
        tasks: TasksAction | None = None,
        vikunja_store: VikunjaCredentialStore | None = None,
        signal: SignalAction | None = None,
        signal_store: SignalMessageStore | None = None,
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
        self.tasks = tasks
        self.vikunja_store = vikunja_store
        self.signal = signal
        self.signal_store = signal_store
        self.base_prompt = load_system_prompt()
        # Cached calendar source names (refreshed every 5 minutes)
        self._source_names_cache: list[str] = []
        self._source_names_ts: float = 0.0
        # Pending phone choice: chat_id → {phones, text, contact_name}
        self._pending_phone_choices: dict[str, dict] = {}

    async def _resolve_user_id(self, chat_id: str) -> int | None:
        """Extract user_id from chat_id, resolving phone lookups as needed.

        Supports:
          - web-user-{uid}  → uid directly
          - wa-self-{phone}  → phone lookup via wa_store
        """
        if chat_id.startswith("web-user-"):
            try:
                return int(chat_id.split("-", 2)[2])
            except (ValueError, IndexError):
                return None
        if chat_id.startswith("wa-self-") and self.wa_store:
            phone = chat_id.split("-", 2)[2]
            session = await self.wa_store.get_by_phone(phone)
            if session:
                return session["user_id"]
        return None

    async def _resolve_wa_instance(self, chat_id: str) -> str | None:
        """Look up per-user WhatsApp instance from chat_id."""
        uid = await self._resolve_user_id(chat_id)
        if uid is not None and self.wa_store:
            session = await self.wa_store.get_session(uid)
            if session and session["status"] == "connected":
                return session["instance_name"]
        return None

    async def _resolve_contact_phone(
        self, name_or_number: str
    ) -> tuple[str | None, dict | None]:
        """Resolve a contact name or phone number to a normalized phone string.

        Returns (phone, None) on success or (None, error_dict) on failure.
        Phone is returned without '+' prefix.
        """
        raw = name_or_number.strip().lstrip("@")
        if raw.replace("+", "").replace(" ", "").isdigit():
            clean = raw.replace(" ", "").lstrip("+")
            return normalize_phone(clean), None
        # Name lookup
        contact = await self.contacts.find_by_name(raw)
        if not contact or not contact.get("phone"):
            return None, {"error": f"Kontakt '{name_or_number}' nicht gefunden"}
        return contact["phone"], None

    async def _get_own_phone_number(self, chat_id: str) -> str | None:
        """Get the user's own WhatsApp phone number from their session.

        For self-chat (wa-self-{phone}), extracts the phone directly.
        For web users (web-user-{uid}), looks up from wa_store.
        """
        if chat_id.startswith("wa-self-"):
            return chat_id.split("-", 2)[2]
        uid = await self._resolve_user_id(chat_id)
        if uid is not None and self.wa_store:
            session = await self.wa_store.get_session(uid)
            if session and session.get("phone_number"):
                return session["phone_number"].replace("+", "").replace(" ", "")
        return None

    async def _resolve_vikunja_tasks(self, chat_id: str) -> TasksAction | None:
        """Resolve per-user Vikunja credentials."""
        if self.vikunja_store:
            uid = await self._resolve_user_id(chat_id)
            if uid is not None:
                creds = await self.vikunja_store.get_credentials(uid)
                if creds and creds["api_token"]:
                    api_url = creds["api_url"] or self.config.vikunja_api_url
                    return TasksAction(api_url=api_url, api_token=creds["api_token"])
        return None

    # Known tool names for text-based tool call detection
    _TOOL_NAMES = frozenset(t["function"]["name"] for t in TOOLS)

    @staticmethod
    def _try_parse_text_tool_call(
        text: str,
        known_tools: frozenset[str] | None = None,
    ) -> dict | None:
        """Detect a tool call embedded as JSON in the LLM text response.

        Some local models (e.g. llama3.1 via Ollama) output tool calls as
        plain text instead of using the function-calling API.  This method
        tries to extract a valid tool call from the text.

        Returns {"name": str, "arguments": str} or None.
        """
        if known_tools is None:
            known_tools = NilesAgent._TOOL_NAMES

        # Strip markdown code fences if present
        cleaned = text.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        cleaned = cleaned.strip()

        # Must look like JSON
        if not cleaned.startswith("{"):
            return None

        try:
            obj = json.loads(cleaned)
        except json.JSONDecodeError:
            return None

        if not isinstance(obj, dict):
            return None

        # Format: {"name": "tool", "parameters": {...}}
        name = obj.get("name")
        if name and name in known_tools:
            params = obj.get("parameters") or obj.get("arguments") or {}
            return {"name": name, "arguments": json.dumps(params, ensure_ascii=False)}

        return None

    @staticmethod
    def _synthetic_tool_call(parsed: dict) -> tuple[dict, dict]:
        """Build a synthetic tool-call dict and assistant message from parsed text.

        Returns (tc_dict, assistant_message) where tc_dict has keys
        "id", "name", "arguments" and assistant_message is ready to append
        to the messages list.
        """
        tc = {
            "id": f"text_{parsed['name']}",
            "name": parsed["name"],
            "arguments": parsed["arguments"],
        }
        message = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {"name": tc["name"], "arguments": tc["arguments"]},
                }
            ],
        }
        return tc, message

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
            to=phone,
            text=pending["text"],
            instance=instance,
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
        messages.extend(
            {"role": m["role"], "content": m["content"]} for m in history_messages
        )
        messages.append({"role": "user", "content": event["content"]})

        all_tools = [t for t in TOOLS]
        # Remove task tools when Vikunja is not configured
        if not self.config.vikunja_api_url:
            _task_tools = {"list_tasks", "create_task", "complete_task"}
            all_tools = [
                t for t in all_tools if t["function"]["name"] not in _task_tools
            ]
        # Remove WhatsApp tools when no WhatsApp action is configured
        if not self.whatsapp:
            _wa_tools = {"send_whatsapp", "get_whatsapp_messages"}
            all_tools = [t for t in all_tools if t["function"]["name"] not in _wa_tools]
        # Remove Signal tools when no Signal action is configured
        if self.signal is None:
            _signal_tools = {"send_signal", "get_signal_messages"}
            all_tools = [
                t for t in all_tools if t["function"]["name"] not in _signal_tools
            ]
        if self.mcp:
            mcp_tools = self.mcp.get_openai_tools()
            all_tools.extend(mcp_tools)
            if mcp_tools and logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "MCP tools added: %s",
                    [t["function"]["name"] for t in mcp_tools],
                )
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
                _llm_start = time.monotonic()
                stream = await self.llm.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=all_tools,
                    temperature=0.7,
                    stream=True,
                    stream_options={"include_usage": True},
                )
            except Exception as e:
                LLM_DURATION.observe(time.monotonic() - _llm_start)
                logger.error("LLM call failed: %s", e)
                yield {
                    "type": "chunk",
                    "text": "Entschuldigung, ich konnte die Anfrage nicht verarbeiten.",
                }
                yield {"type": "done"}
                return

            # Consume the stream, accumulating text content and tool-call deltas
            full_content = ""
            tool_calls_by_idx: dict[int, dict] = {}
            finish_reason = None
            # Buffer responses that look like JSON tool calls instead of
            # streaming them — avoids showing raw JSON to the user.
            _buffering = False

            try:
                async for chunk in stream:
                    # Final chunk with usage data has empty choices
                    if not chunk.choices:
                        if chunk.usage:
                            LLM_TOKENS.labels(type="prompt").inc(
                                chunk.usage.prompt_tokens
                            )
                            LLM_TOKENS.labels(type="completion").inc(
                                chunk.usage.completion_tokens
                            )
                        continue
                    choice = chunk.choices[0]
                    finish_reason = choice.finish_reason or finish_reason

                    if choice.delta.content:
                        full_content += choice.delta.content
                        # If the first content looks like JSON or a code-fenced
                        # tool call, buffer it.  Single backticks (inline code)
                        # are NOT buffered — only triple-backtick fences or
                        # bare '{'.
                        stripped = full_content.lstrip()
                        if not _buffering and (
                            stripped.startswith("{") or stripped.startswith("```")
                        ):
                            _buffering = True
                        if not _buffering:
                            yield {"type": "chunk", "text": choice.delta.content}

                    if choice.delta.tool_calls:
                        for tc_delta in choice.delta.tool_calls:
                            idx = tc_delta.index
                            if idx not in tool_calls_by_idx:
                                tool_calls_by_idx[idx] = {
                                    "id": "",
                                    "name": "",
                                    "arguments": "",
                                }
                            if tc_delta.id:
                                tool_calls_by_idx[idx]["id"] = tc_delta.id
                            if tc_delta.function:
                                if tc_delta.function.name:
                                    tool_calls_by_idx[idx]["name"] += (
                                        tc_delta.function.name
                                    )
                                if tc_delta.function.arguments:
                                    tool_calls_by_idx[idx]["arguments"] += (
                                        tc_delta.function.arguments
                                    )
            finally:
                LLM_DURATION.observe(time.monotonic() - _llm_start)

            # No tool calls → check for text-based tool call fallback
            if finish_reason != "tool_calls" or not tool_calls_by_idx:
                parsed = (
                    self._try_parse_text_tool_call(full_content)
                    if full_content
                    else None
                )
                if parsed:
                    logger.info(
                        "Detected text-based tool call (stream): %s", parsed["name"]
                    )
                    tc_dict, _ = self._synthetic_tool_call(parsed)
                    tool_calls_by_idx = {0: tc_dict}
                    full_content = ""  # Don't pass JSON as assistant content
                    # Don't save or return — fall through to tool execution below
                else:
                    # Flush buffered content that turned out not to be a tool call
                    if _buffering and full_content:
                        yield {"type": "chunk", "text": full_content}
                    if full_content:
                        await self.history.add_message(
                            chat_id, "user", event["content"]
                        )
                        await self.history.add_message(
                            chat_id, "assistant", full_content
                        )
                    else:
                        logger.warning(
                            "LLM returned empty streaming response for event: %s",
                            event.get("content", "")[:100],
                        )
                        yield {
                            "type": "chunk",
                            "text": "Entschuldigung, ich habe keine Antwort erhalten.",
                        }
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
                _success = (
                    result.get("error") is None if isinstance(result, dict) else True
                )
                TOOL_CALLS.labels(
                    tool_name=tc_dict["function"]["name"],
                    success=str(_success).lower(),
                ).inc()
                logger.info("Tool result [%s]: %s", tool_call.id, result)

                # choose_phone → bypass LLM, send list directly to user
                if isinstance(result, dict) and "choose_phone" in result:
                    text = result["choose_phone"]
                    await self.history.add_message(chat_id, "user", event["content"])
                    await self.history.add_message(chat_id, "assistant", text)
                    yield {"type": "chunk", "text": text}
                    yield {"type": "done"}
                    return

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
        else:
            yield {
                "type": "chunk",
                "text": "Ich konnte die Anfrage nicht abschliessen.",
            }

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
                _llm_start = time.monotonic()
                response = await self.llm.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=all_tools,
                    temperature=0.7,
                )
                LLM_DURATION.observe(time.monotonic() - _llm_start)
            except Exception as e:
                LLM_DURATION.observe(time.monotonic() - _llm_start)
                logger.error("LLM call failed: %s", e)
                return "Entschuldigung, ich konnte die Anfrage nicht verarbeiten."

            choice = response.choices[0]

            # Record token usage if available
            if response.usage:
                LLM_TOKENS.labels(type="prompt").inc(response.usage.prompt_tokens)
                LLM_TOKENS.labels(type="completion").inc(
                    response.usage.completion_tokens
                )

            # No tool calls – check for text-based tool call fallback
            if choice.finish_reason != "tool_calls" or not choice.message.tool_calls:
                content = choice.message.content or ""
                parsed = self._try_parse_text_tool_call(content) if content else None
                if parsed:
                    logger.info("Detected text-based tool call: %s", parsed["name"])
                    tc_dict, assistant_msg = self._synthetic_tool_call(parsed)
                    messages.append(assistant_msg)
                    tc = SimpleNamespace(
                        id=tc_dict["id"],
                        function=SimpleNamespace(
                            name=tc_dict["name"],
                            arguments=tc_dict["arguments"],
                        ),
                    )
                    result = await self._execute_tool_call(tc, chat_id)
                    logger.info("Tool result [%s]: %s", tc.id, result)
                    if isinstance(result, dict) and "choose_phone" in result:
                        text = result["choose_phone"]
                        await self.history.add_message(
                            chat_id, "user", event["content"]
                        )
                        await self.history.add_message(chat_id, "assistant", text)
                        return text
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": json.dumps(result, ensure_ascii=False),
                        }
                    )
                    continue  # Next LLM round to generate natural language response

                if not content:
                    logger.warning(
                        "LLM returned empty response for event: %s",
                        event.get("content", "")[:100],
                    )
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
                _success = (
                    result.get("error") is None if isinstance(result, dict) else True
                )
                TOOL_CALLS.labels(
                    tool_name=tool_call.function.name,
                    success=str(_success).lower(),
                ).inc()
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
            TOOL_CALLS.labels(tool_name=name, success="false").inc()
            return {"error": "Invalid arguments"}

        logger.info("Tool call [%s]: %s(%s)", tool_call.id, name, args)

        if name == "find_contact":
            contact = await self.contacts.find_by_name(args["name"])
            if contact:
                return contact
            return {"error": f"Kontakt '{args['name']}' nicht gefunden"}

        if name == "send_whatsapp":
            to = args["to"]
            text = args["text"]
            resolved_number = None

            # 1. Contact resolution (if name instead of number)
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
                resolved_number = contact["phone"]
            else:
                resolved_number = to

            # 2. Self-check: own number is always allowed
            is_self = False
            own_number = await self._get_own_phone_number(chat_id)
            if own_number:
                normalized = resolved_number.replace("+", "").replace(" ", "")
                is_self = normalized == own_number or (
                    len(own_number) >= 8 and normalized.endswith(own_number)
                )

            # 3. Sending to others: only if feature flag is active
            if not is_self and not self.config.feature_whatsapp_send_others:
                logger.info("send_whatsapp to others disabled via feature flag")
                return {
                    "error": "Das Senden an andere Personen ist deaktiviert. "
                    "Du kannst diese Funktion in den Einstellungen aktivieren."
                }

            # 4. Send message
            instance = await self._resolve_wa_instance(chat_id)

            result = await self.whatsapp.send_message(
                to=resolved_number,
                text=text,
                instance=instance,
            )
            return (
                {"status": "sent", "to": resolved_number}
                if "error" not in result
                else result
            )

        if name == "get_whatsapp_messages":
            contact_arg = args.get("contact", "").strip()
            if not contact_arg:
                return {"error": "Bitte Kontaktname oder Telefonnummer angeben"}

            phone, err = await self._resolve_contact_phone(contact_arg)
            if err:
                return err

            # Build JID and resolve per-user instance
            jid = f"{phone}@s.whatsapp.net"
            instance = await self._resolve_wa_instance(chat_id)

            messages = await self.whatsapp.fetch_messages(
                remote_jid=jid,
                instance=instance,
            )
            if not messages:
                return {
                    "error": "Keine WhatsApp-Nachrichten gefunden",
                    "hint": "Es werden nur Nachrichten der letzten 30 Tage angezeigt.",
                }

            # Format as readable chat transcript for the LLM
            contact_name = (
                contact_arg
                if not contact_arg.replace("+", "").replace(" ", "").isdigit()
                else (messages[0].get("push_name") or phone)
            )
            local_tz = ZoneInfo(self.config.timezone)
            lines = []
            for msg in messages:
                ts = datetime.fromtimestamp(
                    msg["timestamp"], tz=timezone.utc
                ).astimezone(local_tz)
                who = "Du" if msg["from_me"] else contact_name
                lines.append(f"[{ts:%d.%m. %H:%M}] {who}: {msg['text']}")
            transcript = "\n".join(lines)

            # Compute date range for LLM context (in user's local timezone)
            # See also: config/soul.md "Nachrichten lesen" + hinweis below
            first_dt = datetime.fromtimestamp(
                messages[0]["timestamp"],
                tz=timezone.utc,
            ).astimezone(local_tz)
            last_dt = datetime.fromtimestamp(
                messages[-1]["timestamp"],
                tz=timezone.utc,
            ).astimezone(local_tz)
            if first_dt.date() == last_dt.date():
                date_range = first_dt.strftime("%d.%m.%Y")
            else:
                date_range = (
                    f"{first_dt.strftime('%d.%m.%Y')}"
                    f" \u2013 "
                    f"{last_dt.strftime('%d.%m.%Y')}"
                )

            return {
                "chat_with": contact_name,
                "count": len(messages),
                "date_range": date_range,
                # Summarization instruction (3/3) — keep in sync with:
                # 1/3: config/soul.md "Nachrichten lesen"
                # 2/3: tool description above
                "hinweis": (
                    f"{len(messages)} Nachrichten ({date_range}). "
                    "Fasse die wichtigsten Punkte zusammen: "
                    "Termine, Abmachungen, offene Fragen, wichtige Infos. "
                    "Gib NICHT das rohe Transcript wieder."
                ),
                "transcript": transcript,
            }

        if name == "send_signal":
            to = args["to"]
            text = args["text"]

            # 1. Contact resolution (if name instead of number)
            phone, err = await self._resolve_contact_phone(to)
            if err:
                return err
            resolved_number = f"+{phone}"

            # 2. Self-check: own number is always allowed
            own_phone = self.config.signal_phone_number
            is_self = resolved_number == own_phone

            # 3. Sending to others: only if feature flag is active
            if not is_self and not self.config.feature_signal_send_others:
                logger.info("send_signal to others disabled via feature flag")
                return {
                    "error": "Das Senden an andere Personen ist deaktiviert. "
                    "Du kannst diese Funktion in den Einstellungen aktivieren."
                }

            # 4. Send message
            result = await self.signal.send_message(to=resolved_number, text=text)
            return (
                {"status": "sent", "to": resolved_number}
                if "error" not in result
                else result
            )

        if name == "get_signal_messages":
            contact_arg = args.get("contact", "").strip()
            if not contact_arg:
                return {"error": "Bitte Kontaktname oder Telefonnummer angeben"}

            phone, err = await self._resolve_contact_phone(contact_arg)
            if err:
                return err
            phone = f"+{phone}"

            messages = await self.signal_store.get_messages(phone=phone)
            if not messages:
                return {
                    "error": "Keine Signal-Nachrichten gefunden",
                    "hint": "Es werden nur Nachrichten der letzten 30 Tage angezeigt.",
                }

            # Format as readable chat transcript for the LLM
            contact_name = (
                contact_arg
                if not contact_arg.replace("+", "").replace(" ", "").isdigit()
                else phone
            )
            local_tz = ZoneInfo(self.config.timezone)
            lines = []
            for msg in messages:
                ts = datetime.fromtimestamp(
                    msg["timestamp"], tz=timezone.utc
                ).astimezone(local_tz)
                who = "Du" if msg["from_me"] else contact_name
                lines.append(f"[{ts:%d.%m. %H:%M}] {who}: {msg['text']}")
            transcript = "\n".join(lines)

            first_dt = datetime.fromtimestamp(
                messages[0]["timestamp"], tz=timezone.utc
            ).astimezone(local_tz)
            last_dt = datetime.fromtimestamp(
                messages[-1]["timestamp"], tz=timezone.utc
            ).astimezone(local_tz)
            if first_dt.date() == last_dt.date():
                date_range = first_dt.strftime("%d.%m.%Y")
            else:
                date_range = (
                    f"{first_dt.strftime('%d.%m.%Y')}"
                    f" \u2013 "
                    f"{last_dt.strftime('%d.%m.%Y')}"
                )

            return {
                "chat_with": contact_name,
                "count": len(messages),
                "date_range": date_range,
                "hinweis": (
                    f"{len(messages)} Nachrichten ({date_range}). "
                    "Fasse die wichtigsten Punkte zusammen: "
                    "Termine, Abmachungen, offene Fragen, wichtige Infos. "
                    "Gib NICHT das rohe Transcript wieder."
                ),
                "transcript": transcript,
            }

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
            # Guard: small LLMs often confuse the user's name with a calendar
            # source name and pass it as filter on general date queries.
            # Only honour the calendar filter when a search term is present
            # (e.g. birthday lookups).
            # Known limitation: explicit calendar-only queries like "was steht
            # in meinem Arbeits-Kalender an?" (calendar set, query empty) will
            # also have their filter dropped.  Acceptable trade-off — the
            # small LLM misuse case is far more common.
            cal_filter = args.get("calendar", "")
            if cal_filter and not args.get("query"):
                logger.debug(
                    "Dropping calendar filter '%s' on general date query",
                    cal_filter,
                )
                cal_filter = ""
            events = await self.calendar.find_by_query(
                query=args.get("query", ""),
                date_from=args.get("date_from", ""),
                date_to=args.get("date_to", ""),
                calendar=cal_filter,
            )
            if events:
                result: dict = {"events": events, "count": len(events)}
                result["hinweis"] = (
                    "Nenne NUR diese Termine. Erfinde keine zusätzlichen Termine."
                )
                return result
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

        if name == "list_tasks":
            tasks_action = await self._resolve_vikunja_tasks(chat_id)
            if not tasks_action:
                return {
                    "error": "Aufgaben nicht konfiguriert. Bitte Vikunja-Token in den Einstellungen hinterlegen."
                }
            tasks = await tasks_action.list_tasks(
                project=args.get("project", ""),
                include_done=args.get("include_done", False),
            )
            if tasks:
                return {"tasks": tasks, "count": len(tasks)}
            return {"error": "Keine Aufgaben gefunden"}

        if name == "create_task":
            tasks_action = await self._resolve_vikunja_tasks(chat_id)
            if not tasks_action:
                return {
                    "error": "Aufgaben nicht konfiguriert. Bitte Vikunja-Token in den Einstellungen hinterlegen."
                }
            return await tasks_action.create_task(
                title=args["title"],
                description=args.get("description", ""),
                due_date=args.get("due_date", ""),
                priority=args.get("priority", 0),
                project=args.get("project", ""),
            )

        if name == "complete_task":
            tasks_action = await self._resolve_vikunja_tasks(chat_id)
            if not tasks_action:
                return {
                    "error": "Aufgaben nicht konfiguriert. Bitte Vikunja-Token in den Einstellungen hinterlegen."
                }
            return await tasks_action.complete_task(title=args["title"])

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
