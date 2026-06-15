# SPDX-License-Identifier: AGPL-3.0-only
"""Contact lookup and CardDAV connection management."""

import logging
import re
from typing import TYPE_CHECKING, cast

from niles.contact_store import ContactStore
from niles.types import ContactInfo

if TYPE_CHECKING:
    from niles.sync.carddav_manager import CardDAVSourceManager

logger = logging.getLogger(__name__)


def normalize_phone(phone: str, country_code: str = "43") -> str:
    """
    Normalize phone number for WhatsApp.

    - Remove +, spaces, dashes, parentheses, dots
    - Remove leading 00
    - Convert leading 0 to country_code (default: 43/Austria)

    Examples (country_code="43"):
        "+43 500 000 0000" -> "435000000000"
        "0500 000 0000"    -> "435000000000"
        "00435000000000"   -> "435000000000"
    """
    phone = re.sub(r"[\s\-\(\)\.]", "", phone)
    phone = phone.lstrip("+")
    if phone.startswith("00"):
        phone = phone[2:]
    if phone.startswith("0"):
        phone = country_code + phone[1:]
    return phone


class ContactsAction:
    """Contact search, CardDAV connection management."""

    def __init__(
        self,
        contact_store: ContactStore,
        *,
        carddav_manager: "CardDAVSourceManager | None" = None,
        phone_country_code: str = "43",
    ) -> None:
        self.store = contact_store
        self.carddav_manager = carddav_manager
        self.phone_country_code = phone_country_code

    async def get_sync_status(self, user_id: int | None = None) -> dict:
        """Return contact count and last sync timestamp, optionally per user."""
        return await self.store.count_and_last_sync(user_id)

    async def clear_all(self, user_id: int | None = None) -> None:
        """Remove contacts, optionally scoped to a user."""
        await self.store.clear(user_id)

    async def connect(
        self,
        url: str,
        user: str,
        password: str,
        user_id: int | None = None,
    ) -> dict:
        """Test CardDAV connection, create source, trigger initial sync.

        Returns the created source dict.
        Raises ConnectionError on test failure, ValueError on invalid input.
        """
        if self.carddav_manager is None:
            raise RuntimeError("ContactsAction requires carddav_manager for connect/disconnect")
        url, user = url.strip(), user.strip()

        ok, message = await self.carddav_manager.test_connection(url, user, password)
        if not ok:
            raise ConnectionError(message)

        source = await self.carddav_manager.add_source(url, user, password, user_id=user_id)

        # Run initial sync for the new source
        try:
            await self.carddav_manager.sync_source(source["id"], user_id=user_id)
        except Exception:
            logger.exception("Initial CardDAV sync failed for source %d", source["id"])

        return source

    async def disconnect(self, source_id: int, user_id: int | None = None) -> bool:
        """Remove a CardDAV source (contacts are CASCADE-deleted)."""
        if self.carddav_manager is None:
            raise RuntimeError("ContactsAction requires carddav_manager for connect/disconnect")
        return await self.carddav_manager.remove_source(source_id, user_id=user_id)

    async def find_by_name(self, name: str, *, user_id: int | None = None) -> ContactInfo | None:
        """
        Search contact by name (case-insensitive, partial match).

        For multi-word queries (e.g. "Thomas Brunner"), each word must match
        somewhere in the contact's name fields. This handles cases where
        full_name is stored as "Brunner Thomas" or the search order differs.

        Priority:
        1. Exact match on full_name
        2. Prefix match on full_name
        3. Partial match on full_name
        4. All words match across name fields

        Returns dict with full_name, phone, email or None.

        Fails closed (in the store): without a ``user_id`` no lookup is
        performed, so an unresolved chat context can never read another
        user's contacts.
        """
        row = await self.store.find_contact_row(name, user_id=user_id)
        if not row:
            return None

        phone_rows = await self.store.get_phones(row["id"])

        cc = self.phone_country_code
        phones = [{"type": p["type"], "number": normalize_phone(p["number"], cc)} for p in phone_rows]

        # Preferred phone: first from sorted list (mobile > home > work > other)
        preferred = phones[0]["number"] if phones else None

        # Fallback to legacy columns if contact_phones is empty (pre-migration)
        if not phones:
            raw_phone = row["phone_mobile"] or row["phone_primary"] or row["phone_work"]
            preferred = normalize_phone(raw_phone, cc) if raw_phone else None

        return cast(
            ContactInfo,
            {
                "full_name": row["full_name"],
                "phone": preferred,
                "phones": phones,
                "email": row["email"],
            },
        )
