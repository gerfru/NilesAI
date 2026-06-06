"""Niles agent core – event processing with LLM tool-call loop."""

import json
import logging
import time
from types import SimpleNamespace

import httpx
from openai import AsyncOpenAI

from ..actions.calendar import CalendarAction
from ..actions.contacts import ContactsAction
from ..actions.signal import SignalAction
from ..actions.whatsapp import WhatsAppAction
from ..config import Settings
from ..mcp.client import MCPManager
from ..mcp.user_pool import UserMCPPool
from ..memory.history import ConversationHistory
from ..memory.store import MemoryStore
from ..metrics import LLM_DURATION, LLM_TOKENS, TOOL_CALLS
from ..signal_store import SignalMessageStore
from ..sync.manager import CalendarSourceManager
from ..vikunja_store import VikunjaCredentialStore
from ..whatsapp_store import WhatsAppSessionStore
from .context import ContextBuilder
from .prompts import load_system_prompt
from .text_tool_parser import (
    is_rejected_tool_call,
    synthetic_tool_call,
    try_parse_text_tool_call,
)
from .tools import TOOL_REGISTRY, ToolContext
from .tools.mcp import handle_mcp_tool

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
                        "description": "Telefonnummer (z.B. '+436601234567') oder Kontaktname",
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
    {
        "type": "function",
        "function": {
            "name": "search_notion",
            "description": (
                "Durchsucht die Notion-Wissensdatenbank nach relevanten Inhalten. "
                "Nutze dieses Tool wenn der Benutzer nach Informationen fragt, "
                "die in seinen Notion-Seiten stehen koennten (Dokumentation, "
                "Notizen, Projekte, Wikis)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Suchanfrage in natuerlicher Sprache",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximale Anzahl Ergebnisse (1-10, Standard: 5)",
                    },
                },
                "required": ["query"],
            },
        },
    },
]

MAX_TOOL_ROUNDS = 5


class NilesAgent:
    """Thin orchestrator: LLM call loop + streaming pipeline.

    Context assembly is delegated to ``ContextBuilder`` (context.py).
    Text tool-call parsing is delegated to ``text_tool_parser`` module.
    """

    # Backward-compatible static method wrapper for synthetic tool calls.
    _synthetic_tool_call = staticmethod(synthetic_tool_call)

    @staticmethod
    def _try_parse_text_tool_call(
        text: str,
        known_tools: frozenset[str] | None = None,
    ) -> dict | None:
        """Detect a tool call embedded as JSON in the LLM text response.

        When *known_tools* is ``None``, defaults to the module-level TOOLS list.
        """
        if known_tools is None:
            known_tools = NilesAgent._TOOL_NAMES
        return try_parse_text_tool_call(text, known_tools)

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
        vikunja_store: VikunjaCredentialStore | None = None,
        signal: SignalAction | None = None,
        signal_store: SignalMessageStore | None = None,
        http_client: httpx.AsyncClient | None = None,
        user_mcp_pool: UserMCPPool | None = None,
    ):
        self.notion_retriever: object | None = None
        self.llm = AsyncOpenAI(
            base_url=config.llm_base_url,
            api_key="not-needed",
        )
        self.model = config.llm_model
        self._ctx = ContextBuilder(
            config=config,
            contacts=contacts,
            whatsapp=whatsapp,
            memory=memory,
            history=history,
            base_prompt=load_system_prompt(),
            mcp=mcp_manager,
            calendar=calendar,
            calendar_manager=calendar_manager,
            wa_store=wa_store,
            vikunja_store=vikunja_store,
            signal=signal,
            signal_store=signal_store,
            http_client=http_client,
            user_mcp_pool=user_mcp_pool,
        )

    def __getattr__(self, name: str):
        """Delegate attribute access to ContextBuilder for backward compat.

        Only called when normal attribute lookup fails, so ``self.llm``
        and ``self.model`` are resolved directly with zero overhead.
        """
        if name == "_ctx":
            raise AttributeError("_ctx not yet initialized")
        try:
            return getattr(self._ctx, name)
        except AttributeError:
            raise AttributeError(  # noqa: B904
                f"'{type(self).__name__}' has no attribute '{name}'"
            )

    _TOOL_NAMES = frozenset(t["function"]["name"] for t in TOOLS)

    async def _prepare_messages(self, event: dict) -> tuple[str, list[dict], list]:
        """Delegate to ContextBuilder.prepare_messages."""
        return await self._ctx.prepare_messages(event, TOOLS)

    async def _handle_phone_choice(self, chat_id: str, content: str) -> str | None:
        """Delegate to ContextBuilder.handle_phone_choice."""
        return await self._ctx.handle_phone_choice(chat_id, content)

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
        # Store original user message in history (without injected Notion context)
        _history_content = (
            event.get("metadata", {}).get("original_message") or event["content"]
        )

        # Intercept pending phone choice (bypass LLM entirely)
        reply = await self._handle_phone_choice(chat_id, event["content"])
        if reply is not None:
            await self.history.add_message(chat_id, "user", _history_content)
            await self.history.add_message(chat_id, "assistant", reply)
            yield {"type": "chunk", "text": reply}
            yield {"type": "done"}
            return

        # Intercept pending confirmation (bypass LLM entirely)
        reply = await self._ctx.handle_confirmation(chat_id, event["content"])
        if reply is not None:
            await self.history.add_message(chat_id, "user", _history_content)
            await self.history.add_message(chat_id, "assistant", reply)
            yield {"type": "chunk", "text": reply}
            yield {"type": "done"}
            return

        chat_id, messages, all_tools = await self._prepare_messages(event)
        _temperature = 0.3 if not all_tools else 0.7

        # Force search tool on first round when Recherche-Modus is active
        _web_search = event.get("metadata", {}).get("web_search", False)
        _search_tool = "mcp__searxng__web_search"
        _tool_names = [t["function"]["name"] for t in all_tools]
        _force_search = _web_search and _search_tool in _tool_names

        for _round in range(MAX_TOOL_ROUNDS):
            if _force_search and _round == 0:
                _tool_choice: object = {
                    "type": "function",
                    "function": {"name": _search_tool},
                }
            else:
                _tool_choice = "auto" if all_tools else None

            try:
                _llm_start = time.monotonic()
                stream = await self.llm.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=all_tools or None,
                    tool_choice=_tool_choice,
                    temperature=_temperature,
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
                _all_names = frozenset(t["function"]["name"] for t in all_tools)
                parsed = (
                    self._try_parse_text_tool_call(full_content, _all_names)
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
                        rejected_name = is_rejected_tool_call(full_content)
                        if rejected_name:
                            logger.info(
                                "Suppressed rejected tool call: %s",
                                rejected_name,
                            )
                            full_content = (
                                "Ich kann diese Anfrage mit den aktuell "
                                "verfügbaren Funktionen nicht beantworten. "
                                "Bitte aktiviere den Recherche-Modus."
                            )
                        yield {"type": "chunk", "text": full_content}
                    if full_content:
                        await self.history.add_message(
                            chat_id, "user", _history_content
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

                # confirm → bypass LLM, ask user for confirmation
                if isinstance(result, dict) and "confirm" in result:
                    text = result["confirm"]
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
        # Store original user message in history (without injected Notion context)
        _history_content = (
            event.get("metadata", {}).get("original_message") or event["content"]
        )

        # Intercept pending phone choice (bypass LLM entirely)
        reply = await self._handle_phone_choice(chat_id, event["content"])
        if reply is not None:
            await self.history.add_message(chat_id, "user", _history_content)
            await self.history.add_message(chat_id, "assistant", reply)
            return reply

        # Intercept pending confirmation (bypass LLM entirely)
        reply = await self._ctx.handle_confirmation(chat_id, event["content"])
        if reply is not None:
            await self.history.add_message(chat_id, "user", _history_content)
            await self.history.add_message(chat_id, "assistant", reply)
            return reply

        chat_id, messages, all_tools = await self._prepare_messages(event)
        _temperature = 0.3 if not all_tools else 0.7

        # Force search tool on first round when Recherche-Modus is active
        _web_search = event.get("metadata", {}).get("web_search", False)
        _search_tool = "mcp__searxng__web_search"
        _force_search = _web_search and any(
            t["function"]["name"] == _search_tool for t in all_tools
        )

        # Tool-call loop: LLM may request multiple rounds of tool calls
        for _round in range(MAX_TOOL_ROUNDS):
            if _force_search and _round == 0:
                _tool_choice: object = {
                    "type": "function",
                    "function": {"name": _search_tool},
                }
            else:
                _tool_choice = "auto" if all_tools else None

            try:
                _llm_start = time.monotonic()
                response = await self.llm.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=all_tools or None,
                    tool_choice=_tool_choice,
                    temperature=_temperature,
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
                _all_names = frozenset(t["function"]["name"] for t in all_tools)
                parsed = (
                    self._try_parse_text_tool_call(content, _all_names)
                    if content
                    else None
                )
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
                            chat_id, "user", _history_content
                        )
                        await self.history.add_message(chat_id, "assistant", text)
                        return text
                    if isinstance(result, dict) and "confirm" in result:
                        text = result["confirm"]
                        await self.history.add_message(
                            chat_id, "user", _history_content
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

                # Suppress raw JSON for unavailable tools
                if content:
                    rejected_name = is_rejected_tool_call(content)
                    if rejected_name:
                        logger.info(
                            "Suppressed rejected tool call: %s",
                            rejected_name,
                        )
                        content = (
                            "Ich kann diese Anfrage mit den aktuell "
                            "verfügbaren Funktionen nicht beantworten. "
                            "Bitte aktiviere den Recherche-Modus."
                        )

                if not content:
                    logger.warning(
                        "LLM returned empty response for event: %s",
                        event.get("content", "")[:100],
                    )
                # Save both messages together to avoid orphaned records
                if content:
                    await self.history.add_message(chat_id, "user", _history_content)
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

                # confirm → bypass LLM, ask user for confirmation
                if isinstance(result, dict) and "confirm" in result:
                    text = result["confirm"]
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

    def _tool_context(self, user_id: int | None = None) -> ToolContext:
        """Build a ToolContext from the agent's dependencies.

        Uses ``self.X`` (not ``self._ctx.X``) for data attributes so that
        tests can override them on the agent instance directly.
        """
        return ToolContext(
            config=self.config,
            contacts=self.contacts,
            whatsapp=self.whatsapp,
            signal=self.signal,
            signal_store=self.signal_store,
            memory=self.memory,
            calendar=self.calendar,
            calendar_manager=self.calendar_manager,
            vikunja_store=self.vikunja_store,
            wa_store=self.wa_store,
            mcp=self.mcp,
            user_mcp_pool=getattr(self._ctx, "user_mcp_pool", None),
            user_id=user_id,
            resolve_contact_phone=self._resolve_contact_phone,
            resolve_wa_instance=self._resolve_wa_instance,
            resolve_vikunja=self._resolve_vikunja_tasks,
            get_own_phone_number=self._get_own_phone_number,
            pending_phone_choices=self._pending_phone_choices,
            pending_confirmations=self._pending_confirmations,
            notion_retriever=getattr(self, "notion_retriever", None),
        )

    async def _execute_tool_call(self, tool_call, chat_id: str = "") -> dict:
        """Execute a single tool call and return the result."""
        name = tool_call.function.name
        try:
            args = json.loads(tool_call.function.arguments)
        except json.JSONDecodeError:
            TOOL_CALLS.labels(tool_name=name, success="false").inc()
            return {"error": "Invalid arguments"}

        logger.info("Tool call [%s]: %s(%s)", tool_call.id, name, args)

        # Resolve user_id for per-user MCP tool routing
        user_id = await self._ctx.resolve_user_id(chat_id) if chat_id else None
        ctx = self._tool_context(user_id=user_id)

        # Registry lookup for built-in tools
        handler = TOOL_REGISTRY.get(name)
        if handler:
            try:
                return await handler(args, chat_id, ctx)
            except KeyError as exc:
                logger.warning("Missing required argument in %s: %s", name, exc)
                return {"error": f"Missing required argument: {exc}"}

        # MCP fallback for tools not in the registry
        return await handle_mcp_tool(name, args, ctx)
