"""Tests for WhatsApp session management (per-user Evolution API instances)."""

import json
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
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with pytest.MonkeyPatch.context() as m:
            m.setattr("httpx.AsyncClient", lambda: mock_client)
            result = await action.send_message(
                to="436601234567", text="Hi", instance="niles-wa-5",
            )
            assert "error" not in result
            # Verify the URL includes the custom instance name
            call_url = mock_client.post.call_args[0][0]
            assert "niles-wa-5" in call_url

    async def test_fetch_messages(self, action):
        """fetch_messages calls Evolution API findMessages endpoint."""
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
                        "messageTimestamp": 1771900000,
                    },
                ],
            },
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with pytest.MonkeyPatch.context() as m:
            m.setattr("httpx.AsyncClient", lambda: mock_client)
            result = await action.fetch_messages(
                remote_jid="436601234567@s.whatsapp.net",
                limit=10,
                instance="niles-wa-1",
            )

        assert len(result) == 1
        assert result[0]["text"] == "Hallo!"
        assert result[0]["from_me"] is False
        assert result[0]["push_name"] == "Max"
        # Verify correct URL
        call_url = mock_client.post.call_args[0][0]
        assert "/chat/findMessages/niles-wa-1" in call_url

    async def test_fetch_messages_filters_old(self, action):
        """Messages older than 30 days are filtered out."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "messages": {
                "records": [
                    {
                        "key": {"fromMe": False},
                        "pushName": "Old",
                        "message": {"conversation": "Ancient"},
                        "messageTimestamp": 1000000,  # 1970
                    },
                ],
            },
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with pytest.MonkeyPatch.context() as m:
            m.setattr("httpx.AsyncClient", lambda: mock_client)
            result = await action.fetch_messages(
                remote_jid="436601234567@s.whatsapp.net",
            )

        assert result == []

    async def test_fetch_messages_skips_non_text(self, action):
        """Messages without text content are skipped."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "messages": {
                "records": [
                    {
                        "key": {"fromMe": False},
                        "pushName": "Img",
                        "message": {"imageMessage": {"url": "..."}},
                        "messageTimestamp": 1771900000,
                    },
                ],
            },
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with pytest.MonkeyPatch.context() as m:
            m.setattr("httpx.AsyncClient", lambda: mock_client)
            result = await action.fetch_messages(
                remote_jid="436601234567@s.whatsapp.net",
            )

        assert result == []

    async def test_fetch_messages_handles_string_timestamp(self, action):
        """messageTimestamp may be a string — must be cast to int."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "messages": {
                "records": [
                    {
                        "key": {"fromMe": False},
                        "pushName": "Anna",
                        "message": {"conversation": "Hey!"},
                        "messageTimestamp": "1771900000",  # string!
                    },
                ],
            },
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with pytest.MonkeyPatch.context() as m:
            m.setattr("httpx.AsyncClient", lambda: mock_client)
            result = await action.fetch_messages(
                remote_jid="436601234567@s.whatsapp.net",
            )

        assert len(result) == 1
        assert result[0]["text"] == "Hey!"
        assert result[0]["timestamp"] == 1771900000  # int, not string

    def test_headers(self, action):
        """_headers returns correct API key."""
        assert action._headers() == {"apikey": VALID_TOKEN}


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
            to="436601234567", text="Hi", instance="niles-wa-5",
        )

    async def test_send_without_session_uses_global(self):
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

        assert result == {"status": "sent", "to": "436601234567"}
        whatsapp_mock.send_message.assert_called_once_with(
            to="436601234567", text="Hi", instance=None,
        )

    async def test_send_without_wa_store_uses_global(self):
        """Agent without wa_store (backwards compat) uses global instance."""
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

        assert result == {"status": "sent", "to": "436601234567"}
        whatsapp_mock.send_message.assert_called_once_with(
            to="436601234567", text="Hi", instance=None,
        )


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
        contacts_mock.find_by_name.assert_called_once_with("Max")
        whatsapp_mock.fetch_messages.assert_called_once_with(
            remote_jid="436601234567@s.whatsapp.net",
            limit=10,
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
            limit=10,
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
            limit=10,
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

    async def test_get_messages_limit_capped(self):
        """Limit is capped at 50."""
        from niles.agent.core import NilesAgent

        contacts_mock = AsyncMock()
        contacts_mock.find_by_name.return_value = {
            "full_name": "Max",
            "phone": "436601234567",
            "phones": [],
            "email": None,
        }

        whatsapp_mock = AsyncMock()
        whatsapp_mock.fetch_messages.return_value = []

        agent = NilesAgent(
            config=_make_settings(),
            contacts=contacts_mock,
            whatsapp=whatsapp_mock,
            memory=AsyncMock(),
            history=AsyncMock(),
        )

        tool_call = MagicMock()
        tool_call.id = "call_msg_5"
        tool_call.function.name = "get_whatsapp_messages"
        tool_call.function.arguments = json.dumps({"contact": "Max", "limit": 999})

        await agent._execute_tool_call(tool_call, chat_id="web-user-1")

        whatsapp_mock.fetch_messages.assert_called_once_with(
            remote_jid="436601234567@s.whatsapp.net",
            limit=50,
            instance=None,
        )

    async def test_get_messages_limit_as_string(self):
        """LLM may pass limit as string — must be cast to int."""
        from niles.agent.core import NilesAgent

        contacts_mock = AsyncMock()
        contacts_mock.find_by_name.return_value = {
            "full_name": "Max",
            "phone": "436601234567",
            "phones": [],
            "email": None,
        }

        whatsapp_mock = AsyncMock()
        whatsapp_mock.fetch_messages.return_value = []

        agent = NilesAgent(
            config=_make_settings(),
            contacts=contacts_mock,
            whatsapp=whatsapp_mock,
            memory=AsyncMock(),
            history=AsyncMock(),
        )

        tool_call = MagicMock()
        tool_call.id = "call_msg_str"
        tool_call.function.name = "get_whatsapp_messages"
        tool_call.function.arguments = json.dumps({"contact": "Max", "limit": "10"})

        await agent._execute_tool_call(tool_call, chat_id="web-user-1")

        whatsapp_mock.fetch_messages.assert_called_once_with(
            remote_jid="436601234567@s.whatsapp.net",
            limit=10,
            instance=None,
        )

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
            limit=10,
            instance="niles-wa-5",
        )
