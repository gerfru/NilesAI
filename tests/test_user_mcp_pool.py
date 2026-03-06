"""Tests for UserMCPPool (per-user gws MCP server instances)."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from niles.mcp.user_pool import UserMCPPool, _UserMCPInstance


class TestUserMCPPoolToolCheck:
    """Test tool name prefix matching."""

    def test_is_gws_tool_true(self):
        pool = UserMCPPool(
            token_store=AsyncMock(),
            google_client_id="cid",
            google_client_secret="cs",
            google_client=AsyncMock(),
        )
        assert pool.is_gws_tool("mcp__gws__calendar_events_list") is True
        assert pool.is_gws_tool("mcp__gws__calendar_calendars_get") is True

    def test_is_gws_tool_false(self):
        pool = UserMCPPool(
            token_store=AsyncMock(),
            google_client_id="cid",
            google_client_secret="cs",
            google_client=AsyncMock(),
        )
        assert pool.is_gws_tool("mcp__weather__get_current_weather") is False
        assert pool.is_gws_tool("find_event") is False
        assert pool.is_gws_tool("") is False


class TestUserMCPPoolNoTokens:
    """Test graceful degradation when user has no tokens."""

    async def test_no_tools_without_tokens(self):
        token_store = AsyncMock()
        token_store.has_tokens.return_value = False

        pool = UserMCPPool(
            token_store=token_store,
            google_client_id="cid",
            google_client_secret="cs",
            google_client=AsyncMock(),
        )
        tools = await pool.get_openai_tools(user_id=42)
        assert tools == []

    async def test_has_google_tokens_delegates(self):
        token_store = AsyncMock()
        token_store.has_tokens.return_value = True

        pool = UserMCPPool(
            token_store=token_store,
            google_client_id="cid",
            google_client_secret="cs",
            google_client=AsyncMock(),
        )
        assert await pool.has_google_tokens(42) is True
        token_store.has_tokens.assert_called_with(42)


class TestUserMCPPoolCallTool:
    """Test tool call routing."""

    async def test_call_tool_raises_without_tokens(self):
        token_store = AsyncMock()
        token_store.get_tokens.return_value = None

        pool = UserMCPPool(
            token_store=token_store,
            google_client_id="cid",
            google_client_secret="cs",
            google_client=AsyncMock(),
        )
        with pytest.raises(ValueError, match="No Google tokens"):
            await pool.call_tool(42, "mcp__gws__calendar_events_list", {})


class TestUserMCPInstanceTokenExpiry:
    """Test token expiry detection."""

    def test_not_expiring_soon(self):
        inst = _UserMCPInstance(
            user_id=1,
            command="gws",
            services="calendar",
            access_token="at",
            token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        assert inst.token_expiring_soon() is False

    def test_expiring_soon(self):
        inst = _UserMCPInstance(
            user_id=1,
            command="gws",
            services="calendar",
            access_token="at",
            token_expires_at=datetime.now(timezone.utc) + timedelta(minutes=2),
        )
        assert inst.token_expiring_soon() is True

    def test_already_expired(self):
        inst = _UserMCPInstance(
            user_id=1,
            command="gws",
            services="calendar",
            access_token="at",
            token_expires_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
        assert inst.token_expiring_soon() is True

    def test_none_expiry_not_expiring(self):
        inst = _UserMCPInstance(
            user_id=1,
            command="gws",
            services="calendar",
            access_token="at",
            token_expires_at=None,
        )
        assert inst.token_expiring_soon() is False

    def test_touch_updates_last_used(self):
        inst = _UserMCPInstance(
            user_id=1,
            command="gws",
            services="calendar",
            access_token="at",
            token_expires_at=None,
        )
        old = inst.last_used
        import time

        time.sleep(0.01)
        inst.touch()
        assert inst.last_used > old

    def test_update_token(self):
        inst = _UserMCPInstance(
            user_id=1,
            command="gws",
            services="calendar",
            access_token="old",
            token_expires_at=None,
        )
        new_expiry = datetime.now(timezone.utc) + timedelta(hours=1)
        inst.update_token("new-token", new_expiry)
        assert inst.access_token == "new-token"
        assert inst.token_expires_at == new_expiry


class TestUserMCPPoolTokenRefresh:
    """Test OAuth token refresh logic."""

    async def test_refresh_token_stores_result(self):
        token_store = AsyncMock()
        token_store.get_tokens.return_value = {
            "refresh_token": "rt",
            "access_token": "old-at",
            "token_expiry": datetime.now(timezone.utc) - timedelta(hours=1),
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "new-at",
            "expires_in": 3600,
        }
        mock_response.raise_for_status = MagicMock()

        google_client = AsyncMock()
        google_client.post.return_value = mock_response

        pool = UserMCPPool(
            token_store=token_store,
            google_client_id="cid",
            google_client_secret="cs",
            google_client=google_client,
        )

        access_token, expires_at = await pool._refresh_token(42, "rt")

        assert access_token == "new-at"
        assert expires_at > datetime.now(timezone.utc)
        token_store.upsert_tokens.assert_called_once()

    async def test_is_expired_true_when_none(self):
        assert UserMCPPool._is_expired(None) is True

    async def test_is_expired_true_when_past(self):
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        assert UserMCPPool._is_expired(past) is True

    async def test_is_expired_false_when_future(self):
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        assert UserMCPPool._is_expired(future) is False


class TestMCPToolDispatch:
    """Test that handle_mcp_tool routes gws tools correctly."""

    async def test_gws_tool_dispatched_to_user_pool(self):
        from niles.agent.tools.mcp import handle_mcp_tool

        user_pool = AsyncMock()
        user_pool.is_gws_tool.return_value = True
        user_pool.call_tool.return_value = '{"events": []}'

        ctx = MagicMock()
        ctx.mcp = MagicMock()
        ctx.mcp.is_mcp_tool.return_value = False
        ctx.user_mcp_pool = user_pool
        ctx.user_id = 42

        result = await handle_mcp_tool("mcp__gws__calendar_events_list", {}, ctx)
        assert result == {"result": '{"events": []}'}
        user_pool.call_tool.assert_called_once_with(
            42, "mcp__gws__calendar_events_list", {}
        )

    async def test_gws_tool_without_user_id_returns_error(self):
        from niles.agent.tools.mcp import handle_mcp_tool

        user_pool = MagicMock()
        user_pool.is_gws_tool.return_value = True

        ctx = MagicMock()
        ctx.mcp = MagicMock()
        ctx.mcp.is_mcp_tool.return_value = False
        ctx.user_mcp_pool = user_pool
        ctx.user_id = None

        result = await handle_mcp_tool("mcp__gws__calendar_events_list", {}, ctx)
        assert "error" in result
        assert "Google" in result["error"]

    async def test_global_mcp_takes_priority(self):
        from niles.agent.tools.mcp import handle_mcp_tool

        ctx = MagicMock()
        ctx.mcp = AsyncMock()
        ctx.mcp.is_mcp_tool.return_value = True
        ctx.mcp.call_tool.return_value = "weather data"
        ctx.user_mcp_pool = MagicMock()

        result = await handle_mcp_tool("mcp__weather__get_forecast", {}, ctx)
        assert result == {"result": "weather data"}
        ctx.user_mcp_pool.is_gws_tool.assert_not_called()
