"""Integration tests for ContactsAction (PostgreSQL)."""

import pytest

from niles.actions.contacts import ContactsAction

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]


class TestFindContact:
    async def test_find_by_exact_name(self, pool_in_tx, seed_contact):
        action = ContactsAction(pool_in_tx)
        result = await action.find_by_name("Max Mustermann")
        assert result is not None
        assert result["full_name"] == "Max Mustermann"
        assert result["phone"] == "436601234567"
        assert result["email"] == "max@example.com"

    async def test_find_by_partial_name(self, pool_in_tx, seed_contact):
        action = ContactsAction(pool_in_tx)
        result = await action.find_by_name("Muster")
        assert result is not None
        assert result["full_name"] == "Max Mustermann"

    async def test_find_by_first_name(self, pool_in_tx, seed_contact):
        action = ContactsAction(pool_in_tx)
        result = await action.find_by_name("Max")
        assert result is not None

    async def test_find_case_insensitive(self, pool_in_tx, seed_contact):
        action = ContactsAction(pool_in_tx)
        result = await action.find_by_name("max mustermann")
        assert result is not None

    async def test_find_reversed_name_order(self, pool_in_tx, seed_contact):
        action = ContactsAction(pool_in_tx)
        result = await action.find_by_name("Mustermann Max")
        assert result is not None

    async def test_find_nonexistent(self, pool_in_tx, seed_contact):
        action = ContactsAction(pool_in_tx)
        result = await action.find_by_name("Nonexistent Person")
        assert result is None

    async def test_phones_list_populated(self, pool_in_tx, seed_contact):
        action = ContactsAction(pool_in_tx)
        result = await action.find_by_name("Max")
        assert result is not None
        assert len(result["phones"]) >= 1
        assert result["phones"][0]["type"] == "mobile"
