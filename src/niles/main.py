"""Niles AI Core – FastAPI entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown."""
    logger.info("Niles Core starting up...")
    # Startup: DB, MCP, Scheduler etc. will be added in later stages
    yield
    # Shutdown
    logger.info("Niles Core shutting down...")


app = FastAPI(title="Niles AI Core", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}
