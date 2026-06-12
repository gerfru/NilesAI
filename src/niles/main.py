"""Niles AI Core – FastAPI entry point."""

import asyncio
import hmac
import logging
import os
import re
import secrets
import sys
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import Depends, FastAPI, HTTPException, Request, Security
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.security import APIKeyHeader
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError
from starlette.middleware.base import BaseHTTPMiddleware

from .logging_config import generate_request_id, setup_logging
from .metrics import HTTP_DURATION, HTTP_REQUESTS

from .errors import error_response
from .config import Settings
from .sources.signal import signal_listener
from .sources.web import router as web_router
from .sources.whatsapp import router as whatsapp_router
from .startup import (
    setup_database,
    setup_encryptor,
    setup_mcp_and_actions,
    setup_notion_rag,
    setup_scheduler,
    setup_stores,
)

logger = logging.getLogger(__name__)


# Default logging until settings are loaded
setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown."""
    logger.info("Niles Core starting up...")

    # Guard: in-memory state (rate limiter, pending confirmations, echo guard)
    # requires a single worker process. Fail fast if misconfigured.
    workers = int(os.environ.get("WEB_CONCURRENCY", "1"))
    if workers > 1:
        logger.error(
            "WEB_CONCURRENCY=%d but Niles requires a single worker (in-memory state). "
            "Remove WEB_CONCURRENCY or set it to 1.",
            workers,
        )
        sys.exit(1)

    try:
        settings = Settings()
    except ValidationError as exc:
        logger.error("Configuration error – required environment variables missing:")
        for error in exc.errors():
            field = error["loc"][-1] if error["loc"] else "unknown"
            logger.error("  %s: %s", field, error["msg"])
        logger.error("Set EVOLUTION_POSTGRES_PASSWORD and EVOLUTION_API_KEY in .env or environment.")
        sys.exit(1)

    # Reconfigure logging with settings
    setup_logging(settings.log_level)

    # Optional Sentry error tracking (set SENTRY_DSN to enable)
    if settings.sentry_dsn:
        import sentry_sdk

        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            traces_sample_rate=settings.sentry_traces_sample_rate,
        )
        logger.info("Sentry error tracking enabled")

    # Warn if API key was auto-generated (do not log the key itself)
    if not os.environ.get("NILES_API_KEY"):
        logger.info("NILES_API_KEY auto-generated. Retrieve with: docker exec niles_core printenv NILES_API_KEY")
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

    # Core infrastructure
    pool = await setup_database(settings)
    encryptor = setup_encryptor(settings)

    # Data stores, managers, and DB overrides
    stores = await setup_stores(pool, settings, encryptor)
    settings = stores["settings"]  # may include DB overrides

    # Scheduler + calendar + briefing
    sched = await setup_scheduler(app.state, settings, stores)

    # MCP servers, actions, agent
    actions = await setup_mcp_and_actions(settings, stores, sched["calendar_action"], pool)

    # Notion RAG pipeline
    notion = await setup_notion_rag(pool, settings, actions["agent"], sched["scheduler"])

    # Wire app.state for route handlers
    app.state.settings = settings
    app.state.pool = pool
    app.state.agent = actions["agent"]
    app.state.contacts_action = actions["contacts_action"]
    app.state.whatsapp_action = actions["whatsapp_action"]
    app.state.history = stores["history"]
    app.state.settings_store = stores["settings_store"]
    app.state.settings_action = stores["settings_action"]
    app.state.weather_action = stores["weather_action"]
    app.state.user_store = stores["user_store"]
    app.state.admin_action = stores["admin_action"]
    app.state.caldav = stores["caldav_sync"]
    app.state.calendar_manager = stores["calendar_manager"]
    app.state.wa_store = stores["wa_store"]
    app.state.carddav_manager = stores["carddav_manager"]
    app.state.vikunja_store = stores["vikunja_store"]
    app.state.vikunja_setup_action = actions["vikunja_setup_action"]
    app.state.wa_setup_action = actions["wa_setup_action"]
    app.state.vikunja_provisioner = stores["vikunja_provisioner"]
    app.state.briefing_generator = sched["briefing_generator"]
    app.state.scheduler = sched["scheduler"]
    app.state.signal_action = actions["signal_action"]
    app.state.signal_store = actions["signal_store"]
    app.state.signal_setup_action = actions["signal_setup_action"]
    app.state.http_clients = stores["http_clients"]
    app.state.notion_store = stores["notion_store"]
    app.state.notion_sync = notion["notion_sync"]
    app.state.notion_embedder = notion["notion_embedder"]
    app.state.notion_retriever = notion["notion_retriever"]
    app.state.ollama_embedder = notion["ollama_embedder"]
    app.state.notion_summarizer = notion["notion_summarizer"]

    # Cache signal_disabled flag from DB overrides (avoids DB query on
    # every 3s HTMX poll in signal_status endpoint).
    app.state.signal_disabled = stores["overrides"].get("signal_disabled") == "true"

    # Shutdown event for SSE drain
    shutdown_event = asyncio.Event()
    app.state.shutdown_event = shutdown_event

    # Start Signal WebSocket listener if phone number is already known
    signal_task = None
    if actions["signal_action"] and settings.signal_phone_number:
        signal_task = asyncio.create_task(signal_listener(app.state, shutdown_event))
        logger.info("Signal WebSocket listener started")
    app.state.signal_task = signal_task

    yield

    # Shutdown — signal SSE streams to close gracefully
    logger.info("Shutdown initiated, draining SSE connections...")
    shutdown_event.set()
    await asyncio.sleep(0.5)

    sig_task = getattr(app.state, "signal_task", None)
    if sig_task and not sig_task.done():
        sig_task.cancel()
        try:
            await sig_task
        except asyncio.CancelledError:
            pass

    if actions["signal_action"]:
        await actions["signal_action"].close()
    if notion["ollama_embedder"]:
        await notion["ollama_embedder"].close()
    if notion["notion_summarizer"]:
        await notion["notion_summarizer"].close()
    await actions["mcp_manager"].stop_all()
    sched["scheduler"].shutdown(wait=False)
    await stores["http_clients"].close_all()
    await pool.close()
    logger.info("Niles Core shut down.")


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple in-memory rate limiter per client IP.

    Uses OrderedDict so eviction is O(1) via popitem(last=False).
    """

    MAX_TRACKED_IPS = 10_000

    def __init__(self, app, requests_per_minute: int = 60):
        super().__init__(app)
        self.rpm = requests_per_minute
        self._hits: OrderedDict[str, list[float]] = OrderedDict()

    async def dispatch(self, request: Request, call_next):
        # Skip rate limiting for health checks and static files
        if request.url.path in ("/health", "/ready") or request.url.path.startswith("/static"):
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        now = time.monotonic()
        window = now - 60.0

        # Prune old entries and append current
        hits = self._hits.get(client_ip, [])
        self._hits[client_ip] = [t for t in hits if t > window]
        self._hits[client_ip].append(now)
        self._hits.move_to_end(client_ip)

        # Evict least-recently-seen IP if tracking table grows too large
        while len(self._hits) > self.MAX_TRACKED_IPS:
            self._hits.popitem(last=False)

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
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
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
        if incoming and len(incoming) <= 64 and incoming.replace("-", "").replace("_", "").isalnum():
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
        HTTP_REQUESTS.labels(method=request.method, endpoint=endpoint, status=response.status_code).inc()
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
        logger.exception("Unhandled exception on %s %s", request.method, request.url.path)

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

    from .metrics import DB_POOL_FREE, DB_POOL_SIZE

    # Update DB pool saturation gauges on each scrape
    pool = getattr(app.state, "pool", None)
    if pool is not None:
        DB_POOL_SIZE.set(pool.get_size())
        DB_POOL_FREE.set(pool.get_idle_size())

    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )


@app.get("/health")
async def health():
    """Liveness probe. Pool stats are available via /metrics (API-key protected)."""
    return {"status": "ok"}


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
    message: str = Field(..., max_length=2000)
    user_id: int | None = None


@app.post("/chat")
async def chat(request: ChatRequest, _key: str = Depends(require_api_key)):
    """Direct chat endpoint for testing (no WhatsApp)."""
    chat_id = f"web-user-{request.user_id}" if request.user_id else "api"
    agent = app.state.agent
    event = {
        "type": "chat",
        "from": chat_id,
        "content": request.message,
        "metadata": {},
    }
    response = await agent.process_event(event)
    return {"response": response}
