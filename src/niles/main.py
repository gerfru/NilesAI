"""Niles AI Core – FastAPI entry point."""

import asyncio
import hmac
import logging
import os
import sys
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path

import asyncpg
import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Security
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.security import APIKeyHeader
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError
from starlette.middleware.base import BaseHTTPMiddleware

from .actions.calendar import CalendarAction
from .actions.contacts import ContactsAction
from .actions.whatsapp import WhatsAppAction
from .agent.core import NilesAgent
from .config import Settings, apply_overrides
from .mcp.client import MCPManager
from .memory.history import ConversationHistory
from .memory.store import MemoryStore
from .settings_store import SettingsStore
from .sources.web import router as web_router
from .user_store import UserStore
from .sources.whatsapp import router as whatsapp_router
from .sync.caldav import CalDAVSync
from .sync.carddav import CardDAVSync
from .sync.manager import CalendarSourceManager

logger = logging.getLogger(__name__)


def _configure_logging(level: str = "INFO") -> None:
    """Configure root logger with the given level."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )


# Default logging until settings are loaded
_configure_logging()


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
    _configure_logging(settings.log_level)

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

    # CalDAV Sync (kept for discover_collections in settings UI)
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

    # Scheduler (shared by CardDAV, CalDAV, and calendar sources)
    scheduler = None
    needs_scheduler = (
        settings.feature_carddav_sync
        or settings.feature_caldav_sync
        or calendar_sources
    )
    if needs_scheduler:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler

        scheduler = AsyncIOScheduler()

    if settings.feature_carddav_sync:
        scheduler.add_job(
            carddav_sync.sync_contacts, "cron", hour=3, minute=0,
            id="carddav_daily_sync",
            max_instances=1, misfire_grace_time=300,
        )
        asyncio.create_task(carddav_sync.sync_contacts())
        logger.info("CardDAV sync scheduled (daily at 03:00)")

    calendar = None
    if settings.feature_caldav_sync or calendar_sources:
        calendar = CalendarAction(pool, timezone=settings.timezone)

    if calendar_sources:
        scheduler.add_job(
            calendar_manager.sync_all, "cron", hour=3, minute=20,
            id="calendar_sources_sync",
            max_instances=1, misfire_grace_time=300,
        )
        asyncio.create_task(calendar_manager.sync_all())
        logger.info(
            "Calendar source sync scheduled (daily at 03:20), %d source(s)",
            len(calendar_sources),
        )

    if scheduler:
        scheduler.start()

    # MCP Servers
    mcp_manager = MCPManager()
    await mcp_manager.start_all()

    # Actions
    contacts = ContactsAction(pool)
    whatsapp_action = WhatsAppAction(settings)

    # Agent
    agent = NilesAgent(
        config=settings,
        contacts=contacts,
        whatsapp=whatsapp_action,
        memory=memory,
        history=history,
        mcp_manager=mcp_manager,
        calendar=calendar,
        calendar_manager=calendar_manager if calendar_sources else None,
    )

    # Store on app state for access in route handlers
    app.state.settings = settings
    app.state.pool = pool
    app.state.agent = agent
    app.state.whatsapp_action = whatsapp_action
    app.state.history = history
    app.state.settings_store = settings_store
    app.state.user_store = user_store
    app.state.caldav = caldav_sync if settings.feature_caldav_sync else None
    app.state.calendar_manager = calendar_manager

    yield

    # Shutdown
    await mcp_manager.stop_all()
    if scheduler:
        scheduler.shutdown()
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
        oldest_ip = min(self._hits, key=lambda ip: self._hits[ip][-1] if self._hits[ip] else 0)
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


app = FastAPI(title="Niles AI Core", version="0.1.0", lifespan=lifespan)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware, requests_per_minute=60)
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
