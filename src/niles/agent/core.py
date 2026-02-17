"""Niles agent core – event processing with LLM tool-call loop."""

import json
import logging

from openai import AsyncOpenAI

from ..actions.contacts import ContactsAction
from ..actions.whatsapp import WhatsAppAction
from ..config import Settings
from .prompts import load_system_prompt

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
]

MAX_TOOL_ROUNDS = 5


class NilesAgent:
    """
    Event processing pipeline:
    1. Receive event
    2. Build messages (system prompt + user message)
    3. Call LLM with tools
    4. Execute tool calls if any
    5. Feed results back to LLM
    6. Return final response
    """

    def __init__(
        self,
        config: Settings,
        contacts: ContactsAction,
        whatsapp: WhatsAppAction,
    ):
        self.llm = AsyncOpenAI(
            base_url=config.llm_base_url,
            api_key="not-needed",  # LM Studio doesn't require a key
        )
        self.model = config.llm_model
        self.contacts = contacts
        self.whatsapp = whatsapp
        self.system_prompt = load_system_prompt()

    async def process_event(self, event: dict) -> str:
        """
        Main entry point for all events.

        Args:
            event: {"type": str, "from": str, "content": str, "metadata": dict}

        Returns:
            Response text
        """
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": event["content"]},
        ]

        # Tool-call loop: LLM may request multiple rounds of tool calls
        for _ in range(MAX_TOOL_ROUNDS):
            try:
                response = await self.llm.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=TOOLS,
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

        return {"error": f"Unknown tool: {name}"}
