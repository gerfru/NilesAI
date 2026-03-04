"""Context building and resolution helpers for NilesAgent.

Extracts context assembly (system prompt, memory, calendar sources)
and per-user resource resolution from the main orchestration loop.
"""

import logging
import time
from typing import TYPE_CHECKING

from ..actions.contacts import normalize_phone
from ..actions.tasks import TasksAction
from ..config import Settings
from ..memory.store import MemoryStore
from ..memory.history import ConversationHistory
from .prompts import build_system_prompt

if TYPE_CHECKING:
    import httpx

    from ..actions.calendar import CalendarAction
    from ..actions.contacts import ContactsAction
    from ..actions.signal import SignalAction
    from ..actions.whatsapp import WhatsAppAction
    from ..mcp.client import MCPManager
    from ..signal_store import SignalMessageStore
    from ..sync.manager import CalendarSourceManager
    from ..vikunja_store import VikunjaCredentialStore
    from ..whatsapp_store import WhatsAppSessionStore

logger = logging.getLogger(__name__)


class ContextBuilder:
    """Builds message context and resolves per-user resources.

    Extracted from NilesAgent to separate context assembly from
    the LLM orchestration loop.
    """

    _SOURCE_CACHE_TTL = 300  # 5 minutes

    def __init__(
        self,
        config: Settings,
        contacts: "ContactsAction",
        whatsapp: "WhatsAppAction",
        memory: MemoryStore,
        history: ConversationHistory,
        base_prompt: str,
        mcp: "MCPManager | None" = None,
        calendar: "CalendarAction | None" = None,
        calendar_manager: "CalendarSourceManager | None" = None,
        wa_store: "WhatsAppSessionStore | None" = None,
        vikunja_store: "VikunjaCredentialStore | None" = None,
        signal: "SignalAction | None" = None,
        signal_store: "SignalMessageStore | None" = None,
        http_client: "httpx.AsyncClient | None" = None,
    ):
        self.config = config
        self.contacts = contacts
        self.whatsapp = whatsapp
        self.memory = memory
        self.history = history
        self.base_prompt = base_prompt
        self.mcp = mcp
        self.calendar = calendar
        self.calendar_manager = calendar_manager
        self.wa_store = wa_store
        self.vikunja_store = vikunja_store
        self.signal = signal
        self.signal_store = signal_store
        self._http_client = http_client
        self.notion_retriever: object | None = None

        # Cached calendar source names (refreshed every 5 minutes)
        self._source_names_cache: list[str] = []
        self._source_names_ts: float = 0.0
        # Pending phone choice: chat_id → {phones, text, contact_name, expires_at}
        self._pending_phone_choices: dict[str, dict] = {}

    async def resolve_user_id(self, chat_id: str) -> int | None:
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

    async def resolve_wa_instance(self, chat_id: str) -> str | None:
        """Look up per-user WhatsApp instance from chat_id."""
        uid = await self.resolve_user_id(chat_id)
        if uid is not None and self.wa_store:
            session = await self.wa_store.get_session(uid)
            if session and session["status"] == "connected":
                return session["instance_name"]
        return None

    async def resolve_contact_phone(
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

    async def get_own_phone_number(self, chat_id: str) -> str | None:
        """Get the user's own WhatsApp phone number from their session.

        For self-chat (wa-self-{phone}), extracts the phone directly.
        For web users (web-user-{uid}), looks up from wa_store.
        """
        if chat_id.startswith("wa-self-"):
            return chat_id.split("-", 2)[2]
        uid = await self.resolve_user_id(chat_id)
        if uid is not None and self.wa_store:
            session = await self.wa_store.get_session(uid)
            if session and session.get("phone_number"):
                return session["phone_number"].replace("+", "").replace(" ", "")
        return None

    async def resolve_vikunja_tasks(self, chat_id: str) -> TasksAction | None:
        """Resolve per-user Vikunja credentials."""
        if self.vikunja_store:
            uid = await self.resolve_user_id(chat_id)
            if uid is not None:
                creds = await self.vikunja_store.get_credentials(uid)
                if creds and creds["api_token"]:
                    api_url = creds["api_url"] or self.config.vikunja_api_url
                    if api_url:
                        return TasksAction(
                            api_url=api_url,
                            api_token=creds["api_token"],
                            client=self._http_client,
                        )
        return None

    async def get_calendar_source_names(self) -> list[str]:
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

    async def handle_phone_choice(self, chat_id: str, content: str) -> str | None:
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
        pending = self._pending_phone_choices[chat_id]

        if choice_idx < 0 or choice_idx >= len(pending["phones"]):
            count = len(pending["phones"])
            return f"Ungültige Auswahl. Bitte wähle 1 bis {count}."

        self._pending_phone_choices.pop(chat_id)  # valid choice — remove state
        phone = pending["phones"][choice_idx]["number"]
        instance = await self.resolve_wa_instance(chat_id)

        result = await self.whatsapp.send_message(
            to=phone,
            text=pending["text"],
            instance=instance,
        )
        if "error" not in result:
            return f"Nachricht an {pending['contact_name']} (00{phone}) gesendet."
        return f"Fehler beim Senden: {result['error']}"

    async def prepare_messages(
        self, event: dict, tools: list
    ) -> tuple[str, list[dict], list]:
        """Build the messages list for an LLM call.

        Returns (chat_id, messages, filtered_tools).
        """
        chat_id = event["from"]

        memories = await self.memory.list_all()
        source_names = await self.get_calendar_source_names()

        system_prompt = build_system_prompt(
            self.base_prompt,
            memories,
            timezone=self.config.timezone,
            calendar_sources=source_names,
        )

        # Append recherche-mode instruction only when MCP search tools exist
        web_search = event.get("metadata", {}).get("web_search", False)
        _has_search_mcp = self.mcp and any(
            t["function"]["name"].startswith("mcp__searxng__")
            for t in self.mcp.get_openai_tools()
        )
        if _has_search_mcp:
            if web_search:
                system_prompt += (
                    "\n\n## Recherche-Modus AKTIV\n"
                    "Der Benutzer hat den Recherche-Modus aktiviert. "
                    "Priorisiere die Web-Suche (`mcp__searxng__search`) und "
                    "Fetch-Tools (`mcp__fetch__fetch_url`) um die Anfrage "
                    "zu beantworten. Lokale Tools (find_contact, find_event, "
                    "list_tasks) nur verwenden, wenn die Anfrage eindeutig "
                    "lokale Daten betrifft."
                )
            else:
                system_prompt += (
                    "\n\n## Recherche-Modus NICHT aktiv\n"
                    "Nutze lokale Tools: find_contact, find_event, "
                    "list_tasks, send_whatsapp, remember, recall, "
                    "Wetter-Tools etc. Führe keine Web-Suche durch — die "
                    "Such-Tools stehen nicht zur Verfügung."
                )

        # Append Notion context instruction when toggle is active
        notion_search = event.get("metadata", {}).get("notion_search", False)
        if notion_search:
            system_prompt += (
                "\n\n## Notion-Kontext AKTIV\n"
                "Der Benutzer hat die Notion-Suche aktiviert. Relevante Inhalte "
                "aus dem Notion-Wissensspeicher wurden bereits in die Nachricht "
                "eingefuegt (markiert mit [Notion-Kontext]). Beantworte die "
                "Frage ausschliesslich auf Basis dieses Kontexts. Rufe KEINE "
                "anderen Tools auf (kein list_tasks, find_event etc.), es sei "
                "denn die Frage betrifft eindeutig etwas anderes."
            )

        history_messages = await self.history.get_recent(chat_id)
        messages: list[dict] = [{"role": "system", "content": system_prompt}]
        messages.extend(
            {"role": m["role"], "content": m["content"]} for m in history_messages
        )
        messages.append({"role": "user", "content": event["content"]})

        all_tools = list(tools)
        # Remove task tools when Vikunja is not configured
        if not self.config.vikunja_api_url:
            _task_tools = {"list_tasks", "create_task", "complete_task"}
            all_tools = [
                t for t in all_tools if t["function"]["name"] not in _task_tools
            ]
        # Remove Signal tools when no Signal action is configured
        if self.signal is None:
            _signal_tools = {"send_signal", "get_signal_messages"}
            all_tools = [
                t for t in all_tools if t["function"]["name"] not in _signal_tools
            ]
        # Remove Notion tool when disabled or retriever not available
        if not self.config.feature_notion or not getattr(
            self, "notion_retriever", None
        ):
            all_tools = [
                t for t in all_tools if t["function"]["name"] != "search_notion"
            ]

        # When Notion toggle is active, context is already injected into the
        # user message.  Remove ALL tools so the small local model answers
        # exclusively from the provided context instead of calling tools.
        if notion_search:
            all_tools = []

        if self.mcp and not notion_search:
            mcp_tools = self.mcp.get_openai_tools()
            # Only include search/fetch MCP tools when web_search is active
            if not web_search:
                _search_prefixes = ("mcp__searxng__", "mcp__fetch__")
                mcp_tools = [
                    t
                    for t in mcp_tools
                    if not t["function"]["name"].startswith(_search_prefixes)
                ]
            all_tools.extend(mcp_tools)
            if mcp_tools and logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "MCP tools added: %s",
                    [t["function"]["name"] for t in mcp_tools],
                )
        return chat_id, messages, all_tools

    # Backward-compatible aliases — tests and older code use underscore-prefixed names.
    _resolve_user_id = resolve_user_id
    _resolve_wa_instance = resolve_wa_instance
    _resolve_contact_phone = resolve_contact_phone
    _get_own_phone_number = get_own_phone_number
    _resolve_vikunja_tasks = resolve_vikunja_tasks
    _get_calendar_source_names = get_calendar_source_names
