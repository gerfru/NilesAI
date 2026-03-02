"""Tool handler registry for NilesAgent.

Each handler module registers its functions via @register_tool.
Importing this package auto-registers all handlers (side-effect
imports at the bottom of this file).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from ...actions.calendar import CalendarAction
from ...actions.contacts import ContactsAction
from ...actions.signal import SignalAction
from ...actions.whatsapp import WhatsAppAction
from ...config import Settings
from ...mcp.client import MCPManager
from ...memory.store import MemoryStore
from ...signal_store import SignalMessageStore
from ...sync.manager import CalendarSourceManager
from ...vikunja_store import VikunjaCredentialStore
from ...whatsapp_store import WhatsAppSessionStore

logger = logging.getLogger(__name__)


@dataclass
class ToolContext:
    """Everything a tool handler needs — built by NilesAgent per call."""

    config: Settings
    contacts: ContactsAction
    whatsapp: WhatsAppAction
    signal: SignalAction | None
    signal_store: SignalMessageStore | None
    memory: MemoryStore
    calendar: CalendarAction | None
    calendar_manager: CalendarSourceManager | None
    vikunja_store: VikunjaCredentialStore | None
    wa_store: WhatsAppSessionStore | None
    mcp: MCPManager | None
    # Helper callables from NilesAgent:
    resolve_contact_phone: Callable[..., Awaitable[tuple[str | None, dict | None]]]
    resolve_wa_instance: Callable[..., Awaitable[str | None]]
    resolve_vikunja: Callable[..., Awaitable[Any]]
    get_own_phone_number: Callable[..., Awaitable[str | None]]
    pending_phone_choices: dict[str, dict]


ToolHandler = Callable[[dict, str, ToolContext], Awaitable[dict]]

TOOL_REGISTRY: dict[str, ToolHandler] = {}


def register_tool(name: str) -> Callable[[ToolHandler], ToolHandler]:
    """Decorator: register an async handler for a named tool."""

    def decorator(func: ToolHandler) -> ToolHandler:
        TOOL_REGISTRY[name] = func
        return func

    return decorator


# Auto-register all handler modules on package import.
from . import calendar, contacts, memory, signal, tasks, whatsapp  # noqa: E402, F401
