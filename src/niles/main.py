"""Niles AI Core – FastAPI entry point."""

import asyncio
import hmac
import logging
import os
import re
import secrets
import sys
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path

import asyncpg
import httpx
import structlog
from fastapi import Depends, FastAPI, HTTPException, Request, Security
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.security import APIKeyHeader
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError
from starlette.middleware.base import BaseHTTPMiddleware

from .logging_config import generate_request_id, setup_logging
from .metrics import HTTP_DURATION, HTTP_REQUESTS

from .actions.admin import AdminAction
from .actions.briefing import BriefingGenerator
from .errors import error_response
from .http_clients import HttpClients
from .actions.calendar import CalendarAction
from .jobs.briefing import send_daily_briefing, send_weekly_briefing
from .actions.contacts import ContactsAction
from .actions.settings import SettingsAction
from .actions.vikunja_setup import VikunjaSetupAction
from .actions.signal_setup import SignalSetupAction
from .actions.whatsapp_setup import WhatsAppSetupAction
from .actions.signal import SignalAction
from .actions.weather import WeatherAction
from .actions.whatsapp import WhatsAppAction
from .agent.core import NilesAgent
from .config import Settings, apply_overrides
from .crypto import FieldEncryptor
from .mcp.client import MCPManager
from .memory.history import ConversationHistory
from .memory.store import MemoryStore
from .notion_store import NotionStore
from .settings_store import SettingsStore
from .sources.web import router as web_router
from .user_store import UserStore
from .signal_store import SignalMessageStore
from .sources.signal import signal_listener
from .vikunja_store import VikunjaCredentialStore
from .whatsapp_store import WhatsAppSessionStore
from .sources.whatsapp import router as whatsapp_router
from .sync.caldav import CalDAVSync
from .sync.carddav_manager import CardDAVSourceManager
from .sync.manager import CalendarSourceManager

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
    except (ValueError, IndexError):
        logger.warning("Ungültige Briefing-Zeit '%s', verwende 07:30", time_str)
        return 7, 30


# Default logging until settings are loaded
setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown."""
    logger.info("Niles Core starting up...")

    try:
        settings = Settings()
    except ValidationError as exc:
        logger.error("Configuration error – required environment variables missing:")
        for error in exc.errors():
            field = error["loc"][-1] if error["loc"] else "unknown"
            logger.error("  %s: %s", field, error["msg"])
        logger.error(
            "Set EVOLUTION_POSTGRES_PASSWORD and EVOLUTION_API_KEY in .env or environment."
        )
        sys.exit(1)

    # Reconfigure logging with settings
    setup_logging(settings.log_level)

    # Warn if API key was auto-generated (do not log the key itself)
    if not os.environ.get("NILES_API_KEY"):
        logger.info(
            "NILES_API_KEY auto-generated. Retrieve with: "
            "docker exec niles_core printenv NILES_API_KEY"
        )
        logger.info("Set NILES_API_KEY in .env for a stable key.")

    # Startup security warnings
    if not os.environ.get("SESSION_SECRET"):
        logger.warning(
            "SESSION_SECRET not set — auto-generated (sessions won't survive restarts). "
            "Set SESSION_SECRET in .env for persistent sessions."
        )
    if not settings.base_url and settings.google_client_id:
        logger.warning(
            "BASE_URL not set but Google OAuth is configured — "
            "OAuth redirect URI will be derived from request headers (less secure). "
            "Set BASE_URL in .env for a stable redirect URI."
        )

    # Database connection pool
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

    # Verify schema is managed by Alembic
    try:
        alembic_version = await pool.fetchval(
            "SELECT version_num FROM alembic_version LIMIT 1"
        )
    except Exception:
        alembic_version = None
    if alembic_version is None:
        logger.error(
            "No alembic_version found. Database migrations have not been applied. "
            "Run 'python -m niles.migrate' or check entrypoint.sh."
        )
        sys.exit(1)
    logger.info("Database schema version: %s", alembic_version)

    # Credential encryption (column-level, Fernet AES-128-CBC + HMAC)
    encryptor: FieldEncryptor | None = None
    if settings.credential_encryption_key:
        encryptor = FieldEncryptor(settings.credential_encryption_key)
        logger.info("Credential encryption enabled")
    else:
        logger.warning(
            "CREDENTIAL_ENCRYPTION_KEY not set — credentials stored in plaintext. "
            'Generate with: python -c "from niles.crypto import FieldEncryptor; '
            'print(FieldEncryptor.generate_key())"'
        )

    # Memory & History
    memory = MemoryStore(pool)
    history = ConversationHistory(pool)

    # User store (Google OAuth users)
    user_store = UserStore(pool)
    await user_store.initialize()

    # WhatsApp session store (per-user Evolution API instances)
    wa_store = WhatsAppSessionStore(pool)

    # Vikunja credential store (per-user API tokens)
    vikunja_store = VikunjaCredentialStore(pool, encryptor=encryptor)

    # Vikunja auto-provisioning (register + token on first login)
    vikunja_provisioner = None
    if settings.vikunja_api_url:
        from .vikunja_provisioning import VikunjaProvisioner

        vikunja_provisioner = VikunjaProvisioner(
            api_url=settings.vikunja_api_url,
            session_secret=settings.session_secret,
            store=vikunja_store,
        )
        logger.info("Vikunja auto-provisioning enabled (%s)", settings.vikunja_api_url)

    # Admin action (user CRUD with password hashing + optional Vikunja sync)
    admin_action = AdminAction(
        user_store,
        vikunja_provisioner=vikunja_provisioner,
        vikunja_store=vikunja_store,
    )

    # Settings store (runtime overrides from DB)
    settings_store = SettingsStore(pool, encryptor=encryptor)
    overrides = await settings_store.get_all()
    if overrides:
        settings = apply_overrides(settings, overrides)
        logger.info("Applied %d settings override(s) from DB", len(overrides))

    # Notion store (pages + embeddings data access)
    notion_store = NotionStore(pool)

    # Shared HTTP clients (connection pooling)
    http_clients = HttpClients(settings)

    # Settings action (validation + persistence)
    settings_action = SettingsAction(settings_store, http_client=http_clients.general)

    # Weather action (location search + persistence)
    weather_action = WeatherAction(settings_store, http_client=http_clients.geocoding)

    # CardDAV Source Manager (per-user CardDAV contact sources)
    carddav_manager = CardDAVSourceManager(
        pool, encryptor=encryptor, client=http_clients.general
    )
    await carddav_manager.initialize()

    # CalDAV Sync (only for legacy discover_collections in settings UI)
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

    # Calendar Source Manager (unified sync for ICS + CalDAV)
    calendar_manager = CalendarSourceManager(
        pool,
        settings,
        client=http_clients.general,
        encryptor=encryptor,
    )
    await calendar_manager.initialize()
    calendar_sources = await calendar_manager.get_sources()

    # Scheduler – always started so jobs can be registered later
    # (e.g. CardDAV daily sync added via contacts_connect in the UI)
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    scheduler = AsyncIOScheduler()

    # CardDAV daily sync (all sources)
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

    calendar = None
    if settings.caldav_url or calendar_sources:
        calendar = CalendarAction(pool, timezone=settings.timezone)

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
        pool=pool,
        timezone=settings.timezone,
        vikunja_store=vikunja_store,
        weather_latitude=settings.weather_latitude,
        weather_longitude=settings.weather_longitude,
        weather_client=http_clients.open_meteo,
        vikunja_client=http_clients.general,
    )

    # Daily briefing: Mo-Fr (number auto-detected at runtime)
    if settings.feature_briefing_daily:
        hour, minute = _parse_briefing_time(settings.briefing_daily_time)
        scheduler.add_job(
            send_daily_briefing,
            "cron",
            args=[app.state],
            day_of_week="mon-fri",
            hour=hour,
            minute=minute,
            id="briefing_daily",
            max_instances=1,
            misfire_grace_time=600,
            timezone=settings.timezone,
        )
        logger.info("Daily briefing scheduled Mo-Fr at %02d:%02d", hour, minute)

    # Weekly overview: Monday (number auto-detected at runtime)
    if settings.feature_briefing_weekly:
        hour, minute = _parse_briefing_time(settings.briefing_weekly_time)
        scheduler.add_job(
            send_weekly_briefing,
            "cron",
            args=[app.state],
            day_of_week="mon",
            hour=hour,
            minute=minute,
            id="briefing_weekly",
            max_instances=1,
            misfire_grace_time=600,
            timezone=settings.timezone,
        )
        logger.info("Weekly briefing scheduled Mon at %02d:%02d", hour, minute)

    scheduler.start()

    # MCP Servers — inject settings as env vars before starting subprocesses.
    # NOTE: These env vars are read once at subprocess startup. Changing the
    # weather location via the Settings UI updates the DB and Settings object,
    # but the running MCP subprocess keeps its original env vars. A container
    # restart is required for location changes to take effect.
    if settings.weather_latitude:
        os.environ["WEATHER_LATITUDE"] = settings.weather_latitude
    if settings.weather_longitude:
        os.environ["WEATHER_LONGITUDE"] = settings.weather_longitude
    os.environ["WEATHER_TIMEZONE"] = settings.timezone

    # Web Search (SearXNG) — feature flag + URL for mcp_servers.yaml expansion
    os.environ["FEATURE_SEARCH"] = str(settings.feature_search).lower()
    os.environ["SEARXNG_URL"] = settings.searxng_url

    mcp_manager = MCPManager()
    await mcp_manager.start_all()

    # Actions
    contacts = ContactsAction(pool, carddav_manager=carddav_manager)
    vikunja_setup = VikunjaSetupAction(
        vikunja_store,
        http_client=http_clients.general,
        default_api_url=settings.vikunja_api_url,
    )
    whatsapp_action = WhatsAppAction(settings, client=http_clients.evolution)
    wa_setup_action = None
    if settings.evolution_api_url:
        wa_setup_action = WhatsAppSetupAction(
            wa_store,
            whatsapp_action,
            webhook_base_url=settings.webhook_base_url,
            evolution_api_key=settings.evolution_api_key,
        )

    # Signal (signal-cli-rest-api)
    signal_action = None
    signal_store = None
    signal_task = None
    signal_setup_action = None
    if settings.signal_api_url:
        signal_action = SignalAction(settings)
        signal_store = SignalMessageStore(pool)
        signal_setup_action = SignalSetupAction(
            signal_action, settings_store=settings_store
        )
        logger.info("Signal integration enabled (%s)", settings.signal_phone_number)

    # Agent (Vikunja tasks resolved per-user via vikunja_store, no global fallback)
    agent = NilesAgent(
        config=settings,
        contacts=contacts,
        whatsapp=whatsapp_action,
        memory=memory,
        history=history,
        mcp_manager=mcp_manager,
        calendar=calendar,
        calendar_manager=calendar_manager,
        wa_store=wa_store,
        vikunja_store=vikunja_store,
        signal=signal_action,
        signal_store=signal_store,
        http_client=http_clients.general,
    )

    # Notion RAG sync + embeddings + retrieval
    notion_sync = None
    notion_embedder = None
    notion_retriever = None
    ollama_embedder = None
    notion_summarizer = None
    if settings.feature_notion and settings.notion_token:
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
            logger.info(
                "Notion sync scheduled (every %d min)",
                settings.notion_sync_interval,
            )
        else:
            logger.info("Notion auto-sync disabled (interval=0)")
        asyncio.create_task(notion_sync_and_embed())

    # Wire Notion retriever into agent + context builder (for tool filtering)
    if notion_retriever:
        agent.notion_retriever = notion_retriever
        agent._ctx.notion_retriever = notion_retriever

    # Store on app state for access in route handlers
    app.state.settings = settings
    app.state.pool = pool
    app.state.agent = agent
    app.state.contacts_action = contacts
    app.state.whatsapp_action = whatsapp_action
    app.state.history = history
    app.state.settings_store = settings_store
    app.state.settings_action = settings_action
    app.state.weather_action = weather_action
    app.state.user_store = user_store
    app.state.admin_action = admin_action
    app.state.caldav = caldav_sync
    app.state.calendar_manager = calendar_manager
    app.state.wa_store = wa_store
    app.state.carddav_manager = carddav_manager
    app.state.vikunja_store = vikunja_store
    app.state.vikunja_setup_action = vikunja_setup
    app.state.wa_setup_action = wa_setup_action
    app.state.vikunja_provisioner = vikunja_provisioner
    app.state.briefing_generator = briefing_generator
    app.state.scheduler = scheduler
    app.state.signal_action = signal_action
    app.state.signal_store = signal_store
    app.state.signal_setup_action = signal_setup_action
    app.state.http_clients = http_clients
    app.state.notion_store = notion_store
    app.state.notion_sync = notion_sync
    app.state.notion_embedder = notion_embedder
    app.state.notion_retriever = notion_retriever
    app.state.ollama_embedder = ollama_embedder
    app.state.notion_summarizer = notion_summarizer

    # Cache signal_disabled flag from DB overrides (avoids DB query on
    # every 3s HTMX poll in signal_status endpoint).
    app.state.signal_disabled = overrides.get("signal_disabled") == "true"

    # Shutdown event for SSE drain
    shutdown_event = asyncio.Event()
    app.state.shutdown_event = shutdown_event

    # Start Signal WebSocket listener if phone number is already known
    # (from env var or previous auto-discovery stored in settings_store).
    # If no phone number yet, the listener starts dynamically after QR linking
    # via the signal_status endpoint in web.py.
    if signal_action and settings.signal_phone_number:
        signal_task = asyncio.create_task(signal_listener(app.state, shutdown_event))
        logger.info("Signal WebSocket listener started")
    app.state.signal_task = signal_task

    yield

    # Shutdown — signal SSE streams to close gracefully.
    # The drain window is best-effort: active LLM inference may exceed it.
    # SSE generators check the event between yielded items, so streams that
    # are idle or between tool calls will close within this window.
    logger.info("Shutdown initiated, draining SSE connections...")
    shutdown_event.set()
    await asyncio.sleep(0.5)

    # Stop Signal WebSocket listener (may have been started dynamically)
    sig_task = getattr(app.state, "signal_task", None)
    if sig_task and not sig_task.done():
        sig_task.cancel()
        try:
            await sig_task
        except asyncio.CancelledError:
            pass

    # Close Signal HTTP client
    if signal_action:
        await signal_action.close()

    if ollama_embedder:
        await ollama_embedder.close()
    if notion_summarizer:
        await notion_summarizer.close()
    await mcp_manager.stop_all()
    scheduler.shutdown(wait=False)
    await http_clients.close_all()
    await pool.close()
    logger.info("Niles Core shut down.")


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple in-memory rate limiter per client IP."""

    MAX_TRACKED_IPS = 10_000

    def __init__(self, app, requests_per_minute: int = 60):
        super().__init__(app)
        self.rpm = requests_per_minute
        self._hits: dict[str, list[float]] = defaultdict(list)

    def _evict_oldest(self) -> None:
        """Remove the oldest IP entry when the tracking table is full."""
        if len(self._hits) <= self.MAX_TRACKED_IPS:
            return
        oldest_ip = min(
            self._hits, key=lambda ip: self._hits[ip][-1] if self._hits[ip] else 0
        )
        del self._hits[oldest_ip]

    async def dispatch(self, request: Request, call_next):
        # Skip rate limiting for health checks and static files
        if request.url.path in ("/health", "/ready") or request.url.path.startswith(
            "/static"
        ):
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        now = time.monotonic()
        window = now - 60.0

        # Prune old entries and append current
        hits = self._hits[client_ip]
        self._hits[client_ip] = [t for t in hits if t > window]
        self._hits[client_ip].append(now)

        # Evict oldest IP if tracking table grows too large
        self._evict_oldest()

        if len(self._hits[client_ip]) > self.rpm:
            logger.warning("Rate limit exceeded for %s", client_ip)
            return error_response(429, "Too many requests")

        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add defence-in-depth security headers including nonce-based CSP."""

    async def dispatch(self, request: Request, call_next):
        nonce = secrets.token_urlsafe(16)
        request.state.csp_nonce = nonce

        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Strict-Transport-Security"] = (
            "max-age=63072000; includeSubDomains"
        )
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=()"
        )
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            f"script-src 'nonce-{nonce}' 'strict-dynamic'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https://*.googleusercontent.com; "
            "media-src 'self' data:; "
            "font-src 'self'; "
            "connect-src 'self'; "
            "base-uri 'self'; "
            "form-action 'self'; "
            "report-uri /csp-report"
        )
        return response


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Attach a unique request_id to every request via structlog contextvars."""

    async def dispatch(self, request: Request, call_next):
        incoming = request.headers.get("X-Request-ID", "")
        # Accept only short alphanumeric/dash/underscore IDs to prevent abuse
        if (
            incoming
            and len(incoming) <= 64
            and incoming.replace("-", "").replace("_", "").isalnum()
        ):
            request_id = incoming
        else:
            request_id = generate_request_id()
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class MetricsMiddleware(BaseHTTPMiddleware):
    """Record HTTP request count and duration for Prometheus."""

    _ID_RE = re.compile(
        r"/(\d+|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(?=/|$)",
        re.IGNORECASE,
    )

    @staticmethod
    def _normalize_path(path: str) -> str:
        """Replace numeric/UUID path segments to prevent label cardinality explosion.

        /api/admin/users/42/password → /api/admin/users/:id/password
        /api/calendar/sources/7/sync → /api/calendar/sources/:id/sync
        /items/550e8400-e29b-41d4-a716-446655440000 → /items/:id
        """
        return MetricsMiddleware._ID_RE.sub("/:id", path)

    async def dispatch(self, request: Request, call_next):
        if request.url.path in (
            "/metrics",
            "/health",
            "/ready",
            "/csp-report",
        ) or request.url.path.startswith("/static"):
            return await call_next(request)
        endpoint = self._normalize_path(request.url.path)
        with HTTP_DURATION.labels(method=request.method, endpoint=endpoint).time():
            response = await call_next(request)
        HTTP_REQUESTS.labels(
            method=request.method, endpoint=endpoint, status=response.status_code
        ).inc()
        return response


app = FastAPI(title="Niles AI Core", version="0.1.0", lifespan=lifespan)


async def _api_exception_handler(request: Request, exc: Exception) -> Response:
    """Return structured JSON errors for API clients, plain text for browsers."""
    accept = request.headers.get("accept", "")

    if isinstance(exc, HTTPException):
        status = exc.status_code
        message = exc.detail
    else:
        status = 500
        message = "Internal server error"
        logger.exception(
            "Unhandled exception on %s %s", request.method, request.url.path
        )

    if "text/html" in accept:
        return Response(content=str(message), status_code=status)

    return error_response(status, str(message))


app.add_exception_handler(HTTPException, _api_exception_handler)
app.add_exception_handler(Exception, _api_exception_handler)

# Middleware execution order (outermost first):
# 1. RequestIdMiddleware — every response gets X-Request-ID, even 429s
# 2. RateLimitMiddleware — reject abusive clients early
# 3. SecurityHeadersMiddleware — defence-in-depth headers
# 4. MetricsMiddleware — record timing (skips /metrics, /health, /static)
# Starlette applies middleware in reverse add_middleware order.
app.add_middleware(MetricsMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware, requests_per_minute=60)
app.add_middleware(RequestIdMiddleware)
app.include_router(whatsapp_router)
app.include_router(web_router)

# Static files (CSS, JS)
_static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_api_key(
    request: Request,
    api_key: str | None = Security(_api_key_header),
) -> str:
    """Validate X-API-Key header against settings.niles_api_key."""
    expected = request.app.state.settings.niles_api_key
    if not api_key or len(api_key) > 256 or not hmac.compare_digest(api_key, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return api_key


@app.get("/")
async def root():
    """Redirect to web UI."""
    return RedirectResponse(url="/ui/chat", status_code=303)


@app.get("/metrics")
async def metrics(_key: str = Depends(require_api_key)):
    """Prometheus metrics endpoint (API-key protected)."""
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )


@app.get("/health")
async def health():
    """Health check endpoint with DB pool status."""
    pool = app.state.pool
    return {
        "status": "ok",
        "db_pool": {
            "size": pool.get_size(),
            "free": pool.get_idle_size(),
            "min": pool.get_min_size(),
            "max": pool.get_max_size(),
        },
    }


@app.get("/ready")
async def readiness():
    """Readiness probe: checks DB connectivity and migration status."""
    pool = app.state.pool
    errors: list[str] = []

    try:
        await pool.fetchval("SELECT 1")
    except Exception as exc:
        logger.debug("Readiness probe DB check failed: %s", exc)
        errors.append("db: unreachable")

    try:
        version = await pool.fetchval("SELECT version_num FROM alembic_version LIMIT 1")
        if version is None:
            errors.append("alembic: no version found")
    except Exception as exc:
        logger.debug("Readiness probe alembic check failed: %s", exc)
        errors.append("alembic: unreachable")

    if errors:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "errors": errors},
        )

    return {"status": "ready", "alembic_version": version}


@app.post("/csp-report", status_code=204)
async def csp_report(request: Request) -> Response:
    """Receive Content-Security-Policy violation reports from browsers.

    Browsers send these automatically when a CSP directive is violated.
    No auth required (browsers send without credentials).
    """
    try:
        body = await request.json()
    except Exception:
        return Response(status_code=204)

    report = body.get("csp-report", body)
    logger.warning(
        "CSP violation: %s blocked by %s on %s",
        report.get("blocked-uri", "unknown"),
        report.get("violated-directive", "unknown"),
        report.get("document-uri", "unknown"),
    )
    return Response(status_code=204)


class ChatRequest(BaseModel):
    message: str


@app.post("/chat")
async def chat(request: ChatRequest, _key: str = Depends(require_api_key)):
    """Direct chat endpoint for testing (no WhatsApp)."""
    agent = app.state.agent
    event = {
        "type": "chat",
        "from": "api",
        "content": request.message,
        "metadata": {},
    }
    response = await agent.process_event(event)
    return {"response": response}
