# SPDX-License-Identifier: AGPL-3.0-only
"""Niles AI Core – Startup helpers extracted from lifespan()."""

import asyncio
import logging
import os
import sys
from dataclasses import dataclass, field
from typing import Any

import asyncpg
import httpx

from .actions.admin import AdminAction
from .actions.briefing import BriefingGenerator
from .actions.calendar import CalendarAction
from .actions.contacts import ContactsAction
from .actions.settings import SettingsAction
from .actions.signal import SignalAction
from .actions.signal_setup import SignalSetupAction
from .actions.vikunja_setup import VikunjaSetupAction
from .actions.weather import WeatherAction
from .actions.whatsapp import WhatsAppAction
from .actions.whatsapp_setup import WhatsAppSetupAction
from .agent.core import NilesAgent
from .config import Settings, apply_overrides
from .crypto import FieldEncryptor
from .http_clients import HttpClients
from .jobs.briefing import send_daily_briefing, send_weekly_briefing
from .mcp.client import MCPManager
from .memory.history import ConversationHistory
from .memory.store import MemoryStore
from .notion_store import NotionStore
from .settings_store import SettingsStore
from .signal_store import SignalMessageStore
from .sync.caldav import CalDAVSync
from .sync.carddav_manager import CardDAVSourceManager
from .sync.manager import CalendarSourceManager
from .user_store import UserStore
from .vikunja_store import VikunjaCredentialStore
from .whatsapp_store import WhatsAppSessionStore

logger = logging.getLogger(__name__)


def _parse_briefing_time(time_str: str) -> tuple[int, int]:
    """Parse 'HH:MM' string to (hour, minute) tuple."""
    try:
        parts = time_str.strip().split(":")
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
        return hour, minute
    except ValueError, IndexError:
        logger.warning("Ungültige Briefing-Zeit '%s', verwende 07:30", time_str)
        return 7, 30


@dataclass
class StartupContext:
    """Holds all objects created during startup for app.state wiring."""

    settings: Settings
    pool: asyncpg.Pool

    # Stores
    memory: MemoryStore
    history: ConversationHistory
    user_store: UserStore
    wa_store: WhatsAppSessionStore
    vikunja_store: VikunjaCredentialStore
    settings_store: SettingsStore
    notion_store: NotionStore
    signal_store: SignalMessageStore | None = None

    # Managers
    carddav_manager: CardDAVSourceManager | None = None
    caldav_sync: CalDAVSync | None = None
    calendar_manager: CalendarSourceManager | None = None
    http_clients: HttpClients | None = None
    mcp_manager: MCPManager | None = None

    # Actions
    admin_action: AdminAction | None = None
    settings_action: SettingsAction | None = None
    weather_action: WeatherAction | None = None
    contacts_action: ContactsAction | None = None
    whatsapp_action: WhatsAppAction | None = None
    wa_setup_action: WhatsAppSetupAction | None = None
    vikunja_setup_action: VikunjaSetupAction | None = None
    vikunja_provisioner: object | None = None
    signal_action: SignalAction | None = None
    signal_setup_action: SignalSetupAction | None = None
    calendar_action: CalendarAction | None = None
    briefing_generator: BriefingGenerator | None = None
    agent: NilesAgent | None = None

    # Notion RAG
    notion_sync: object | None = None
    notion_embedder: object | None = None
    notion_retriever: object | None = None
    ollama_embedder: object | None = None
    notion_summarizer: object | None = None

    # Scheduler & tasks
    scheduler: object | None = None
    signal_task: asyncio.Task | None = None
    encryptor: FieldEncryptor | None = None

    # DB overrides snapshot
    overrides: dict = field(default_factory=dict)


async def setup_database(settings: Settings) -> asyncpg.Pool:
    """Create the asyncpg connection pool and verify Alembic schema."""
    pool = await asyncpg.create_pool(
        host=settings.postgres_host,
        port=settings.postgres_port,
        database=settings.postgres_db,
        user=settings.postgres_user,
        password=settings.postgres_password,
        min_size=2,
        max_size=10,
    )
    logger.info("PostgreSQL pool created")

    try:
        alembic_version = await pool.fetchval("SELECT version_num FROM alembic_version LIMIT 1")
    except asyncpg.PostgresError:
        alembic_version = None
    if alembic_version is None:
        logger.error(
            "No alembic_version found. Database migrations have not been applied. "
            "Run 'python -m niles.migrate' or check entrypoint.sh."
        )
        sys.exit(1)
    logger.info("Database schema version: %s", alembic_version)

    return pool


def setup_encryptor(settings: Settings) -> FieldEncryptor | None:
    """Initialize credential encryption if a key is configured."""
    if settings.credential_encryption_key:
        encryptor = FieldEncryptor(settings.credential_encryption_key)
        logger.info("Credential encryption enabled")
        return encryptor

    logger.warning(
        "CREDENTIAL_ENCRYPTION_KEY not set — credentials stored in plaintext. "
        "This is only allowed because CREDENTIAL_ENCRYPTION_OPTIONAL=true. "
        'Generate a key: python -c "from niles.crypto import FieldEncryptor; '
        'print(FieldEncryptor.generate_key())"'
    )
    return None


async def setup_stores(
    pool: asyncpg.Pool,
    settings: Settings,
    encryptor: FieldEncryptor | None,
) -> dict[str, Any]:
    """Initialize all data stores, managers, and apply DB overrides."""
    memory = MemoryStore(pool)
    history = ConversationHistory(pool)
    user_store = UserStore(pool)
    await user_store.initialize()
    wa_store = WhatsAppSessionStore(pool)
    vikunja_store = VikunjaCredentialStore(pool, encryptor=encryptor)

    # Vikunja auto-provisioning
    vikunja_provisioner = None
    if settings.vikunja_api_url:
        from .vikunja_provisioning import VikunjaProvisioner

        vikunja_provisioner = VikunjaProvisioner(
            api_url=settings.vikunja_api_url,
            session_secret=settings.session_secret,
            store=vikunja_store,
        )
        logger.info("Vikunja auto-provisioning enabled (%s)", settings.vikunja_api_url)

    admin_action = AdminAction(
        user_store,
        vikunja_provisioner=vikunja_provisioner,
        vikunja_store=vikunja_store,
    )

    # Settings store with runtime overrides
    settings_store = SettingsStore(pool, encryptor=encryptor)
    overrides = await settings_store.get_all()
    if overrides:
        settings = apply_overrides(settings, overrides)
        logger.info("Applied %d settings override(s) from DB", len(overrides))

    notion_store = NotionStore(pool)
    http_clients = HttpClients(settings)
    settings_action = SettingsAction(settings_store, http_client=http_clients.general)
    weather_action = WeatherAction(settings_store, http_client=http_clients.geocoding)

    # CardDAV Source Manager
    carddav_manager = CardDAVSourceManager(pool, encryptor=encryptor, client=http_clients.general)
    await carddav_manager.initialize()

    # CalDAV Sync (legacy discover_collections)
    caldav_sync = None
    if settings.caldav_url:
        caldav_sync = CalDAVSync(
            pool=pool,
            caldav_url=settings.caldav_url,
            auth=httpx.BasicAuth(settings.caldav_user, settings.caldav_password),
            timezone=settings.timezone,
            caldav_calendars=settings.caldav_calendars,
            client=http_clients.general,
        )

    # Calendar Source Manager
    calendar_manager = CalendarSourceManager(
        pool,
        settings,
        client=http_clients.general,
        encryptor=encryptor,
    )
    await calendar_manager.initialize()

    return {
        "settings": settings,
        "memory": memory,
        "history": history,
        "user_store": user_store,
        "wa_store": wa_store,
        "vikunja_store": vikunja_store,
        "vikunja_provisioner": vikunja_provisioner,
        "admin_action": admin_action,
        "settings_store": settings_store,
        "overrides": overrides,
        "notion_store": notion_store,
        "http_clients": http_clients,
        "settings_action": settings_action,
        "weather_action": weather_action,
        "carddav_manager": carddav_manager,
        "caldav_sync": caldav_sync,
        "calendar_manager": calendar_manager,
    }


async def setup_scheduler(app_state: Any, settings: Settings, stores: dict[str, Any]) -> dict[str, Any]:
    """Create APScheduler and register CardDAV, Calendar, and Briefing jobs."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    scheduler = AsyncIOScheduler()
    carddav_manager = stores["carddav_manager"]
    calendar_manager = stores["calendar_manager"]
    vikunja_store = stores["vikunja_store"]
    http_clients = stores["http_clients"]

    # CardDAV daily sync
    carddav_sources = await carddav_manager.get_sources()
    if carddav_sources:
        scheduler.add_job(
            carddav_manager.sync_all,
            "cron",
            hour=3,
            minute=0,
            id="carddav_daily_sync",
            max_instances=1,
            misfire_grace_time=300,
        )
        asyncio.create_task(carddav_manager.sync_all())
        logger.info(
            "CardDAV sync scheduled (daily at 03:00), %d source(s)",
            len(carddav_sources),
        )

    # Calendar source sync
    calendar_sources = await calendar_manager.get_sources()
    calendar_action = None
    if settings.caldav_url or calendar_sources:
        calendar_action = CalendarAction(stores["memory"].pool, timezone=settings.timezone)

    if calendar_sources:
        scheduler.add_job(
            calendar_manager.sync_all,
            "cron",
            hour=3,
            minute=20,
            id="calendar_sources_sync",
            max_instances=1,
            misfire_grace_time=300,
        )
        asyncio.create_task(calendar_manager.sync_all())
        logger.info(
            "Calendar source sync scheduled (daily at 03:20), %d source(s)",
            len(calendar_sources),
        )

    # Briefing Generator
    briefing_generator = BriefingGenerator(
        pool=stores["memory"].pool,
        timezone=settings.timezone,
        vikunja_store=vikunja_store,
        weather_latitude=settings.weather_latitude,
        weather_longitude=settings.weather_longitude,
        weather_client=http_clients.open_meteo,
        vikunja_client=http_clients.general,
    )

    if settings.feature_briefing_daily:
        hour, minute = _parse_briefing_time(settings.briefing_daily_time)
        scheduler.add_job(
            send_daily_briefing,
            "cron",
            args=[app_state],
            day_of_week="mon-fri",
            hour=hour,
            minute=minute,
            id="briefing_daily",
            max_instances=1,
            misfire_grace_time=600,
            timezone=settings.timezone,
        )
        logger.info("Daily briefing scheduled Mo-Fr at %02d:%02d", hour, minute)

    if settings.feature_briefing_weekly:
        hour, minute = _parse_briefing_time(settings.briefing_weekly_time)
        scheduler.add_job(
            send_weekly_briefing,
            "cron",
            args=[app_state],
            day_of_week="mon",
            hour=hour,
            minute=minute,
            id="briefing_weekly",
            max_instances=1,
            misfire_grace_time=600,
            timezone=settings.timezone,
        )
        logger.info("Weekly briefing scheduled Mon at %02d:%02d", hour, minute)

    # Conversation history pruning (weekly, Sunday 04:00)
    history = stores["history"]
    scheduler.add_job(
        history.prune,
        "cron",
        kwargs={"retention_days": settings.history_retention_days},
        day_of_week="sun",
        hour=4,
        minute=0,
        id="history_pruning",
        max_instances=1,
        misfire_grace_time=600,
    )
    logger.info("History pruning scheduled (Sun 04:00, retention=%d days)", settings.history_retention_days)

    scheduler.start()

    return {
        "scheduler": scheduler,
        "calendar_action": calendar_action,
        "briefing_generator": briefing_generator,
    }


async def setup_mcp_and_actions(
    settings: Settings, stores: dict[str, Any], calendar_action: Any, pool: asyncpg.Pool
) -> dict[str, Any]:
    """Set up MCP servers, create all action objects, and build the agent."""
    # MCP env vars (read once at subprocess startup)
    if settings.weather_latitude:
        os.environ["WEATHER_LATITUDE"] = settings.weather_latitude
    if settings.weather_longitude:
        os.environ["WEATHER_LONGITUDE"] = settings.weather_longitude
    os.environ["WEATHER_TIMEZONE"] = settings.timezone
    os.environ["FEATURE_SEARCH"] = str(settings.feature_search).lower()
    os.environ["SEARXNG_URL"] = settings.searxng_url

    mcp_manager = MCPManager()
    await mcp_manager.start_all()

    http_clients = stores["http_clients"]

    contacts = ContactsAction(
        pool, carddav_manager=stores["carddav_manager"], phone_country_code=settings.phone_country_code
    )
    vikunja_setup = VikunjaSetupAction(
        stores["vikunja_store"],
        http_client=http_clients.general,
        default_api_url=settings.vikunja_api_url,
    )
    whatsapp_action = WhatsAppAction(settings, client=http_clients.evolution)
    wa_setup_action = None
    if settings.evolution_api_url:
        wa_setup_action = WhatsAppSetupAction(
            stores["wa_store"],
            whatsapp_action,
            webhook_base_url=settings.webhook_base_url,
            webhook_token=settings.webhook_token,
        )

    # Signal
    signal_action = None
    signal_store = None
    signal_setup_action = None
    if settings.signal_api_url:
        signal_action = SignalAction(settings)
        signal_store = SignalMessageStore(pool)
        signal_setup_action = SignalSetupAction(signal_action, settings_store=stores["settings_store"])
        logger.info("Signal integration enabled (%s)", settings.signal_phone_number)

    # Agent
    agent = NilesAgent(
        config=settings,
        contacts=contacts,
        whatsapp=whatsapp_action,
        memory=stores["memory"],
        history=stores["history"],
        mcp_manager=mcp_manager,
        calendar=calendar_action,
        calendar_manager=stores["calendar_manager"],
        wa_store=stores["wa_store"],
        vikunja_store=stores["vikunja_store"],
        signal=signal_action,
        signal_store=signal_store,
        user_store=stores["user_store"],
        http_client=http_clients.general,
    )

    return {
        "mcp_manager": mcp_manager,
        "contacts_action": contacts,
        "vikunja_setup_action": vikunja_setup,
        "whatsapp_action": whatsapp_action,
        "wa_setup_action": wa_setup_action,
        "signal_action": signal_action,
        "signal_store": signal_store,
        "signal_setup_action": signal_setup_action,
        "agent": agent,
    }


async def setup_notion_rag(pool: asyncpg.Pool, settings: Settings, agent: Any, scheduler: Any) -> dict[str, Any]:
    """Initialize Notion RAG pipeline (sync, embeddings, retrieval) if enabled."""
    result = {
        "notion_sync": None,
        "notion_embedder": None,
        "notion_retriever": None,
        "ollama_embedder": None,
        "notion_summarizer": None,
    }

    if not (settings.feature_notion and settings.notion_token):
        return result

    from .sync.notion import NotionSync
    from .sync.notion_embeddings import NotionEmbeddingPipeline
    from .sync.notion_summarizer import NotionSummarizer
    from .sync.ollama_embedder import OllamaEmbedder
    from .actions.notion import NotionRetriever

    ollama_embedder = OllamaEmbedder(
        ollama_base_url=settings.llm_base_url,
        model=settings.notion_embedding_model,
    )
    notion_summarizer = NotionSummarizer(
        ollama_base_url=settings.llm_base_url,
        model=settings.notion_summary_model or settings.llm_model,
        max_input_chars=settings.notion_summary_max_input,
        max_tokens=settings.notion_summary_max_tokens,
    )
    notion_sync = NotionSync(pool, settings.notion_token)
    notion_embedder = NotionEmbeddingPipeline(
        pool=pool,
        embedder=ollama_embedder,
        chunk_size=settings.notion_chunk_size,
        chunk_overlap=settings.notion_chunk_overlap,
        summarizer=notion_summarizer,
    )
    notion_retriever = NotionRetriever(
        pool=pool,
        embedder=ollama_embedder,
        similarity_threshold=settings.notion_similarity_threshold,
    )

    _notion_lock = asyncio.Lock()

    async def notion_sync_and_embed():
        if _notion_lock.locked():
            logger.info("Notion sync skipped (already running)")
            return
        async with _notion_lock:
            await notion_sync.sync_all()
            await notion_embedder.embed_pending()

    if settings.notion_sync_interval > 0:
        scheduler.add_job(
            notion_sync_and_embed,
            "interval",
            minutes=settings.notion_sync_interval,
            id="notion_sync",
            max_instances=1,
            misfire_grace_time=600,
        )
        logger.info("Notion sync scheduled (every %d min)", settings.notion_sync_interval)
    else:
        logger.info("Notion auto-sync disabled (interval=0)")
    asyncio.create_task(notion_sync_and_embed())

    # Wire retriever into agent
    agent.notion_retriever = notion_retriever
    agent._ctx.notion_retriever = notion_retriever

    return {
        "notion_sync": notion_sync,
        "notion_embedder": notion_embedder,
        "notion_retriever": notion_retriever,
        "ollama_embedder": ollama_embedder,
        "notion_summarizer": notion_summarizer,
    }
