"""Integration tests for SignalAction (signal-cli-rest-api)."""

import pytest
import pytest_asyncio

from niles.actions.signal import SignalAction
from niles.config import Settings
from .conftest import POSTGRES_PASSWORD, SIGNAL_API_URL, SIGNAL_PHONE

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]


@pytest_asyncio.fixture(loop_scope="session")
async def signal_action(signal_available):
    """SignalAction connected to real Signal API."""
    settings = Settings(
        signal_api_url=SIGNAL_API_URL,
        signal_phone_number=SIGNAL_PHONE,
        evolution_api_key="unused",
        postgres_password=POSTGRES_PASSWORD,
    )
    action = SignalAction(settings)
    yield action
    await action.close()


class TestSignalReadOperations:
    async def test_get_status(self, signal_action):
        result = await signal_action.get_status()
        assert isinstance(result, dict)

    async def test_get_accounts(self, signal_action):
        accounts = await signal_action.get_accounts()
        assert isinstance(accounts, list)
