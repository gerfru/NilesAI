"""Integration tests for ContactsAction (PostgreSQL)."""

import pytest

from niles.actions.contacts import ContactsAction
from niles.contact_store import ContactStore

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]


class TestFindContact:
    async def test_find_by_exact_name(self, pool_in_tx, seed_contact):
        action = ContactsAction(ContactStore(pool_in_tx))
        result = await action.find_by_name("Max Mustermann", user_id=seed_contact["user_id"])
        assert result is not None
        assert result["full_name"] == "Max Mustermann"
        assert result["phone"] == "435000000000"
        assert result["email"] == "max@example.com"

    async def test_find_by_partial_name(self, pool_in_tx, seed_contact):
        action = ContactsAction(ContactStore(pool_in_tx))
        result = await action.find_by_name("Muster", user_id=seed_contact["user_id"])
        assert result is not None
        assert result["full_name"] == "Max Mustermann"

    async def test_find_by_first_name(self, pool_in_tx, seed_contact):
        action = ContactsAction(ContactStore(pool_in_tx))
        result = await action.find_by_name("Max", user_id=seed_contact["user_id"])
        assert result is not None

    async def test_find_case_insensitive(self, pool_in_tx, seed_contact):
        action = ContactsAction(ContactStore(pool_in_tx))
        result = await action.find_by_name("max mustermann", user_id=seed_contact["user_id"])
        assert result is not None

    async def test_find_reversed_name_order(self, pool_in_tx, seed_contact):
        action = ContactsAction(ContactStore(pool_in_tx))
        result = await action.find_by_name("Mustermann Max", user_id=seed_contact["user_id"])
        assert result is not None

    async def test_find_nonexistent(self, pool_in_tx, seed_contact):
        action = ContactsAction(ContactStore(pool_in_tx))
        result = await action.find_by_name("Nonexistent Person", user_id=seed_contact["user_id"])
        assert result is None

    async def test_phones_list_populated(self, pool_in_tx, seed_contact):
        action = ContactsAction(ContactStore(pool_in_tx))
        result = await action.find_by_name("Max", user_id=seed_contact["user_id"])
        assert result is not None
        assert len(result["phones"]) >= 1
        assert result["phones"][0]["type"] == "mobile"

    async def test_fails_closed_without_user_id(self, pool_in_tx, seed_contact):
        """No user_id → no lookup, even though the contact exists (H1)."""
        action = ContactsAction(ContactStore(pool_in_tx))
        result = await action.find_by_name("Max Mustermann", user_id=None)
        assert result is None

    async def test_other_user_cannot_see_contact(self, pool_in_tx, seed_contact):
        """A different user_id must not resolve another user's contact (H1)."""
        action = ContactsAction(ContactStore(pool_in_tx))
        result = await action.find_by_name("Max Mustermann", user_id=seed_contact["user_id"] + 9999)
        assert result is None
