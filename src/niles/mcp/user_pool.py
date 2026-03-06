"""Per-user MCP server pool for gws (Google Workspace CLI).

Each user who has connected their Google account gets a dedicated gws
subprocess, started lazily on first tool call and cleaned up after an
idle timeout.  All instances expose the same tools — tool definitions
are discovered once from the first instance and cached.
"""

import asyncio
import logging
import os
import time
from contextlib import AsyncExitStack
from datetime import datetime, timedelta, timezone

import httpx
from mcp import ClientSession, StdioServerParameters, stdio_client

from ..google_token_store import GoogleTokenStore
from .client import (
    _DESTRUCTIVE_PREFIXES,
    _VALID_TOOL_NAME,
    _coerce_arguments,
    _mcp_tool_to_openai,
)

logger = logging.getLogger(__name__)

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"

_IDLE_TIMEOUT = 1800  # 30 minutes
_TOKEN_REFRESH_BUFFER = 300  # refresh 5 min before expiry
_STARTUP_TIMEOUT = 15  # seconds
_MAX_RESULT_SIZE = 100_000  # 100 KB


class _UserMCPInstance:
    """A single gws MCP server subprocess for one user."""

    def __init__(
        self,
        user_id: int,
        command: str,
        services: str,
        access_token: str,
        token_expires_at: datetime | None,
    ):
        self.user_id = user_id
        self.command = command
        self.services = services
        self.access_token = access_token
        self.token_expires_at = token_expires_at
        self.last_used: float = time.monotonic()
        self._session: ClientSession | None = None
        self._exit_stack: AsyncExitStack | None = None

    async def start(self) -> None:
        """Start the gws MCP subprocess and initialize the session."""
        self._exit_stack = AsyncExitStack()
        env = {
            **os.environ,
            "GOOGLE_WORKSPACE_CLI_TOKEN": self.access_token,
        }
        params = StdioServerParameters(
            command=self.command,
            args=["mcp", "-s", self.services],
            env=env,
        )
        async with asyncio.timeout(_STARTUP_TIMEOUT):
            read_stream, write_stream = await self._exit_stack.enter_async_context(
                stdio_client(params)
            )
            self._session = await self._exit_stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )
            await self._session.initialize()

    async def stop(self) -> None:
        """Stop the gws subprocess."""
        if self._exit_stack:
            await self._exit_stack.aclose()
            self._exit_stack = None
            self._session = None

    async def call_tool(self, tool_name: str, arguments: dict) -> str:
        """Call a tool on this user's gws session."""
        if not self._session:
            raise RuntimeError("gws instance not started")
        self.touch()
        arguments = _coerce_arguments(arguments)
        result = await self._session.call_tool(name=tool_name, arguments=arguments)
        texts = []
        for c in result.content:
            if hasattr(c, "text"):
                texts.append(c.text)
        if result.isError:
            return f"Error: {' '.join(texts)}" if texts else "Error: unknown"
        return "\n".join(texts) if texts else ""

    async def discover_tools(self) -> list[dict]:
        """Discover tools and return them in OpenAI format."""
        if not self._session:
            raise RuntimeError("gws instance not started")
        result = await self._session.list_tools()
        tools = []
        for tool in result.tools:
            if not _VALID_TOOL_NAME.match(tool.name):
                continue
            if tool.name.lower().startswith(_DESTRUCTIVE_PREFIXES):
                logger.warning("Blocking destructive gws tool: %s", tool.name)
                continue
            prefixed = f"mcp__gws__{tool.name}"
            tools.append(_mcp_tool_to_openai(prefixed, tool))
        return tools

    def touch(self) -> None:
        """Update last-used timestamp."""
        self.last_used = time.monotonic()

    def token_expiring_soon(self) -> bool:
        """Check if the access token expires within the refresh buffer."""
        if self.token_expires_at is None:
            return False
        return datetime.now(timezone.utc) >= (
            self.token_expires_at - timedelta(seconds=_TOKEN_REFRESH_BUFFER)
        )

    def update_token(self, access_token: str, expires_at: datetime | None) -> None:
        """Update the stored token (requires restart to take effect)."""
        self.access_token = access_token
        self.token_expires_at = expires_at


class UserMCPPool:
    """Manages per-user gws MCP server instances.

    Each user who has connected Google gets their own gws subprocess,
    started lazily on first tool call and cleaned up after idle timeout.
    """

    def __init__(
        self,
        token_store: GoogleTokenStore,
        google_client_id: str,
        google_client_secret: str,
        google_client: httpx.AsyncClient,
        gws_command: str = "gws",
        gws_services: str = "calendar",
    ):
        self._token_store = token_store
        self._google_client_id = google_client_id
        self._google_client_secret = google_client_secret
        self._google_client = google_client
        self._gws_command = gws_command
        self._gws_services = gws_services

        self._instances: dict[int, _UserMCPInstance] = {}
        self._locks: dict[int, asyncio.Lock] = {}
        self._tool_defs: list[dict] | None = None
        self._cleanup_task: asyncio.Task | None = None

    # --- Lifecycle ---

    async def start(self) -> None:
        """Start the cleanup timer. Does NOT start any gws instances."""
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def stop(self) -> None:
        """Stop all user instances and cancel cleanup."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        for inst in list(self._instances.values()):
            await inst.stop()
        self._instances.clear()
        self._locks.clear()
        logger.info("UserMCPPool: all instances stopped")

    # --- Public API ---

    async def has_google_tokens(self, user_id: int) -> bool:
        """Check if user has stored Google refresh token."""
        return await self._token_store.has_tokens(user_id)

    async def get_openai_tools(self, user_id: int) -> list[dict]:
        """Return gws tools in OpenAI format if user has Google connected.

        Returns empty list if user has no tokens (graceful degradation).
        Tools are discovered once and cached.
        """
        if not await self._token_store.has_tokens(user_id):
            return []
        if self._tool_defs is not None:
            return self._tool_defs
        # Force-start an instance to discover tools
        try:
            await self._ensure_instance(user_id)
        except Exception:
            logger.exception(
                "Failed to start gws for tool discovery (user %d)", user_id
            )
            return []
        return self._tool_defs or []

    def is_gws_tool(self, name: str) -> bool:
        """Check if tool name is a gws MCP tool."""
        return name.startswith("mcp__gws__")

    async def call_tool(self, user_id: int, prefixed_name: str, arguments: dict) -> str:
        """Route a gws tool call to the correct user's instance."""
        inst = await self._ensure_instance(user_id)
        # Strip mcp__gws__ prefix to get the original tool name
        tool_name = prefixed_name.split("__", 2)[2]
        result = await inst.call_tool(tool_name, arguments)
        if len(result) > _MAX_RESULT_SIZE:
            result = result[:_MAX_RESULT_SIZE] + "\n...[truncated]"
        return result

    # --- Internal ---

    def _get_lock(self, user_id: int) -> asyncio.Lock:
        """Get or create a per-user lock."""
        if user_id not in self._locks:
            self._locks[user_id] = asyncio.Lock()
        return self._locks[user_id]

    async def _ensure_instance(self, user_id: int) -> _UserMCPInstance:
        """Get or create a gws MCP instance for this user."""
        async with self._get_lock(user_id):
            if user_id in self._instances:
                inst = self._instances[user_id]
                inst.touch()
                if inst.token_expiring_soon():
                    await self._refresh_and_restart(inst, user_id)
                return inst
            return await self._start_instance(user_id)

    async def _start_instance(self, user_id: int) -> _UserMCPInstance:
        """Start a new gws process for user (caller must hold lock)."""
        tokens = await self._token_store.get_tokens(user_id)
        if not tokens:
            raise ValueError(f"No Google tokens for user {user_id}")

        access_token = tokens["access_token"]
        expires_at = tokens["token_expiry"]

        # Refresh if expired or about to expire
        if self._is_expired(expires_at):
            access_token, expires_at = await self._refresh_token(
                user_id, tokens["refresh_token"]
            )

        inst = _UserMCPInstance(
            user_id=user_id,
            command=self._gws_command,
            services=self._gws_services,
            access_token=access_token,
            token_expires_at=expires_at,
        )
        await inst.start()

        # Discover tools once from the first instance
        if self._tool_defs is None:
            self._tool_defs = await inst.discover_tools()
            logger.info(
                "gws tool discovery: %d tools available",
                len(self._tool_defs),
            )

        self._instances[user_id] = inst
        logger.info("Started gws instance for user %d", user_id)
        return inst

    async def _refresh_and_restart(self, inst: _UserMCPInstance, user_id: int) -> None:
        """Refresh token and restart gws process with new token."""
        tokens = await self._token_store.get_tokens(user_id)
        if not tokens:
            raise ValueError(f"No Google tokens for user {user_id}")
        try:
            new_access, new_expiry = await self._refresh_token(
                user_id, tokens["refresh_token"]
            )
        except Exception:
            logger.exception(
                "Token refresh failed for user %d, removing instance", user_id
            )
            await inst.stop()
            self._instances.pop(user_id, None)
            # Delete revoked tokens so user must re-authenticate
            await self._token_store.delete_tokens(user_id)
            raise
        await inst.stop()
        inst.update_token(new_access, new_expiry)
        await inst.start()
        logger.info("Restarted gws instance for user %d (token refreshed)", user_id)

    async def _refresh_token(
        self, user_id: int, refresh_token: str
    ) -> tuple[str, datetime]:
        """Exchange refresh_token for a new access_token via Google OAuth."""
        resp = await self._google_client.post(
            GOOGLE_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": self._google_client_id,
                "client_secret": self._google_client_secret,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        access_token = data["access_token"]
        expires_in = data.get("expires_in", 3600)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

        # Persist the refreshed token
        await self._token_store.upsert_tokens(
            user_id=user_id,
            refresh_token=refresh_token,
            access_token=access_token,
            token_expiry=expires_at,
        )
        return access_token, expires_at

    @staticmethod
    def _is_expired(expires_at: datetime | None) -> bool:
        """Check if a token is expired or about to expire."""
        if expires_at is None:
            return True
        return datetime.now(timezone.utc) >= (
            expires_at - timedelta(seconds=_TOKEN_REFRESH_BUFFER)
        )

    async def _cleanup_loop(self) -> None:
        """Periodically stop idle instances."""
        while True:
            await asyncio.sleep(60)
            now = time.monotonic()
            to_remove = []
            for uid, inst in self._instances.items():
                if now - inst.last_used > _IDLE_TIMEOUT:
                    to_remove.append(uid)
            for uid in to_remove:
                inst = self._instances.pop(uid)
                await inst.stop()
                self._locks.pop(uid, None)
                logger.info("Stopped idle gws instance for user %d", uid)
