"""Niles agent core – event processing with LLM tool-call loop."""

import json
import logging

import httpx
from openai import AsyncOpenAI

from ..actions.calendar import CalendarAction
from ..actions.contacts import ContactsAction
from ..actions.whatsapp import WhatsAppAction
from ..config import Settings
from ..mcp.client import MCPManager
from ..sync.caldav import CalDAVSync
from ..memory.history import ConversationHistory
from ..memory.store import MemoryStore
from .prompts import build_system_prompt, load_system_prompt

logger = logging.getLogger(__name__)

# Tool definitions in OpenAI function-calling format
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "find_contact",
            "description": "Sucht einen Kontakt nach Name und gibt Telefonnummer und Email zurück.",
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
            "description": "Sucht Kalendertermine nach Stichwort und/oder Zeitraum.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Suchbegriff (Name, Ort, Beschreibung). Leer lassen fuer reine Datumssuche.",
                    },
                    "date_from": {
                        "type": "string",
                        "description": "Startdatum (ISO-Format, z.B. '2026-02-20' oder '2026-02-20T14:00'). Optional.",
                    },
                    "date_to": {
                        "type": "string",
                        "description": "Enddatum (ISO-Format). Optional.",
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
            "description": "Erstellt einen neuen Kalendertermin.",
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
        caldav_sync: CalDAVSync | None = None,
    ):
        self.config = config
        self.llm = AsyncOpenAI(
            base_url=config.llm_base_url,
            api_key="not-needed",  # LM Studio doesn't require a key
        )
        self.model = config.llm_model
        self.contacts = contacts
        self.whatsapp = whatsapp
        self.memory = memory
        self.history = history
        self.mcp = mcp_manager
        self.calendar = calendar
        self.caldav_sync = caldav_sync
        self.base_prompt = load_system_prompt()

    async def process_event(self, event: dict) -> str:
        """
        Main entry point for all events.

        Args:
            event: {"type": str, "from": str, "content": str, "metadata": dict}

        Returns:
            Response text
        """
        chat_id = event["from"]

        # Load memory context for system prompt
        memories = await self.memory.list_all()
        system_prompt = build_system_prompt(
            self.base_prompt, memories, timezone=self.config.timezone,
        )

        # Load conversation history
        history_messages = await self.history.get_recent(chat_id)

        # Build message list: system + history + current message
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history_messages)
        messages.append({"role": "user", "content": event["content"]})

        # Save user message to history
        await self.history.add_message(chat_id, "user", event["content"])

        # Combine built-in tools with MCP tools
        all_tools = TOOLS + (self.mcp.get_openai_tools() if self.mcp else [])

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
                # Save assistant response to history
                if content:
                    await self.history.add_message(chat_id, "assistant", content)
                return content

            # Append assistant message with tool calls (serialize to dict)
            messages.append(choice.message.model_dump(exclude_unset=True))

            # Execute each tool call and append results
            for tool_call in choice.message.tool_calls:
                result = await self._execute_tool_call(tool_call)
                logger.info("Tool result [%s]: %s", tool_call.id, result)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )

        logger.warning("Max tool rounds reached")
        return "Ich konnte die Anfrage nicht abschließen."

    async def _execute_tool_call(self, tool_call) -> dict:
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
                if contact and contact.get("phone"):
                    to = contact["phone"]
                else:
                    return {"error": f"Kontakt '{args['to']}' nicht gefunden oder keine Telefonnummer vorhanden"}

            result = await self.whatsapp.send_message(to=to, text=text)
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
            )
            if events:
                return {"events": events, "count": len(events)}
            return {"error": "Keine Termine gefunden"}

        if name == "create_event":
            if not self.caldav_sync:
                return {"error": "Kalender ist nicht konfiguriert"}
            if not self.config.feature_caldav_sync:
                return {"error": "Kalender-Sync ist deaktiviert"}
            try:
                return await self.caldav_sync.create_event(
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
