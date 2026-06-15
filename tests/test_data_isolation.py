"""Tests for cross-tenant data isolation (fail-closed contacts + chat resolution).

Covers the H1/H2 review findings: the contacts data layer must never run an
unscoped query, and Signal self-chats must resolve to the owner (admin) user
rather than falling through to user_id=None.
"""

from unittest.mock import AsyncMock

import pytest

from niles.actions.contacts import ContactsAction
from niles.agent.context import ContextBuilder
from niles.config import Settings


def _make_settings(**overrides):
    defaults = dict(_env_file=None, postgres_password="test", evolution_api_key="test-api-key")
    defaults.update(overrides)
    return Settings(**defaults)


def _make_context_builder(**overrides):
    defaults = dict(
        config=_make_settings(),
        contacts=AsyncMock(),
        whatsapp=AsyncMock(),
        memory=AsyncMock(),
        history=AsyncMock(),
        base_prompt="test prompt",
    )
    defaults.update(overrides)
    return ContextBuilder(**defaults)


class TestContactsFailClosed:
    """H1: find_by_name must not query across all users when user_id is missing."""

    @pytest.mark.asyncio
    async def test_none_user_id_returns_none_without_query(self):
        pool = AsyncMock()
        action = ContactsAction(pool)

        result = await action.find_by_name("Thomas", user_id=None)

        assert result is None
        pool.fetchrow.assert_not_called()

    @pytest.mark.asyncio
    async def test_scoped_query_includes_user_id(self):
        pool = AsyncMock()
        pool.fetchrow.return_value = None
        action = ContactsAction(pool)

        await action.find_by_name("Thomas", user_id=42)

        # user_id is passed as the final bind parameter of the scoped query
        args = pool.fetchrow.call_args.args
        assert 42 in args


class TestResolveUserId:
    """H2: chat_id → user_id resolution, failing closed when unknown."""

    @pytest.mark.asyncio
    async def test_web_user(self):
        ctx = _make_context_builder()
        assert await ctx.resolve_user_id("web-user-7") == 7

    @pytest.mark.asyncio
    async def test_signal_self_resolves_to_admin(self):
        user_store = AsyncMock()
        user_store.get_admin_user_id.return_value = 3
        ctx = _make_context_builder(user_store=user_store)

        assert await ctx.resolve_user_id("signal-self-4366012345") == 3
        user_store.get_admin_user_id.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_signal_self_without_user_store_fails_closed(self):
        ctx = _make_context_builder()  # no user_store
        assert await ctx.resolve_user_id("signal-self-4366012345") is None

    @pytest.mark.asyncio
    async def test_signal_self_without_admin_fails_closed(self):
        user_store = AsyncMock()
        user_store.get_admin_user_id.return_value = None
        ctx = _make_context_builder(user_store=user_store)
        assert await ctx.resolve_user_id("signal-self-4366012345") is None

    @pytest.mark.asyncio
    async def test_unknown_chat_id(self):
        ctx = _make_context_builder()
        assert await ctx.resolve_user_id("garbage") is None
