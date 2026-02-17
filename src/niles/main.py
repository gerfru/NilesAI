"""Niles AI Core – FastAPI entry point."""

import logging
import sys
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI
from pydantic import BaseModel, ValidationError

from .actions.contacts import ContactsAction
from .actions.whatsapp import WhatsAppAction
from .agent.core import NilesAgent
from .config import Settings
from .sources.whatsapp import router as whatsapp_router

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

    # Actions
    contacts = ContactsAction(pool)
    whatsapp_action = WhatsAppAction(settings)

    # Agent
    agent = NilesAgent(
        config=settings,
        contacts=contacts,
        whatsapp=whatsapp_action,
    )

    # Store on app state for access in route handlers
    app.state.pool = pool
    app.state.agent = agent
    app.state.whatsapp_action = whatsapp_action

    yield

    # Shutdown
    await pool.close()
    logger.info("Niles Core shut down.")


app = FastAPI(title="Niles AI Core", version="0.1.0", lifespan=lifespan)
app.include_router(whatsapp_router)


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}


class ChatRequest(BaseModel):
    message: str


@app.post("/chat")
async def chat(request: ChatRequest):
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
