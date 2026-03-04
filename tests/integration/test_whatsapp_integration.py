"""Integration tests for WhatsAppAction (Evolution API).

Only read operations are tested by default.  Send tests require
INTEGRATION_TEST_PHONE to be set explicitly.
"""

import os

import pytest
import pytest_asyncio

from niles.actions.whatsapp import WhatsAppAction
from niles.config import Settings

from .conftest import (
    EVOLUTION_API_KEY,
    EVOLUTION_API_URL,
    EVOLUTION_INSTANCE,
    POSTGRES_PASSWORD,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]


@pytest_asyncio.fixture(loop_scope="session")
async def whatsapp_action(evolution_client):
    """WhatsAppAction with real Evolution API client."""
    settings = Settings(
        evolution_api_key=EVOLUTION_API_KEY,
        evolution_api_url=EVOLUTION_API_URL,
        evolution_instance=EVOLUTION_INSTANCE,
        postgres_password=POSTGRES_PASSWORD,
    )
    return WhatsAppAction(settings, client=evolution_client)


class TestWhatsAppReadOperations:
    async def test_get_connection_state(self, whatsapp_action):
        state = await whatsapp_action.get_connection_state(EVOLUTION_INSTANCE)
        assert state in ("open", "close", "connecting")

    async def test_fetch_messages_empty_jid(self, whatsapp_action):
        messages = await whatsapp_action.fetch_messages(
            remote_jid="000000000000@s.whatsapp.net",
        )
        assert isinstance(messages, list)

    async def test_get_owner_jid(self, whatsapp_action):
        result = await whatsapp_action.get_owner_jid(EVOLUTION_INSTANCE)
        # Either a JID string or None depending on connection state
        assert result is None or "@" in result


class TestWhatsAppSend:
    @pytest.mark.skipif(
        not os.environ.get("INTEGRATION_TEST_PHONE"),
        reason="INTEGRATION_TEST_PHONE not set",
    )
    async def test_send_message_to_self(self, whatsapp_action):
        phone = os.environ["INTEGRATION_TEST_PHONE"]
        result = await whatsapp_action.send_message(
            to=phone,
            text="[Integration Test] Automated test message.",
        )
        assert "error" not in result
