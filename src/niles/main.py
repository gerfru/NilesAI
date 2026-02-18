"""Niles AI Core – FastAPI entry point."""

import asyncio
import hmac
import logging
import os
import sys
import time
from collections import defaultdict
from contextlib import asynccontextmanager

import asyncpg
from fastapi import Depends, FastAPI, HTTPException, Request, Security
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, ValidationError
from starlette.middleware.base import BaseHTTPMiddleware

from .actions.calendar import CalendarAction
from .actions.contacts import ContactsAction
from .actions.whatsapp import WhatsAppAction
from .agent.core import NilesAgent
from .config import Settings
from .mcp.client import MCPManager
from .memory.history import ConversationHistory
from .memory.store import MemoryStore
from .sources.whatsapp import router as whatsapp_router
from .sync.caldav import CalDAVSync
from .sync.carddav import CardDAVSync

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

    # CardDAV Sync
    carddav_sync = CardDAVSync(pool, settings)
    await carddav_sync.initialize()

    # CalDAV Sync
    caldav_sync = CalDAVSync(pool, settings)
    await caldav_sync.initialize()

    # Scheduler (shared by CardDAV and CalDAV)
    scheduler = None
    if settings.feature_carddav_sync or settings.feature_caldav_sync:
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
    if settings.feature_caldav_sync:
        scheduler.add_job(
            caldav_sync.sync_events, "cron", hour=3, minute=15,
            id="caldav_daily_sync",
            max_instances=1, misfire_grace_time=300,
        )
        asyncio.create_task(caldav_sync.sync_events())
        calendar = CalendarAction(pool, timezone=settings.timezone)
        logger.info("CalDAV sync scheduled (daily at 03:15)")

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
        caldav_sync=caldav_sync if settings.feature_caldav_sync else None,
    )

    # Store on app state for access in route handlers
    app.state.settings = settings
    app.state.pool = pool
    app.state.agent = agent
    app.state.whatsapp_action = whatsapp_action

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
        # Skip rate limiting for health checks
        if request.url.path == "/health":
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


app = FastAPI(title="Niles AI Core", version="0.1.0", lifespan=lifespan)
app.add_middleware(RateLimitMiddleware, requests_per_minute=60)
app.include_router(whatsapp_router)

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


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}


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
