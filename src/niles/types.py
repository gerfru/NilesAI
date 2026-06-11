"""Shared type definitions for Niles Core.

Provides TypedDicts for store return types and a typed Protocol for app.state
so mypy can verify attribute access without runtime overhead.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Protocol, TypedDict

if TYPE_CHECKING:
    import asyncpg

    from niles.actions.admin import AdminAction
    from niles.actions.briefing import BriefingGenerator
    from niles.actions.contacts import ContactsAction
    from niles.actions.settings import SettingsAction
    from niles.actions.signal import SignalAction
    from niles.actions.signal_setup import SignalSetupAction
    from niles.actions.vikunja_setup import VikunjaSetupAction
    from niles.actions.weather import WeatherAction
    from niles.actions.whatsapp import WhatsAppAction
    from niles.actions.whatsapp_setup import WhatsAppSetupAction
    from niles.agent.core import NilesAgent
    from niles.config import Settings
    from niles.http_clients import HttpClients
    from niles.memory.history import ConversationHistory
    from niles.notion_store import NotionStore
    from niles.settings_store import SettingsStore
    from niles.signal_store import SignalMessageStore
    from niles.sync.caldav import CalDAVSync
    from niles.sync.carddav_manager import CardDAVSourceManager
    from niles.sync.manager import CalendarSourceManager
    from niles.sync.notion import NotionSync
    from niles.sync.notion_embeddings import NotionEmbeddingPipeline
    from niles.sync.notion_summarizer import NotionSummarizer
    from niles.sync.ollama_embedder import OllamaEmbedder
    from niles.user_store import UserStore
    from niles.actions.notion import NotionRetriever
    from niles.vikunja_provisioning import VikunjaProvisioner
    from niles.vikunja_store import VikunjaCredentialStore
    from niles.whatsapp_store import WhatsAppSessionStore


# ---------------------------------------------------------------------------
# Store return TypedDicts
# ---------------------------------------------------------------------------


class MemoryEntry(TypedDict):
    """Single memory entry returned by MemoryStore.search / list_all."""

    key: str
    value: Any


class UserInfo(TypedDict):
    """Core user record returned by most UserStore methods."""

    id: int
    email: str
    display_name: str
    avatar_url: str | None
    is_admin: bool


class UserWithHash(UserInfo):
    """Extended user record with password hash (UserStore.get_with_hash)."""

    password_hash: str
    auth_method: str


class UserListItem(TypedDict):
    """User record for admin list views (UserStore.list_all)."""

    id: int
    email: str
    display_name: str
    auth_method: str
    is_admin: bool
    is_active: bool
    created_at: Any  # datetime
    last_login: Any  # datetime | None


class ContactPhone(TypedDict):
    """Single phone entry within a contact."""

    type: str
    number: str


class ContactInfo(TypedDict):
    """Contact record returned by ContactsAction.find_by_name."""

    full_name: str
    phone: str | None
    phones: list[ContactPhone]
    email: str | None


class WhatsAppSession(TypedDict):
    """WhatsApp session record."""

    user_id: int
    instance_name: str
    phone_number: str | None
    status: str


class VikunjaCredentials(TypedDict):
    """Vikunja credential record."""

    user_id: int
    api_token: str
    api_url: str
    password_synced: bool


class SignalMessage(TypedDict):
    """Single Signal message record."""

    from_me: bool
    text: str
    timestamp: int
    phone: str


class ConversationMessage(TypedDict):
    """Single conversation history message."""

    role: str
    content: str
    timestamp: str


# ---------------------------------------------------------------------------
# AppState Protocol
# ---------------------------------------------------------------------------


class AppState(Protocol):
    """Typed protocol for app.state attributes set in main.py lifespan."""

    settings: Settings
    pool: asyncpg.Pool
    agent: NilesAgent
    contacts_action: ContactsAction
    whatsapp_action: WhatsAppAction
    history: ConversationHistory
    settings_store: SettingsStore
    settings_action: SettingsAction
    weather_action: WeatherAction
    user_store: UserStore
    admin_action: AdminAction
    caldav: CalDAVSync | None
    calendar_manager: CalendarSourceManager
    wa_store: WhatsAppSessionStore
    carddav_manager: CardDAVSourceManager
    vikunja_store: VikunjaCredentialStore
    vikunja_setup_action: VikunjaSetupAction
    wa_setup_action: WhatsAppSetupAction
    vikunja_provisioner: VikunjaProvisioner | None
    briefing_generator: BriefingGenerator
    scheduler: Any
    signal_action: SignalAction | None
    signal_store: SignalMessageStore | None
    signal_setup_action: SignalSetupAction | None
    http_clients: HttpClients
    signal_disabled: bool
    shutdown_event: asyncio.Event
    signal_task: asyncio.Task[None] | None
    notion_sync: NotionSync | None
    notion_embedder: NotionEmbeddingPipeline | None
    notion_retriever: NotionRetriever | None
    notion_store: NotionStore | None
    ollama_embedder: OllamaEmbedder | None
    notion_summarizer: NotionSummarizer | None
