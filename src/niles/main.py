"""Niles AI Core – FastAPI entry point."""

import asyncio
import hmac
import logging
import os
import re
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

from .actions.briefing import BriefingGenerator
from .actions.calendar import CalendarAction
from .jobs.briefing import send_daily_briefing, send_weekly_briefing
from .actions.contacts import ContactsAction
from .actions.signal import SignalAction
from .actions.whatsapp import WhatsAppAction
from .agent.core import NilesAgent
from .config import Settings, apply_overrides
from .mcp.client import MCPManager
from .memory.history import ConversationHistory
from .memory.store import MemoryStore
from .settings_store import SettingsStore
from .sources.web import router as web_router
from .user_store import UserStore
from .signal_store import SignalMessageStore
from .sources.signal import signal_listener
from .vikunja_store import VikunjaCredentialStore
from .whatsapp_store import WhatsAppSessionStore
from .sources.whatsapp import router as whatsapp_router
from .sync.caldav import CalDAVSync
from .sync.carddav import CardDAVSync
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

    # Memory & History
    memory = MemoryStore(pool)
    await memory.initialize()
    history = ConversationHistory(pool)
    await history.initialize()

    # User store (Google OAuth users)
    user_store = UserStore(pool)
    await user_store.initialize()

    # WhatsApp session store (per-user Evolution API instances)
    wa_store = WhatsAppSessionStore(pool)
    await wa_store.initialize()

    # Vikunja credential store (per-user API tokens)
    vikunja_store = VikunjaCredentialStore(pool)
    await vikunja_store.initialize()

    # Settings store (runtime overrides from DB)
    settings_store = SettingsStore(pool)
    await settings_store.initialize()
    overrides = await settings_store.get_all()
    if overrides:
        settings = apply_overrides(settings, overrides)
        logger.info("Applied %d settings override(s) from DB", len(overrides))

    # CardDAV Sync
    carddav_sync = CardDAVSync(pool, settings)
    await carddav_sync.initialize()

    # CalDAV Sync (only for legacy discover_collections in settings UI)
    caldav_sync = None
    if settings.caldav_url:
        caldav_sync = CalDAVSync(
            pool=pool,
            caldav_url=settings.caldav_url,
            auth=httpx.BasicAuth(settings.caldav_user, settings.caldav_password),
            timezone=settings.timezone,
            caldav_calendars=settings.caldav_calendars,
        )
        await caldav_sync.initialize()

    # Calendar Source Manager (unified sync for ICS + CalDAV + Google)
    calendar_manager = CalendarSourceManager(pool, settings)
    await calendar_manager.initialize()
    calendar_sources = await calendar_manager.get_sources()

    # Scheduler – always started so jobs can be registered later
    # (e.g. CardDAV daily sync added via contacts_connect in the UI)
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    scheduler = AsyncIOScheduler()

    if settings.carddav_url:
        scheduler.add_job(
            carddav_sync.sync_contacts,
            "cron",
            hour=3,
            minute=0,
            id="carddav_daily_sync",
            max_instances=1,
            misfire_grace_time=300,
        )
        asyncio.create_task(carddav_sync.sync_contacts())
        logger.info("CardDAV sync scheduled (daily at 03:00)")

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
        vikunja_api_url=settings.vikunja_api_url,
        vikunja_api_token=settings.vikunja_api_token,
        weather_latitude=settings.weather_latitude,
        weather_longitude=settings.weather_longitude,
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

    mcp_manager = MCPManager()
    await mcp_manager.start_all()

    # Actions
    contacts = ContactsAction(pool)
    whatsapp_action = WhatsAppAction(settings)

    # Signal (signal-cli-rest-api)
    signal_action = None
    signal_store = None
    signal_task = None
    if settings.signal_api_url:
        signal_action = SignalAction(settings)
        signal_store = SignalMessageStore(pool)
        await signal_store.initialize()
        logger.info("Signal integration enabled (%s)", settings.signal_phone_number)

    # Vikunja (Todo/Task Management)
    tasks_action = None
    if settings.feature_vikunja and settings.vikunja_api_url:
        from .actions.tasks import TasksAction

        tasks_action = TasksAction(
            api_url=settings.vikunja_api_url,
            api_token=settings.vikunja_api_token,
        )
        logger.info("Vikunja task management enabled")

    # Agent
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
        tasks=tasks_action,
        vikunja_store=vikunja_store,
        signal=signal_action,
        signal_store=signal_store,
    )

    # Store on app state for access in route handlers
    app.state.settings = settings
    app.state.pool = pool
    app.state.agent = agent
    app.state.whatsapp_action = whatsapp_action
    app.state.history = history
    app.state.settings_store = settings_store
    app.state.user_store = user_store
    app.state.caldav = caldav_sync
    app.state.calendar_manager = calendar_manager
    app.state.wa_store = wa_store
    app.state.carddav_sync = carddav_sync
    app.state.vikunja_store = vikunja_store
    app.state.briefing_generator = briefing_generator
    app.state.scheduler = scheduler
    app.state.signal_action = signal_action
    app.state.signal_store = signal_store

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

    await mcp_manager.stop_all()
    scheduler.shutdown(wait=False)
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
        if request.url.path == "/health" or request.url.path.startswith("/static"):
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
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests"},
            )

        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add defence-in-depth security headers to all responses."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=()"
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
        if request.url.path in ("/metrics", "/health") or request.url.path.startswith(
            "/static"
        ):
            return await call_next(request)
        endpoint = self._normalize_path(request.url.path)
        with HTTP_DURATION.labels(method=request.method, endpoint=endpoint).time():
            response = await call_next(request)
        HTTP_REQUESTS.labels(
            method=request.method, endpoint=endpoint, status=response.status_code
        ).inc()
        return response


app = FastAPI(title="Niles AI Core", version="0.1.0", lifespan=lifespan)
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
