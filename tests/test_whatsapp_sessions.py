"""Tests for WhatsApp session management (per-user Evolution API instances)."""

import json
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from niles.config import Settings


VALID_TOKEN = "test-api-key"


def _make_settings(**overrides):
    defaults = dict(
        _env_file=None,
        postgres_password="test",
        evolution_api_key=VALID_TOKEN,
    )
    defaults.update(overrides)
    return Settings(**defaults)


class TestWhatsAppAction:
    """Test Evolution API client methods."""

    @pytest.fixture
    def action(self):
        from niles.actions.whatsapp import WhatsAppAction

        return WhatsAppAction(_make_settings())

    async def test_send_message_default_instance(self, action):
        """send_message without explicit instance uses the global one."""
        assert action.instance == "niles-whatsapp"

    async def test_send_message_custom_instance(self, action):
        """send_message with explicit instance parameter."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"status": "sent"}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        action._client = mock_client

        result = await action.send_message(
            to="436601234567",
            text="Hi",
            instance="niles-wa-5",
        )
        assert "error" not in result
        # Verify the URL includes the custom instance name
        call_url = mock_client.post.call_args[0][0]
        assert "niles-wa-5" in call_url

    async def test_fetch_messages(self, action):
        """fetch_messages calls Evolution API findMessages endpoint."""
        recent_ts = int(time.time()) - 3600  # 1 hour ago
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "messages": {
                "total": 1,
                "records": [
                    {
                        "key": {
                            "id": "MSG001",
                            "fromMe": False,
                            "remoteJid": "436601234567@s.whatsapp.net",
                        },
                        "pushName": "Max",
                        "message": {"conversation": "Hallo!"},
                        "messageTimestamp": recent_ts,
                    },
                ],
            },
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        action._client = mock_client

        result = await action.fetch_messages(
            remote_jid="436601234567@s.whatsapp.net",
            instance="niles-wa-1",
        )

        assert len(result) == 1
        assert result[0]["text"] == "Hallo!"
        assert result[0]["from_me"] is False
        assert result[0]["push_name"] == "Max"
        # Verify correct URL
        call_url = mock_client.post.call_args[0][0]
        assert "/chat/findMessages/niles-wa-1" in call_url

    async def test_fetch_messages_sends_30day_cutoff(self, action):
        """API request includes 30-day timestamp filter."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"messages": {"records": []}}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        action._client = mock_client

        await action.fetch_messages(
            remote_jid="436601234567@s.whatsapp.net",
        )

        payload = mock_client.post.call_args[1]["json"]
        ts_filter = payload["where"]["messageTimestamp"]
        assert "gte" in ts_filter
        assert "lte" in ts_filter
        # Values should be ISO date strings
        from datetime import datetime

        gte_dt = datetime.fromisoformat(ts_filter["gte"])
        lte_dt = datetime.fromisoformat(ts_filter["lte"])
        # gte should be ~30 days ago, lte should be ~now
        assert (lte_dt - gte_dt).days in (29, 30)

    async def test_fetch_messages_media_placeholder(self, action):
        """Media messages without caption get a placeholder."""
        recent_ts = int(time.time()) - 3600
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "messages": {
                "records": [
                    {
                        "key": {"fromMe": False},
                        "pushName": "Img",
                        "message": {"imageMessage": {"url": "..."}},
                        "messageTimestamp": recent_ts,
                    },
                ],
            },
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        action._client = mock_client

        result = await action.fetch_messages(
            remote_jid="436601234567@s.whatsapp.net",
        )

        assert len(result) == 1
        assert result[0]["text"] == "[Bild]"

    async def test_fetch_messages_handles_string_timestamp(self, action):
        """messageTimestamp may be a string — must be cast to int."""
        recent_ts = int(time.time()) - 3600
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "messages": {
                "records": [
                    {
                        "key": {"fromMe": False},
                        "pushName": "Anna",
                        "message": {"conversation": "Hey!"},
                        "messageTimestamp": str(recent_ts),  # string!
                    },
                ],
            },
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        action._client = mock_client

        result = await action.fetch_messages(
            remote_jid="436601234567@s.whatsapp.net",
        )

        assert len(result) == 1
        assert result[0]["text"] == "Hey!"
        assert result[0]["timestamp"] == recent_ts  # int, not string

    async def test_fetch_messages_lid_filter(self, action):
        """Payload includes both remoteJid and remoteJidAlt for LID support."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"messages": {"records": []}}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        action._client = mock_client

        await action.fetch_messages(
            remote_jid="436601234567@s.whatsapp.net",
        )

        payload = mock_client.post.call_args[1]["json"]
        key_filter = payload["where"]["key"]
        assert key_filter["remoteJid"] == "436601234567@s.whatsapp.net"
        assert key_filter["remoteJidAlt"] == "436601234567@s.whatsapp.net"


class TestWebhookIncoming:
    """Test that webhook handles incoming messages correctly."""

    @pytest.fixture
    def mock_app(self):
        app = MagicMock()
        app.state.agent = AsyncMock()
        app.state.whatsapp_action = AsyncMock()
        app.state.settings = _make_settings()
        app.state.wa_store = AsyncMock()
        return app

    @pytest.fixture
    def webhook_payload(self):
        return {
            "event": "messages.upsert",
            "instance": "niles-wa-42",
            "data": {
                "key": {
                    "remoteJid": "436601234567@s.whatsapp.net",
                    "fromMe": False,
                    "id": "MSG001",
                },
                "message": {
                    "conversation": "Hello Niles",
                },
            },
        }

    async def test_incoming_returns_received(self, mock_app, webhook_payload):
        """Incoming message returns received status with sender phone."""
        from niles.sources.whatsapp import whatsapp_webhook

        request = AsyncMock()
        request.app = mock_app
        request.json.return_value = webhook_payload

        result = await whatsapp_webhook(request, token=VALID_TOKEN)

        assert result == {"status": "received", "sender": "436601234567"}

    async def test_group_message_ignored(self, mock_app):
        """Group messages (JID ending in @g.us) are ignored."""
        from niles.sources.whatsapp import whatsapp_webhook

        request = AsyncMock()
        request.app = mock_app
        request.json.return_value = {
            "event": "messages.upsert",
            "instance": "niles-wa-42",
            "data": {
                "key": {
                    "remoteJid": "120363044917396064@g.us",
                    "fromMe": False,
                    "id": "MSG_GRP",
                },
                "message": {"conversation": "Hi everyone"},
            },
        }

        result = await whatsapp_webhook(request, token=VALID_TOKEN)

        assert result == {"status": "ignored", "reason": "group message"}
        mock_app.state.agent.process_event.assert_not_called()

    async def test_webhook_lid_jid_uses_alt(self, mock_app):
        """Webhook with @lid remoteJid falls back to remoteJidAlt."""
        from niles.sources.whatsapp import whatsapp_webhook

        request = AsyncMock()
        request.app = mock_app
        request.json.return_value = {
            "event": "messages.upsert",
            "instance": "niles-wa-1",
            "data": {
                "key": {
                    "remoteJid": "201846417309877@lid",
                    "remoteJidAlt": "436601234567@s.whatsapp.net",
                    "fromMe": False,
                    "id": "MSG_LID",
                    "addressingMode": "lid",
                },
                "message": {"conversation": "Hi from LID"},
            },
        }

        result = await whatsapp_webhook(request, token=VALID_TOKEN)

        # Should use phone from remoteJidAlt, not the LID
        assert result == {"status": "received", "sender": "436601234567"}

    async def test_webhook_lid_self_chat(self, mock_app):
        """Self-chat with LID JID uses remoteJidAlt for reply."""
        from niles.sources.whatsapp import whatsapp_webhook

        mock_app.state.agent.process_event.return_value = "Antwort"
        mock_app.state.whatsapp_action.send_message.return_value = {
            "key": {"id": "REPLY_LID"}
        }

        request = AsyncMock()
        request.app = mock_app
        request.json.return_value = {
            "event": "messages.upsert",
            "instance": "niles-wa-1",
            "data": {
                "key": {
                    "remoteJid": "201846417309877@lid",
                    "remoteJidAlt": "436601234567@s.whatsapp.net",
                    "fromMe": True,
                    "id": "MSG_SELF_LID",
                    "addressingMode": "lid",
                },
                "message": {"conversation": "Hey Niles, was gibt es neues?"},
            },
        }

        result = await whatsapp_webhook(request, token=VALID_TOKEN)

        assert result == {"status": "processed", "trigger": "self-chat"}
        # Reply should use phone-based JID, not LID
        send_call = mock_app.state.whatsapp_action.send_message
        send_call.assert_called_once()
        assert send_call.call_args[1]["to"] == "436601234567@s.whatsapp.net"

    async def test_incoming_never_auto_replies(self, mock_app, webhook_payload):
        """Incoming messages: no LLM call, no reply."""
        from niles.sources.whatsapp import whatsapp_webhook

        request = AsyncMock()
        request.app = mock_app
        request.json.return_value = webhook_payload

        await whatsapp_webhook(request, token=VALID_TOKEN)

        mock_app.state.agent.process_event.assert_not_called()
        mock_app.state.whatsapp_action.send_message.assert_not_called()


class TestAgentPerUserInstance:
    """Test that agent send_whatsapp tool uses per-user instance."""

    @pytest.fixture
    def wa_store_mock(self):
        store = AsyncMock()
        store.get_session.return_value = {
            "user_id": 5,
            "instance_name": "niles-wa-5",
            "phone_number": "436601234567",
            "status": "connected",
        }
        return store

    async def test_send_uses_per_user_instance(self, wa_store_mock):
        from niles.agent.core import NilesAgent

        whatsapp_mock = AsyncMock()
        whatsapp_mock.send_message.return_value = {"status": "sent"}

        agent = NilesAgent(
            config=_make_settings(),
            contacts=AsyncMock(),
            whatsapp=whatsapp_mock,
            memory=AsyncMock(),
            history=AsyncMock(),
            wa_store=wa_store_mock,
        )

        tool_call = MagicMock()
        tool_call.id = "call_123"
        tool_call.function.name = "send_whatsapp"
        tool_call.function.arguments = json.dumps({"to": "436601234567", "text": "Hi"})

        result = await agent._execute_tool_call(tool_call, chat_id="web-user-5")

        assert result == {"status": "sent", "to": "436601234567"}
        whatsapp_mock.send_message.assert_called_once_with(
            to="436601234567",
            text="Hi",
            instance="niles-wa-5",
        )

    async def test_send_without_session_returns_confirm(self):
        from niles.agent.core import NilesAgent

        wa_store_mock = AsyncMock()
        wa_store_mock.get_session.return_value = None

        whatsapp_mock = AsyncMock()
        whatsapp_mock.send_message.return_value = {"status": "sent"}

        agent = NilesAgent(
            config=_make_settings(),
            contacts=AsyncMock(),
            whatsapp=whatsapp_mock,
            memory=AsyncMock(),
            history=AsyncMock(),
            wa_store=wa_store_mock,
        )

        tool_call = MagicMock()
        tool_call.id = "call_456"
        tool_call.function.name = "send_whatsapp"
        tool_call.function.arguments = json.dumps({"to": "436601234567", "text": "Hi"})

        result = await agent._execute_tool_call(tool_call, chat_id="web-user-99")

        # No session → can't determine own phone → confirmation required
        assert "confirm" in result
        whatsapp_mock.send_message.assert_not_called()

    async def test_send_without_wa_store_returns_confirm(self):
        """Agent without wa_store (backwards compat) returns confirmation."""
        from niles.agent.core import NilesAgent

        whatsapp_mock = AsyncMock()
        whatsapp_mock.send_message.return_value = {"status": "sent"}

        agent = NilesAgent(
            config=_make_settings(),
            contacts=AsyncMock(),
            whatsapp=whatsapp_mock,
            memory=AsyncMock(),
            history=AsyncMock(),
        )

        tool_call = MagicMock()
        tool_call.id = "call_789"
        tool_call.function.name = "send_whatsapp"
        tool_call.function.arguments = json.dumps({"to": "436601234567", "text": "Hi"})

        result = await agent._execute_tool_call(tool_call, chat_id="web-user-1")

        # No wa_store → can't determine own phone → confirmation required
        assert "confirm" in result
        whatsapp_mock.send_message.assert_not_called()


class TestAgentGetWhatsAppMessages:
    """Test that agent get_whatsapp_messages queries Evolution API."""

    async def test_get_messages_by_contact_name(self):
        """Contact name is resolved to phone, then fetched from Evolution API."""
        from niles.agent.core import NilesAgent

        contacts_mock = AsyncMock()
        contacts_mock.find_by_name.return_value = {
            "full_name": "Max Mustermann",
            "phone": "436601234567",
            "phones": [{"type": "mobile", "number": "436601234567"}],
            "email": None,
        }

        whatsapp_mock = AsyncMock()
        whatsapp_mock.fetch_messages.return_value = [
            {
                "from_me": False,
                "text": "Treffen wir uns morgen?",
                "timestamp": 1771900000,
                "push_name": "Max",
            },
        ]

        agent = NilesAgent(
            config=_make_settings(),
            contacts=contacts_mock,
            whatsapp=whatsapp_mock,
            memory=AsyncMock(),
            history=AsyncMock(),
        )

        tool_call = MagicMock()
        tool_call.id = "call_msg_1"
        tool_call.function.name = "get_whatsapp_messages"
        tool_call.function.arguments = json.dumps({"contact": "Max"})

        result = await agent._execute_tool_call(tool_call, chat_id="web-user-1")

        assert result["count"] == 1
        assert result["chat_with"] == "Max"
        assert "Treffen wir uns morgen?" in result["transcript"]
        assert "Max: Treffen wir uns morgen?" in result["transcript"]
        # date_range and hinweis metadata for LLM summarization
        assert "date_range" in result
        assert result["date_range"]  # non-empty
        assert "hinweis" in result
        assert "1 Nachrichten" in result["hinweis"]
        contacts_mock.find_by_name.assert_called_once_with("Max")
        whatsapp_mock.fetch_messages.assert_called_once_with(
            remote_jid="436601234567@s.whatsapp.net",
            instance=None,
        )

    async def test_get_messages_by_phone(self):
        """Phone number goes directly to Evolution API (no contacts lookup)."""
        from niles.agent.core import NilesAgent

        contacts_mock = AsyncMock()
        whatsapp_mock = AsyncMock()
        whatsapp_mock.fetch_messages.return_value = [
            {
                "from_me": False,
                "text": "Test",
                "timestamp": 1771900000,
                "push_name": "",
            },
        ]

        agent = NilesAgent(
            config=_make_settings(),
            contacts=contacts_mock,
            whatsapp=whatsapp_mock,
            memory=AsyncMock(),
            history=AsyncMock(),
        )

        tool_call = MagicMock()
        tool_call.id = "call_msg_2"
        tool_call.function.name = "get_whatsapp_messages"
        tool_call.function.arguments = json.dumps({"contact": "436601234567"})

        result = await agent._execute_tool_call(tool_call, chat_id="web-user-1")

        assert result["count"] == 1
        contacts_mock.find_by_name.assert_not_called()
        whatsapp_mock.fetch_messages.assert_called_once_with(
            remote_jid="436601234567@s.whatsapp.net",
            instance=None,
        )

    async def test_get_messages_by_phone_normalizes(self):
        """Phone with +, spaces must be normalized before JID construction."""
        from niles.agent.core import NilesAgent

        contacts_mock = AsyncMock()
        whatsapp_mock = AsyncMock()
        whatsapp_mock.fetch_messages.return_value = [
            {"from_me": False, "text": "Hi", "timestamp": 1771900000, "push_name": ""},
        ]

        agent = NilesAgent(
            config=_make_settings(),
            contacts=contacts_mock,
            whatsapp=whatsapp_mock,
            memory=AsyncMock(),
            history=AsyncMock(),
        )

        tool_call = MagicMock()
        tool_call.id = "call_msg_norm"
        tool_call.function.name = "get_whatsapp_messages"
        tool_call.function.arguments = json.dumps({"contact": "+43 660 123 4567"})

        await agent._execute_tool_call(tool_call, chat_id="web-user-1")

        whatsapp_mock.fetch_messages.assert_called_once_with(
            remote_jid="436601234567@s.whatsapp.net",
            instance=None,
        )

    async def test_get_messages_strips_at_prefix(self):
        """LLM sometimes sends '@Name' — the @ prefix must be stripped."""
        from niles.agent.core import NilesAgent

        contacts_mock = AsyncMock()
        contacts_mock.find_by_name.return_value = {
            "full_name": "Chrissi",
            "phone": "436645225348",
            "phones": [],
            "email": None,
        }

        whatsapp_mock = AsyncMock()
        whatsapp_mock.fetch_messages.return_value = [
            {"from_me": False, "text": "Hi!", "timestamp": 1771900000, "push_name": ""},
        ]

        agent = NilesAgent(
            config=_make_settings(),
            contacts=contacts_mock,
            whatsapp=whatsapp_mock,
            memory=AsyncMock(),
            history=AsyncMock(),
        )

        tool_call = MagicMock()
        tool_call.id = "call_msg_at"
        tool_call.function.name = "get_whatsapp_messages"
        tool_call.function.arguments = json.dumps({"contact": "@Chrissi"})

        result = await agent._execute_tool_call(tool_call, chat_id="web-user-1")

        assert result["count"] == 1
        contacts_mock.find_by_name.assert_called_once_with("Chrissi")

    async def test_get_messages_unknown_contact(self):
        """Unknown contact name returns error."""
        from niles.agent.core import NilesAgent

        contacts_mock = AsyncMock()
        contacts_mock.find_by_name.return_value = None

        agent = NilesAgent(
            config=_make_settings(),
            contacts=contacts_mock,
            whatsapp=AsyncMock(),
            memory=AsyncMock(),
            history=AsyncMock(),
        )

        tool_call = MagicMock()
        tool_call.id = "call_msg_3"
        tool_call.function.name = "get_whatsapp_messages"
        tool_call.function.arguments = json.dumps({"contact": "Nobody"})

        result = await agent._execute_tool_call(tool_call, chat_id="web-user-1")

        assert "error" in result
        assert "Nobody" in result["error"]

    async def test_get_messages_no_contact_returns_error(self):
        """Empty contact parameter returns error."""
        from niles.agent.core import NilesAgent

        agent = NilesAgent(
            config=_make_settings(),
            contacts=AsyncMock(),
            whatsapp=AsyncMock(),
            memory=AsyncMock(),
            history=AsyncMock(),
        )

        tool_call = MagicMock()
        tool_call.id = "call_msg_4"
        tool_call.function.name = "get_whatsapp_messages"
        tool_call.function.arguments = json.dumps({})

        result = await agent._execute_tool_call(tool_call, chat_id="web-user-1")

        assert "error" in result

    async def test_get_messages_uses_per_user_instance(self):
        """Per-user instance is resolved and passed to fetch_messages."""
        from niles.agent.core import NilesAgent

        wa_store_mock = AsyncMock()
        wa_store_mock.get_session.return_value = {
            "user_id": 5,
            "instance_name": "niles-wa-5",
            "phone_number": "436601234567",
            "status": "connected",
        }

        contacts_mock = AsyncMock()
        contacts_mock.find_by_name.return_value = {
            "full_name": "Max",
            "phone": "436609999999",
            "phones": [],
            "email": None,
        }

        whatsapp_mock = AsyncMock()
        whatsapp_mock.fetch_messages.return_value = [
            {"from_me": False, "text": "Hi", "timestamp": 1771900000, "push_name": ""},
        ]

        agent = NilesAgent(
            config=_make_settings(),
            contacts=contacts_mock,
            whatsapp=whatsapp_mock,
            memory=AsyncMock(),
            history=AsyncMock(),
            wa_store=wa_store_mock,
        )

        tool_call = MagicMock()
        tool_call.id = "call_msg_inst"
        tool_call.function.name = "get_whatsapp_messages"
        tool_call.function.arguments = json.dumps({"contact": "Max"})

        await agent._execute_tool_call(tool_call, chat_id="web-user-5")

        whatsapp_mock.fetch_messages.assert_called_once_with(
            remote_jid="436609999999@s.whatsapp.net",
            instance="niles-wa-5",
        )

    async def test_get_messages_date_range_same_day(self):
        """date_range shows single date when all messages are on the same day."""
        from niles.agent.core import NilesAgent

        contacts_mock = AsyncMock()
        contacts_mock.find_by_name.return_value = {
            "full_name": "Anna",
            "phone": "436601111111",
            "phones": [],
            "email": None,
        }

        whatsapp_mock = AsyncMock()
        # Two messages on the same day (2026-02-24 UTC)
        whatsapp_mock.fetch_messages.return_value = [
            {
                "from_me": False,
                "text": "Morgen!",
                "timestamp": 1772000000,
                "push_name": "Anna",
            },
            {"from_me": True, "text": "Hey!", "timestamp": 1772003600, "push_name": ""},
        ]

        agent = NilesAgent(
            config=_make_settings(),
            contacts=contacts_mock,
            whatsapp=whatsapp_mock,
            memory=AsyncMock(),
            history=AsyncMock(),
        )

        tool_call = MagicMock()
        tool_call.id = "call_dr_same"
        tool_call.function.name = "get_whatsapp_messages"
        tool_call.function.arguments = json.dumps({"contact": "Anna"})

        result = await agent._execute_tool_call(tool_call, chat_id="web-user-1")

        # Single date, no range separator
        assert "\u2013" not in result["date_range"]
        assert "2026" in result["date_range"]

    async def test_get_messages_date_range_multi_day(self):
        """date_range shows start–end when messages span multiple days."""
        from niles.agent.core import NilesAgent

        contacts_mock = AsyncMock()
        contacts_mock.find_by_name.return_value = {
            "full_name": "Anna",
            "phone": "436601111111",
            "phones": [],
            "email": None,
        }

        whatsapp_mock = AsyncMock()
        # Messages spanning 2 days apart
        whatsapp_mock.fetch_messages.return_value = [
            {
                "from_me": False,
                "text": "Hi",
                "timestamp": 1771900000,
                "push_name": "Anna",
            },
            {"from_me": True, "text": "Hey", "timestamp": 1772100000, "push_name": ""},
        ]

        agent = NilesAgent(
            config=_make_settings(),
            contacts=contacts_mock,
            whatsapp=whatsapp_mock,
            memory=AsyncMock(),
            history=AsyncMock(),
        )

        tool_call = MagicMock()
        tool_call.id = "call_dr_multi"
        tool_call.function.name = "get_whatsapp_messages"
        tool_call.function.arguments = json.dumps({"contact": "Anna"})

        result = await agent._execute_tool_call(tool_call, chat_id="web-user-1")

        # En-dash separator between two different dates
        assert " \u2013 " in result["date_range"]

    async def test_get_messages_hinweis_contains_count_and_range(self):
        """hinweis field contains message count and date_range value."""
        from niles.agent.core import NilesAgent

        contacts_mock = AsyncMock()
        contacts_mock.find_by_name.return_value = {
            "full_name": "Max",
            "phone": "436601234567",
            "phones": [],
            "email": None,
        }

        whatsapp_mock = AsyncMock()
        whatsapp_mock.fetch_messages.return_value = [
            {
                "from_me": False,
                "text": "Eins",
                "timestamp": 1771900000,
                "push_name": "Max",
            },
            {"from_me": True, "text": "Zwei", "timestamp": 1771910000, "push_name": ""},
            {
                "from_me": False,
                "text": "Drei",
                "timestamp": 1771920000,
                "push_name": "Max",
            },
        ]

        agent = NilesAgent(
            config=_make_settings(),
            contacts=contacts_mock,
            whatsapp=whatsapp_mock,
            memory=AsyncMock(),
            history=AsyncMock(),
        )

        tool_call = MagicMock()
        tool_call.id = "call_hinweis"
        tool_call.function.name = "get_whatsapp_messages"
        tool_call.function.arguments = json.dumps({"contact": "Max"})

        result = await agent._execute_tool_call(tool_call, chat_id="web-user-1")

        assert "3 Nachrichten" in result["hinweis"]
        assert result["date_range"] in result["hinweis"]
        # Verify the hinweis contains a summarization instruction (wording-independent)
        assert "zusammen" in result["hinweis"].lower()
