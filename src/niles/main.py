"""Niles AI Core – FastAPI entry point."""

import logging
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI
from pydantic import BaseModel

from .actions.contacts import ContactsAction
from .actions.whatsapp import WhatsAppAction
from .agent.core import NilesAgent
from .config import Settings
from .sources.whatsapp import router as whatsapp_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown."""
    logger.info("Niles Core starting up...")

    settings = Settings()

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
