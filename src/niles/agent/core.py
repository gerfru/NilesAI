# SPDX-License-Identifier: AGPL-3.0-only
"""Niles agent core – event processing with LLM tool-call loop."""

import asyncio
import json
import logging
import time
from types import SimpleNamespace

import httpx
from openai import AsyncOpenAI, OpenAIError

from ..actions.calendar import CalendarAction
from ..actions.contacts import ContactsAction
from ..actions.signal import SignalAction
from ..actions.whatsapp import WhatsAppAction
from ..config import Settings
from ..mcp.client import MCPManager
from ..memory.history import ConversationHistory
from ..memory.store import MemoryStore
from ..metrics import LLM_DURATION, LLM_TOKENS, TOOL_CALLS
from ..redaction import redact_tool_args
from ..signal_store import SignalMessageStore
from ..sync.manager import CalendarSourceManager
from ..user_store import UserStore
from ..vikunja_store import VikunjaCredentialStore
from ..whatsapp_store import WhatsAppSessionStore
from .context import ContextBuilder
from .prompts import load_system_prompt
from .text_tool_parser import (
    is_rejected_tool_call,
    synthetic_tool_call,
    try_parse_text_tool_call,
)
from .tool_defs import MAX_TOOL_ROUNDS, TOOLS
from .tools import TOOL_REGISTRY, ToolContext
from .tools.mcp import handle_mcp_tool

logger = logging.getLogger(__name__)


class NilesAgent:
    """Thin orchestrator: LLM call loop + streaming pipeline.

    Context assembly is delegated to ``ContextBuilder`` (context.py).
    Text tool-call parsing is delegated to ``text_tool_parser`` module.
    """

    # Backward-compatible static method wrapper for synthetic tool calls.
    _synthetic_tool_call = staticmethod(synthetic_tool_call)

    @staticmethod
    def _try_parse_text_tool_call(
        text: str,
        known_tools: frozenset[str] | None = None,
    ) -> dict | None:
        """Detect a tool call embedded as JSON in the LLM text response.

        When *known_tools* is ``None``, defaults to the module-level TOOLS list.
        """
        if known_tools is None:
            known_tools = NilesAgent._TOOL_NAMES
        return try_parse_text_tool_call(text, known_tools)

    def __init__(
        self,
        config: Settings,
        contacts: ContactsAction,
        whatsapp: WhatsAppAction,
        memory: MemoryStore,
        history: ConversationHistory,
        mcp_manager: MCPManager | None = None,
        calendar: CalendarAction | None = None,
        calendar_manager: CalendarSourceManager | None = None,
        wa_store: WhatsAppSessionStore | None = None,
        vikunja_store: VikunjaCredentialStore | None = None,
        signal: SignalAction | None = None,
        signal_store: SignalMessageStore | None = None,
        user_store: UserStore | None = None,
        http_client: httpx.AsyncClient | None = None,
    ):
        self.notion_retriever: object | None = None
        self._llm_lock = asyncio.Lock()
        self._OpenAI = AsyncOpenAI
        if config.langfuse_host and config.langfuse_public_key and config.langfuse_secret_key:
            try:
                import os as _os

                _os.environ.setdefault("LANGFUSE_HOST", config.langfuse_host)
                _os.environ.setdefault("LANGFUSE_PUBLIC_KEY", config.langfuse_public_key)
                _os.environ.setdefault("LANGFUSE_SECRET_KEY", config.langfuse_secret_key)
                from langfuse.openai import AsyncOpenAI as _TracedOpenAI  # type: ignore[import]

                self._OpenAI = _TracedOpenAI
                logger.info("LLM tracing enabled via Langfuse (%s)", config.langfuse_host)
            except ImportError:
                logger.warning("langfuse package not installed; LLM tracing disabled. Install: uv add langfuse")
        self.llm = self._OpenAI(base_url=config.llm_base_url, api_key="not-needed")
        self.model = config.llm_model
        self.llm_temperature_tools = config.llm_temperature_tools
        self.llm_temperature_chat = config.llm_temperature_chat
        self.llm_max_tokens = config.llm_max_tokens
        self._ctx = ContextBuilder(
            config=config,
            contacts=contacts,
            whatsapp=whatsapp,
            memory=memory,
            history=history,
            base_prompt=load_system_prompt(),
            mcp=mcp_manager,
            calendar=calendar,
            calendar_manager=calendar_manager,
            wa_store=wa_store,
            vikunja_store=vikunja_store,
            signal=signal,
            signal_store=signal_store,
            user_store=user_store,
            http_client=http_client,
        )

    async def update_llm(self, *, base_url: str | None = None, model: str | None = None) -> None:
        """Atomically update LLM client and/or model under lock.

        Prevents concurrent LLM calls from seeing inconsistent state
        when settings are hot-reloaded.
        """
        async with self._llm_lock:
            if base_url is not None:
                self.llm = self._OpenAI(base_url=base_url, api_key="not-needed")
            if model is not None:
                self.model = model

    async def _llm_create(self, **kwargs):
        """Call self.llm.chat.completions.create with retry on transient errors.

        Retries ConnectError / TimeoutException (Ollama restart, momentary lag)
        twice with short backoff.  Auth / rate-limit errors raise immediately.
        """
        delays = (0.5, 2.0)
        for i, delay in enumerate((*delays, None)):
            try:
                return await self.llm.chat.completions.create(**kwargs)
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                if delay is None:
                    raise
                logger.warning("LLM call failed (attempt %d), retrying in %.1fs: %s", i + 1, delay, e)
                await asyncio.sleep(delay)

    def __getattr__(self, name: str):
        """Delegate attribute access to ContextBuilder for backward compat.

        Only called when normal attribute lookup fails, so ``self.llm``
        and ``self.model`` are resolved directly with zero overhead.
        """
        if name == "_ctx":
            raise AttributeError("_ctx not yet initialized")
        try:
            return getattr(self._ctx, name)
        except AttributeError:
            raise AttributeError(  # noqa: B904
                f"'{type(self).__name__}' has no attribute '{name}'"
            )

    _TOOL_NAMES = frozenset(t["function"]["name"] for t in TOOLS)

    async def _prepare_messages(self, event: dict) -> tuple[str, list[dict], list]:
        """Delegate to ContextBuilder.prepare_messages."""
        return await self._ctx.prepare_messages(event, TOOLS)

    async def _handle_phone_choice(self, chat_id: str, content: str) -> str | None:
        """Delegate to ContextBuilder.handle_phone_choice."""
        return await self._ctx.handle_phone_choice(chat_id, content)

    async def _handle_interception(
        self,
        chat_id: str,
        content: str,
        history_content: str,
    ) -> str | None:
        """Check for pending phone choice or confirmation and save to history.

        Returns the reply text if intercepted, or None to proceed normally.
        """
        for handler in (
            self._handle_phone_choice,
            self._ctx.handle_confirmation,
        ):
            reply = await handler(chat_id, content)
            if reply is not None:
                await self.history.add_message(chat_id, "user", history_content)
                await self.history.add_message(chat_id, "assistant", reply)
                return reply
        return None

    async def _execute_and_check(
        self,
        tool_call,
        chat_id: str,
        messages: list,
        history_content: str,
    ) -> str | None:
        """Execute a tool call, record metrics, and check for bypass signals.

        If the tool result contains ``choose_phone`` or ``confirm``, saves to
        history and returns the bypass text.  Otherwise appends the tool
        result to *messages* and returns ``None``.
        """
        name = tool_call.function.name
        result = await self._execute_tool_call(tool_call, chat_id)

        _success = result.get("error") is None if isinstance(result, dict) else True
        TOOL_CALLS.labels(tool_name=name, success=str(_success).lower()).inc()
        # Redact: tool results may contain PII (message text, phone numbers, names).
        if isinstance(result, dict):
            logger.info("Tool result [%s]: keys=%s", tool_call.id, sorted(result))
            logger.debug("Tool result [%s]: %s", tool_call.id, redact_tool_args(result))
        else:
            logger.info("Tool result [%s]: %d chars", tool_call.id, len(str(result)))

        if isinstance(result, dict):
            for key in ("choose_phone", "confirm"):
                if key in result:
                    text = result[key]
                    await self.history.add_message(chat_id, "user", history_content)
                    await self.history.add_message(chat_id, "assistant", text)
                    return text

        messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps(result, ensure_ascii=False),
            }
        )
        return None

    async def process_event_stream(self, event: dict):
        """Async generator: yields status updates + streamed text chunks.

        Every LLM call uses stream=True so even simple queries (no tool calls)
        are delivered word-by-word.  When the LLM requests tool calls, the
        streamed deltas are accumulated, tools executed, and the loop repeats.

        Yields dicts with:
          {"type": "status", "text": "find_contact..."}
          {"type": "chunk",  "text": "partial text"}
          {"type": "done"}
        """
        chat_id = event["from"]
        # Store original user message in history (without injected Notion context)
        _history_content = event.get("metadata", {}).get("original_message") or event["content"]

        # Intercept pending phone choice / confirmation (bypass LLM entirely)
        reply = await self._handle_interception(chat_id, event["content"], _history_content)
        if reply is not None:
            yield {"type": "chunk", "text": reply}
            yield {"type": "done"}
            return

        chat_id, messages, all_tools = await self._prepare_messages(event)
        _temperature = self.llm_temperature_chat if not all_tools else self.llm_temperature_tools

        # Force search tool on first round when Recherche-Modus is active
        _web_search = event.get("metadata", {}).get("web_search", False)
        _search_tool = "mcp__searxng__web_search"
        _tool_names = [t["function"]["name"] for t in all_tools]
        _force_search = _web_search and _search_tool in _tool_names

        for _round in range(MAX_TOOL_ROUNDS):
            if _force_search and _round == 0:
                _tool_choice: object = {
                    "type": "function",
                    "function": {"name": _search_tool},
                }
            else:
                _tool_choice = "auto" if all_tools else None

            try:
                _llm_start = time.monotonic()
                stream = await self._llm_create(
                    model=self.model,
                    messages=messages,
                    tools=all_tools or None,
                    tool_choice=_tool_choice,
                    temperature=_temperature,
                    max_tokens=self.llm_max_tokens,
                    stream=True,
                    stream_options={"include_usage": True},
                )
            except (httpx.HTTPError, OpenAIError) as e:
                LLM_DURATION.observe(time.monotonic() - _llm_start)
                logger.error("LLM call failed: %s", e)
                yield {
                    "type": "chunk",
                    "text": "Entschuldigung, ich konnte die Anfrage nicht verarbeiten.",
                }
                yield {"type": "done"}
                return

            # Consume the stream, accumulating text content and tool-call deltas
            full_content = ""
            tool_calls_by_idx: dict[int, dict] = {}
            finish_reason = None
            # Buffer responses that look like JSON tool calls instead of
            # streaming them — avoids showing raw JSON to the user.
            _buffering = False

            try:
                async for chunk in stream:
                    # Final chunk with usage data has empty choices
                    if not chunk.choices:
                        if chunk.usage:
                            LLM_TOKENS.labels(type="prompt").inc(chunk.usage.prompt_tokens)
                            LLM_TOKENS.labels(type="completion").inc(chunk.usage.completion_tokens)
                        continue
                    choice = chunk.choices[0]
                    finish_reason = choice.finish_reason or finish_reason

                    if choice.delta.content:
                        full_content += choice.delta.content
                        # If the first content looks like JSON or a code-fenced
                        # tool call, buffer it.  Single backticks (inline code)
                        # are NOT buffered — only triple-backtick fences or
                        # bare '{'.
                        stripped = full_content.lstrip()
                        if not _buffering and (stripped.startswith("{") or stripped.startswith("```")):
                            _buffering = True
                        if not _buffering:
                            yield {"type": "chunk", "text": choice.delta.content}

                    if choice.delta.tool_calls:
                        for tc_delta in choice.delta.tool_calls:
                            idx = tc_delta.index
                            if idx not in tool_calls_by_idx:
                                tool_calls_by_idx[idx] = {
                                    "id": "",
                                    "name": "",
                                    "arguments": "",
                                }
                            if tc_delta.id:
                                tool_calls_by_idx[idx]["id"] = tc_delta.id
                            if tc_delta.function:
                                if tc_delta.function.name:
                                    tool_calls_by_idx[idx]["name"] += tc_delta.function.name
                                if tc_delta.function.arguments:
                                    tool_calls_by_idx[idx]["arguments"] += tc_delta.function.arguments
            finally:
                LLM_DURATION.observe(time.monotonic() - _llm_start)

            # No tool calls → check for text-based tool call fallback
            if finish_reason != "tool_calls" or not tool_calls_by_idx:
                _all_names = frozenset(t["function"]["name"] for t in all_tools)
                parsed = self._try_parse_text_tool_call(full_content, _all_names) if full_content else None
                if parsed:
                    logger.info("Detected text-based tool call (stream): %s", parsed["name"])
                    tc_dict, _ = self._synthetic_tool_call(parsed)
                    tool_calls_by_idx = {0: tc_dict}
                    full_content = ""  # Don't pass JSON as assistant content
                    # Don't save or return — fall through to tool execution below
                else:
                    # Flush buffered content that turned out not to be a tool call
                    if _buffering and full_content:
                        rejected_name = is_rejected_tool_call(full_content)
                        if rejected_name:
                            logger.info(
                                "Suppressed rejected tool call: %s",
                                rejected_name,
                            )
                            full_content = (
                                "Ich kann diese Anfrage mit den aktuell "
                                "verfügbaren Funktionen nicht beantworten. "
                                "Bitte aktiviere den Recherche-Modus."
                            )
                        yield {"type": "chunk", "text": full_content}
                    if full_content:
                        await self.history.add_message(chat_id, "user", _history_content)
                        await self.history.add_message(chat_id, "assistant", full_content)
                    else:
                        logger.warning(
                            "LLM returned empty streaming response for event: %s",
                            event.get("content", "")[:100],
                        )
                        yield {
                            "type": "chunk",
                            "text": "Entschuldigung, ich habe keine Antwort erhalten.",
                        }
                    yield {"type": "done"}
                    return

            # Tool calls detected → build assistant message and execute tools
            assistant_msg = {
                "role": "assistant",
                "content": full_content or None,
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {"name": tc["name"], "arguments": tc["arguments"]},
                    }
                    for tc in (tool_calls_by_idx[i] for i in sorted(tool_calls_by_idx))
                ],
            }
            messages.append(assistant_msg)

            for tc_dict in assistant_msg["tool_calls"]:
                yield {"type": "status", "text": f"{tc_dict['function']['name']}..."}
                tool_call = SimpleNamespace(
                    id=tc_dict["id"],
                    function=SimpleNamespace(
                        name=tc_dict["function"]["name"],
                        arguments=tc_dict["function"]["arguments"],
                    ),
                )
                bypass = await self._execute_and_check(
                    tool_call,
                    chat_id,
                    messages,
                    _history_content,
                )
                if bypass is not None:
                    yield {"type": "chunk", "text": bypass}
                    yield {"type": "done"}
                    return
        else:
            yield {
                "type": "chunk",
                "text": "Ich konnte die Anfrage nicht abschliessen.",
            }

        yield {"type": "done"}

    async def process_event(self, event: dict) -> str:
        """
        Main entry point for all events.

        Args:
            event: {"type": str, "from": str, "content": str, "metadata": dict}

        Returns:
            Response text
        """
        chat_id = event["from"]
        # Store original user message in history (without injected Notion context)
        _history_content = event.get("metadata", {}).get("original_message") or event["content"]

        # Intercept pending phone choice / confirmation (bypass LLM entirely)
        reply = await self._handle_interception(chat_id, event["content"], _history_content)
        if reply is not None:
            return reply

        chat_id, messages, all_tools = await self._prepare_messages(event)
        _temperature = self.llm_temperature_chat if not all_tools else self.llm_temperature_tools

        # Force search tool on first round when Recherche-Modus is active
        _web_search = event.get("metadata", {}).get("web_search", False)
        _search_tool = "mcp__searxng__web_search"
        _force_search = _web_search and any(t["function"]["name"] == _search_tool for t in all_tools)

        # Tool-call loop: LLM may request multiple rounds of tool calls
        for _round in range(MAX_TOOL_ROUNDS):
            if _force_search and _round == 0:
                _tool_choice: object = {
                    "type": "function",
                    "function": {"name": _search_tool},
                }
            else:
                _tool_choice = "auto" if all_tools else None

            try:
                _llm_start = time.monotonic()
                response = await self._llm_create(
                    model=self.model,
                    messages=messages,
                    tools=all_tools or None,
                    tool_choice=_tool_choice,
                    temperature=_temperature,
                    max_tokens=self.llm_max_tokens,
                )
                LLM_DURATION.observe(time.monotonic() - _llm_start)
            except (httpx.HTTPError, OpenAIError) as e:
                LLM_DURATION.observe(time.monotonic() - _llm_start)
                logger.error("LLM call failed: %s", e)
                return "Entschuldigung, ich konnte die Anfrage nicht verarbeiten."

            choice = response.choices[0]

            # Record token usage if available
            if response.usage:
                LLM_TOKENS.labels(type="prompt").inc(response.usage.prompt_tokens)
                LLM_TOKENS.labels(type="completion").inc(response.usage.completion_tokens)

            # No tool calls – check for text-based tool call fallback
            if choice.finish_reason != "tool_calls" or not choice.message.tool_calls:
                content = choice.message.content or ""
                _all_names = frozenset(t["function"]["name"] for t in all_tools)
                parsed = self._try_parse_text_tool_call(content, _all_names) if content else None
                if parsed:
                    logger.info("Detected text-based tool call: %s", parsed["name"])
                    tc_dict, assistant_msg = self._synthetic_tool_call(parsed)
                    messages.append(assistant_msg)
                    tc = SimpleNamespace(
                        id=tc_dict["id"],
                        function=SimpleNamespace(
                            name=tc_dict["name"],
                            arguments=tc_dict["arguments"],
                        ),
                    )
                    bypass = await self._execute_and_check(
                        tc,
                        chat_id,
                        messages,
                        _history_content,
                    )
                    if bypass is not None:
                        return bypass
                    continue  # Next LLM round to generate natural language response

                # Suppress raw JSON for unavailable tools
                if content:
                    rejected_name = is_rejected_tool_call(content)
                    if rejected_name:
                        logger.info(
                            "Suppressed rejected tool call: %s",
                            rejected_name,
                        )
                        content = (
                            "Ich kann diese Anfrage mit den aktuell "
                            "verfügbaren Funktionen nicht beantworten. "
                            "Bitte aktiviere den Recherche-Modus."
                        )

                if not content:
                    logger.warning(
                        "LLM returned empty response for event: %s",
                        event.get("content", "")[:100],
                    )
                # Save both messages together to avoid orphaned records
                if content:
                    await self.history.add_message(chat_id, "user", _history_content)
                    await self.history.add_message(chat_id, "assistant", content)
                return content

            # Append assistant message with tool calls (serialize to dict)
            messages.append(choice.message.model_dump(exclude_unset=True))

            # Execute each tool call and append results
            for tool_call in choice.message.tool_calls:
                bypass = await self._execute_and_check(
                    tool_call,
                    chat_id,
                    messages,
                    _history_content,
                )
                if bypass is not None:
                    return bypass

        logger.warning("Max tool rounds reached")
        return "Ich konnte die Anfrage nicht abschließen."

    def _tool_context(self, user_id: int | None = None) -> ToolContext:
        """Build a ToolContext from the agent's dependencies.

        Uses ``self.X`` (not ``self._ctx.X``) for data attributes so that
        tests can override them on the agent instance directly.
        """
        return ToolContext(
            config=self.config,
            contacts=self.contacts,
            whatsapp=self.whatsapp,
            signal=self.signal,
            signal_store=self.signal_store,
            memory=self.memory,
            calendar=self.calendar,
            calendar_manager=self.calendar_manager,
            vikunja_store=self.vikunja_store,
            wa_store=self.wa_store,
            mcp=self.mcp,
            user_id=user_id,
            resolve_contact_phone=self._resolve_contact_phone,
            resolve_wa_instance=self._resolve_wa_instance,
            resolve_vikunja=self._resolve_vikunja_tasks,
            get_own_phone_number=self._get_own_phone_number,
            pending_phone_choices=self._pending_phone_choices,
            pending_confirmations=self._pending_confirmations,
            notion_retriever=getattr(self, "notion_retriever", None),
        )

    async def _execute_tool_call(self, tool_call, chat_id: str = "") -> dict:
        """Execute a single tool call and return the result."""
        name = tool_call.function.name
        try:
            args = json.loads(tool_call.function.arguments)
        except json.JSONDecodeError:
            TOOL_CALLS.labels(tool_name=name, success="false").inc()
            return {"error": "Invalid arguments"}

        # Redact: argument values may contain PII (recipients, message text, names).
        logger.info(
            "Tool call [%s]: %s(keys=%s)",
            tool_call.id,
            name,
            sorted(args) if isinstance(args, dict) else "<non-dict>",
        )
        logger.debug("Tool call args [%s]: %s", tool_call.id, redact_tool_args(args))

        # Resolve user_id for per-user MCP tool routing
        user_id = await self._ctx.resolve_user_id(chat_id) if chat_id else None
        ctx = self._tool_context(user_id=user_id)

        # Registry lookup for built-in tools
        handler = TOOL_REGISTRY.get(name)
        if handler:
            try:
                return await handler(args, chat_id, ctx)
            except KeyError as exc:
                logger.warning("Missing required argument in %s: %s", name, exc)
                return {"error": f"Missing required argument: {exc}"}

        # MCP fallback for tools not in the registry
        return await handle_mcp_tool(name, args, ctx)
