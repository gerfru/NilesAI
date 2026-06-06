"""Shared type definitions for Niles Core.

Provides a typed Protocol for app.state so mypy can verify attribute access
without runtime overhead.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    import asyncpg

    from niles.actions.briefing import BriefingGenerator
    from niles.actions.signal import SignalAction
    from niles.http_clients import HttpClients
    from niles.actions.whatsapp import WhatsAppAction
    from niles.agent.core import NilesAgent
    from niles.config import Settings
    from niles.memory.history import ConversationHistory
    from niles.settings_store import SettingsStore
    from niles.signal_store import SignalMessageStore
    from niles.sync.caldav import CalDAVSync
    from niles.sync.carddav_manager import CardDAVSourceManager
    from niles.sync.manager import CalendarSourceManager
    from niles.user_store import UserStore
    from niles.actions.notion import NotionRetriever
    from niles.sync.notion import NotionSync
    from niles.sync.notion_embeddings import NotionEmbeddingPipeline
    from niles.vikunja_provisioning import VikunjaProvisioner
    from niles.vikunja_store import VikunjaCredentialStore
    from niles.whatsapp_store import WhatsAppSessionStore


class AppState(Protocol):
    """Typed protocol for app.state attributes set in main.py lifespan."""

    settings: Settings
    pool: asyncpg.Pool
    agent: NilesAgent
    whatsapp_action: WhatsAppAction
    history: ConversationHistory
    settings_store: SettingsStore
    user_store: UserStore
    caldav: CalDAVSync | None
    calendar_manager: CalendarSourceManager
    wa_store: WhatsAppSessionStore
    carddav_manager: CardDAVSourceManager
    vikunja_store: VikunjaCredentialStore
    vikunja_provisioner: VikunjaProvisioner | None
    briefing_generator: BriefingGenerator
    scheduler: Any
    signal_action: SignalAction | None
    signal_store: SignalMessageStore | None
    http_clients: HttpClients
    signal_disabled: bool
    shutdown_event: asyncio.Event
    signal_task: asyncio.Task[None] | None
    notion_sync: NotionSync | None
    notion_embedder: NotionEmbeddingPipeline | None
    notion_retriever: NotionRetriever | None
