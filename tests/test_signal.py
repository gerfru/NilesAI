"""Tests for Signal integration (action, listener, agent tools)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from niles.actions.signal import SignalAction
from niles.config import Settings
from niles.sources.signal import (
    _handle_envelope,
    _record_sent,
    _sent_texts,
    _was_echo,
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
            signal_phone_number="+436601234567",
        )
        return SignalAction(config)

    @pytest.mark.asyncio
    async def test_send_message_success(self):
        action = self._make_action()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"timestamp": "123"}
        mock_response.raise_for_status = MagicMock()

        with patch("niles.actions.signal.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            result = await action.send_message(to="+4369912345678", text="Hello")

        assert result == {"timestamp": "123"}
        mock_client.post.assert_called_once()
        call_kwargs = mock_client.post.call_args
        assert call_kwargs[1]["json"]["recipients"] == ["+4369912345678"]
        assert call_kwargs[1]["json"]["message"] == "Hello"

    @pytest.mark.asyncio
    async def test_send_message_error(self):
        action = self._make_action()

        with patch("niles.actions.signal.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            import httpx

            mock_client.post = AsyncMock(
                side_effect=httpx.ConnectError("Connection refused")
            )
            mock_client_cls.return_value = mock_client

            result = await action.send_message(to="+4369912345678", text="Hello")

        assert "error" in result

    @pytest.mark.asyncio
    async def test_get_status_success(self):
        action = self._make_action()
        mock_response = MagicMock()
        mock_response.json.return_value = {"number": "+436601234567"}
        mock_response.raise_for_status = MagicMock()

        with patch("niles.actions.signal.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            result = await action.get_status()

        assert result == {"number": "+436601234567"}

    @pytest.mark.asyncio
    async def test_get_qr_link_returns_png(self):
        action = self._make_action()
        mock_response = MagicMock()
        mock_response.content = b"\x89PNG..."
        mock_response.headers = {"content-type": "image/png"}
        mock_response.raise_for_status = MagicMock()

        with patch("niles.actions.signal.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            result = await action.get_qr_link()

        assert result == b"\x89PNG..."


# --- Echo-loop guard tests ---


class TestEchoGuard:
    def setup_method(self):
        _sent_texts.clear()

    def test_record_and_detect(self):
        _record_sent("Hello from Niles")
        assert _was_echo("Hello from Niles") is True

    def test_not_echo(self):
        assert _was_echo("Some random message") is False

    def test_truncation(self):
        long_text = "A" * 300
        _record_sent(long_text)
        assert _was_echo(long_text) is True  # truncated key matches

    def teardown_method(self):
        _sent_texts.clear()


# --- WebSocket listener envelope handler tests ---


class TestHandleEnvelope:
    @pytest.fixture
    def app_state(self):
        settings = SimpleNamespace(signal_phone_number="+436601234567")
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
        _sent_texts.clear()
        app_state.agent.process_event = AsyncMock(return_value="Agent reply")
        data = {
            "envelope": {
                "source": "+436601234567",
                "syncMessage": {
                    "sentMessage": {
                        "message": "Hey Niles, was steht an?",
                        "destination": "+436601234567",
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
        _sent_texts.clear()

    @pytest.mark.asyncio
    async def test_self_chat_without_trigger_ignored(self, app_state):
        """Self-chat without trigger phrase is stored but not processed."""
        data = {
            "envelope": {
                "source": "+436601234567",
                "syncMessage": {
                    "sentMessage": {
                        "message": "Einkaufsliste fuer morgen",
                        "destination": "+436601234567",
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
        _sent_texts.clear()
        _record_sent("Niles hier: du hast 2 Termine")
        data = {
            "envelope": {
                "source": "+436601234567",
                "syncMessage": {
                    "sentMessage": {
                        "message": "Niles hier: du hast 2 Termine",
                        "destination": "+436601234567",
                    }
                },
            }
        }
        await _handle_envelope(app_state, data)
        # Should store but NOT process (echo guard)
        app_state.signal_store.store.assert_called_once()
        app_state.agent.process_event.assert_not_called()
        _sent_texts.clear()

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
