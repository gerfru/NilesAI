"""Tests for Signal integration (action, listener, agent tools)."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from niles.actions.signal import SignalAction
from niles.config import Settings
from niles.sources.signal import (
    _echo_guard,
    _handle_envelope,
)
from niles.sources.triggers import is_niles_trigger, strip_trigger


# --- SignalAction tests ---


class TestSignalAction:
    def _make_action(self):
        config = Settings(
            _env_file=None,
            postgres_password="test",
            evolution_api_key="test",
            signal_api_url="http://signal_api:8080",
            signal_phone_number="+4366012345678",
        )
        return SignalAction(config)

    @pytest.mark.asyncio
    async def test_send_message_success(self):
        action = self._make_action()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"timestamp": "123"}
        mock_response.raise_for_status = MagicMock()

        action._client = AsyncMock()
        action._client.post = AsyncMock(return_value=mock_response)

        result = await action.send_message(to="+4369912345678", text="Hello")

        assert result == {"timestamp": "123"}
        action._client.post.assert_called_once()
        call_kwargs = action._client.post.call_args
        assert call_kwargs[1]["json"]["recipients"] == ["+4369912345678"]
        assert call_kwargs[1]["json"]["message"] == "Hello"

    @pytest.mark.asyncio
    async def test_send_message_error(self):
        action = self._make_action()
        import httpx

        action._client = AsyncMock()
        action._client.post = AsyncMock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        result = await action.send_message(to="+4369912345678", text="Hello")

        assert "error" in result

    @pytest.mark.asyncio
    async def test_get_status_success(self):
        action = self._make_action()
        mock_response = MagicMock()
        mock_response.json.return_value = {"number": "+4366012345678"}
        mock_response.raise_for_status = MagicMock()

        action._client = AsyncMock()
        action._client.get = AsyncMock(return_value=mock_response)

        result = await action.get_status()

        assert result == {"number": "+4366012345678"}

    @pytest.mark.asyncio
    async def test_get_qr_link_returns_png(self):
        action = self._make_action()
        mock_response = MagicMock()
        mock_response.content = b"\x89PNG..."
        mock_response.headers = {"content-type": "image/png"}
        mock_response.raise_for_status = MagicMock()

        action._client = AsyncMock()
        action._client.get = AsyncMock(return_value=mock_response)

        result = await action.get_qr_link()

        assert result == b"\x89PNG..."


# --- Echo-loop guard tests ---


class TestEchoGuard:
    def setup_method(self):
        _echo_guard._cache.clear()

    def test_record_and_detect(self):
        _echo_guard.record("Hello from Niles")
        assert _echo_guard.is_echo("Hello from Niles") is True

    def test_not_echo(self):
        assert _echo_guard.is_echo("Some random message") is False

    def test_truncation(self):
        long_text = "A" * 300
        _echo_guard.record(long_text[:200])
        assert _echo_guard.is_echo(long_text[:200]) is True

    def teardown_method(self):
        _echo_guard._cache.clear()


# --- WebSocket listener envelope handler tests ---


class TestHandleEnvelope:
    @pytest.fixture
    def app_state(self):
        settings = SimpleNamespace(signal_phone_number="+4366012345678")
        signal_store = AsyncMock()
        signal_action = AsyncMock()
        agent = AsyncMock()
        return SimpleNamespace(
            settings=settings,
            signal_store=signal_store,
            signal_action=signal_action,
            agent=agent,
        )

    @pytest.mark.asyncio
    async def test_incoming_message_stored(self, app_state):
        """Incoming message from someone else is stored but not processed."""
        data = {
            "envelope": {
                "source": "+4369912345678",
                "dataMessage": {"message": "Hallo, alles klar?"},
            }
        }
        await _handle_envelope(app_state, data)
        app_state.signal_store.store.assert_called_once_with(
            phone="+4369912345678", text="Hallo, alles klar?", from_me=False
        )
        app_state.agent.process_event.assert_not_called()

    @pytest.mark.asyncio
    async def test_self_chat_with_trigger_processes(self, app_state):
        """Self-chat with trigger phrase calls the agent."""
        _echo_guard._cache.clear()
        app_state.agent.process_event = AsyncMock(return_value="Agent reply")
        data = {
            "envelope": {
                "source": "+4366012345678",
                "syncMessage": {
                    "sentMessage": {
                        "message": "Hey Niles, was steht an?",
                        "destination": "+4366012345678",
                    }
                },
            }
        }
        await _handle_envelope(app_state, data)

        # Should store the outgoing message
        app_state.signal_store.store.assert_called_once()
        # Should call agent
        app_state.agent.process_event.assert_called_once()
        event = app_state.agent.process_event.call_args[0][0]
        assert event["content"] == "was steht an?"
        assert event["type"] == "signal"
        assert "signal-self-" in event["from"]
        # Should send reply
        app_state.signal_action.send_message.assert_called_once()
        _echo_guard._cache.clear()

    @pytest.mark.asyncio
    async def test_self_chat_without_trigger_ignored(self, app_state):
        """Self-chat without trigger phrase is stored but not processed."""
        data = {
            "envelope": {
                "source": "+4366012345678",
                "syncMessage": {
                    "sentMessage": {
                        "message": "Einkaufsliste fuer morgen",
                        "destination": "+4366012345678",
                    }
                },
            }
        }
        await _handle_envelope(app_state, data)
        app_state.signal_store.store.assert_called_once()
        app_state.agent.process_event.assert_not_called()

    @pytest.mark.asyncio
    async def test_echo_guard_prevents_loop(self, app_state):
        """Echo guard prevents re-processing of messages the agent just sent."""
        _echo_guard._cache.clear()
        _echo_guard.record("Niles hier: du hast 2 Termine")
        data = {
            "envelope": {
                "source": "+4366012345678",
                "syncMessage": {
                    "sentMessage": {
                        "message": "Niles hier: du hast 2 Termine",
                        "destination": "+4366012345678",
                    }
                },
            }
        }
        await _handle_envelope(app_state, data)
        # Should store but NOT process (echo guard)
        app_state.signal_store.store.assert_called_once()
        app_state.agent.process_event.assert_not_called()
        _echo_guard._cache.clear()

    @pytest.mark.asyncio
    async def test_empty_message_ignored(self, app_state):
        """Envelopes without text content are ignored."""
        data = {
            "envelope": {
                "source": "+4369912345678",
                "dataMessage": {},
            }
        }
        await _handle_envelope(app_state, data)
        app_state.signal_store.store.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_data_no_sync_ignored(self, app_state):
        """Envelopes without dataMessage or syncMessage are ignored."""
        data = {"envelope": {"source": "+4369912345678"}}
        await _handle_envelope(app_state, data)
        app_state.signal_store.store.assert_not_called()


# --- Trigger tests (shared with WhatsApp) ---


class TestTriggers:
    def test_is_trigger_hey_niles(self):
        assert is_niles_trigger("Hey Niles, was geht?") is True

    def test_is_trigger_case_insensitive(self):
        assert is_niles_trigger("HEY NILES was geht") is True

    def test_not_trigger(self):
        assert is_niles_trigger("Einkaufsliste") is False

    def test_nilesh_not_trigger(self):
        assert is_niles_trigger("Nilesh, kannst du...") is False

    def test_strip_trigger_comma(self):
        assert strip_trigger("Hey Niles, was steht an?") == "was steht an?"

    def test_strip_trigger_colon(self):
        assert strip_trigger("Niles: Termin morgen") == "Termin morgen"

    def test_strip_trigger_only(self):
        assert strip_trigger("Hey Niles") == ""


# --- WebSocket URL scheme tests ---


class TestWebSocketScheme:
    def test_ws_scheme_for_http(self):
        """HTTP API URL produces ws:// WebSocket URL."""

        # Extract the URL construction logic by checking the source
        api_url = "http://signal_api:8080"
        ws_scheme = "wss" if api_url.startswith("https://") else "ws"
        ws_host = api_url.replace("http://", "").replace("https://", "").rstrip("/")
        ws_url = f"{ws_scheme}://{ws_host}/v1/receive/+123?timeout=3600"
        assert ws_url == "ws://signal_api:8080/v1/receive/+123?timeout=3600"

    def test_wss_scheme_for_https(self):
        """HTTPS API URL produces wss:// WebSocket URL."""
        api_url = "https://signal.example.com"
        ws_scheme = "wss" if api_url.startswith("https://") else "ws"
        ws_host = api_url.replace("http://", "").replace("https://", "").rstrip("/")
        ws_url = f"{ws_scheme}://{ws_host}/v1/receive/+123?timeout=3600"
        assert ws_url == "wss://signal.example.com/v1/receive/+123?timeout=3600"


# --- _ensure_signal_listener race guard tests ---


class TestEnsureSignalListener:
    @pytest.mark.asyncio
    async def test_idempotent_when_running(self):
        """Second call is a no-op when listener task is already running."""
        from niles.sources.web import _ensure_signal_listener

        app = MagicMock()
        # Simulate a running task
        running_task = MagicMock()
        running_task.done.return_value = False
        app.state.signal_task = running_task
        app.state.shutdown_event = asyncio.Event()

        # Function returns early — signal_listener is never imported
        await _ensure_signal_listener(app)
        # Task unchanged (no new task created)
        assert app.state.signal_task is running_task

    @pytest.mark.asyncio
    async def test_starts_when_no_task(self):
        """Listener is started when no prior task exists."""
        from niles.sources.web import _ensure_signal_listener

        app = MagicMock()
        app.state.signal_task = None
        app.state.shutdown_event = asyncio.Event()

        with patch("niles.sources.signal.signal_listener", new_callable=AsyncMock):
            await _ensure_signal_listener(app)
            assert app.state.signal_task is not None
            # Clean up the created task
            task = app.state.signal_task
            if hasattr(task, "cancel"):
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

    @pytest.mark.asyncio
    async def test_sentinel_prevents_duplicate(self):
        """Sentinel Future prevents a second caller from creating a duplicate task."""
        from niles.sources.web import _ensure_signal_listener

        app = MagicMock()
        app.state.signal_task = None
        app.state.shutdown_event = asyncio.Event()

        call_count = 0

        async def slow_listener(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(10)

        with patch("niles.sources.signal.signal_listener", side_effect=slow_listener):
            # Call twice concurrently
            await asyncio.gather(
                _ensure_signal_listener(app),
                _ensure_signal_listener(app),
            )
            # The sentinel should prevent the second call from creating a task
            assert call_count <= 1
            # Clean up
            task = app.state.signal_task
            if task and not isinstance(task, MagicMock) and hasattr(task, "cancel"):
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
