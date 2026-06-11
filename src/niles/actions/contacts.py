"""Contact lookup and CardDAV connection management."""

import logging
import re
from typing import cast

import asyncpg

from niles.types import ContactInfo

logger = logging.getLogger(__name__)


def normalize_phone(phone: str) -> str:
    """
    Normalize phone number for WhatsApp.

    - Remove +, spaces, dashes, parentheses, dots
    - Remove leading 00
    - Convert leading 0 to 43 (Austria)

    Examples:
        "+43 660 587 5573" -> "436605875573"
        "0660 587 5573"    -> "436605875573"
        "00436605875573"   -> "436605875573"
    """
    phone = re.sub(r"[\s\-\(\)\.]", "", phone)
    phone = phone.lstrip("+")
    if phone.startswith("00"):
        phone = phone[2:]
    if phone.startswith("0"):
        phone = "43" + phone[1:]
    return phone


class ContactsAction:
    """Contact search, CardDAV connection management."""

    def __init__(
        self,
        pool: asyncpg.Pool,
        *,
        carddav_manager=None,
    ):
        self.pool = pool
        self.carddav_manager = carddav_manager

    async def get_sync_status(self, user_id: int | None = None) -> dict:
        """Return contact count and last sync timestamp, optionally per user."""
        if user_id is not None:
            row = await self.pool.fetchrow(
                "SELECT COUNT(*) AS cnt, MAX(updated_at) AS last_sync FROM contacts WHERE user_id = $1",
                user_id,
            )
        else:
            row = await self.pool.fetchrow("SELECT COUNT(*) AS cnt, MAX(updated_at) AS last_sync FROM contacts")
        return dict(row) if row else {"cnt": 0, "last_sync": None}

    async def clear_all(self, user_id: int | None = None) -> None:
        """Remove contacts, optionally scoped to a user."""
        if user_id is not None:
            await self.pool.execute("DELETE FROM contacts WHERE user_id = $1", user_id)
            logger.info("Contacts cleared for user %d", user_id)
        else:
            await self.pool.execute("DELETE FROM contacts")
            logger.info("All contacts cleared")

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
        """
        words = name.split()
        if len(words) > 1:
            # Multi-word search: each word must appear in at least one name field
            word_conditions: list[str] = []
            params: list[str | int] = []
            for i, word in enumerate(words):
                p = f"${i + 1}"
                word_conditions.append(
                    f"(full_name ILIKE '%%' || {p} || '%%' "
                    f"OR first_name ILIKE '%%' || {p} || '%%' "
                    f"OR last_name ILIKE '%%' || {p} || '%%')"
                )
                params.append(word)

            where_clause = " AND ".join(word_conditions)
            name_param = f"${len(params) + 1}"
            params.append(name)

            # Optional user_id filter
            if user_id is not None:
                uid_param = f"${len(params) + 1}"
                params.append(user_id)
                user_filter = f" AND user_id = {uid_param}"
            else:
                user_filter = ""

            query = f"""
                SELECT id, full_name, first_name, last_name,
                       phone_primary, phone_mobile, phone_work, email
                FROM contacts
                WHERE {where_clause}{user_filter}
                ORDER BY
                    CASE
                        WHEN LOWER(full_name) = LOWER({name_param}) THEN 1
                        WHEN LOWER(full_name) LIKE LOWER({name_param}) || '%%' THEN 2
                        WHEN LOWER(full_name) LIKE '%%' || LOWER({name_param}) || '%%' THEN 3
                        ELSE 4
                    END,
                    full_name ASC
                LIMIT 1
            """
            row = await self.pool.fetchrow(query, *params)
        else:
            # Single-word search: original logic
            if user_id is not None:
                row = await self.pool.fetchrow(
                    """
                    SELECT id, full_name, first_name, last_name,
                           phone_primary, phone_mobile, phone_work, email
                    FROM contacts
                    WHERE (full_name ILIKE '%' || $1 || '%'
                       OR first_name ILIKE '%' || $1 || '%'
                       OR last_name ILIKE '%' || $1 || '%')
                       AND user_id = $2
                    ORDER BY
                        CASE
                            WHEN LOWER(full_name) = LOWER($1) THEN 1
                            WHEN LOWER(full_name) LIKE LOWER($1) || '%' THEN 2
                            WHEN LOWER(full_name) LIKE '%' || LOWER($1) || '%' THEN 3
                            ELSE 4
                        END,
                        full_name ASC
                    LIMIT 1
                    """,
                    name,
                    user_id,
                )
            else:
                row = await self.pool.fetchrow(
                    """
                    SELECT id, full_name, first_name, last_name,
                           phone_primary, phone_mobile, phone_work, email
                    FROM contacts
                    WHERE full_name ILIKE '%' || $1 || '%'
                       OR first_name ILIKE '%' || $1 || '%'
                       OR last_name ILIKE '%' || $1 || '%'
                    ORDER BY
                        CASE
                            WHEN LOWER(full_name) = LOWER($1) THEN 1
                            WHEN LOWER(full_name) LIKE LOWER($1) || '%' THEN 2
                            WHEN LOWER(full_name) LIKE '%' || LOWER($1) || '%' THEN 3
                            ELSE 4
                        END,
                        full_name ASC
                    LIMIT 1
                    """,
                    name,
                )

        if not row:
            return None

        # Fetch all phone numbers from contact_phones table
        contact_id = row["id"]
        phone_rows = await self.pool.fetch(
            """
            SELECT type, number FROM contact_phones
            WHERE contact_id = $1
            ORDER BY
                CASE type
                    WHEN 'mobile' THEN 1
                    WHEN 'home' THEN 2
                    WHEN 'work' THEN 3
                    ELSE 4
                END
            """,
            contact_id,
        )

        phones = [{"type": p["type"], "number": normalize_phone(p["number"])} for p in phone_rows]

        # Preferred phone: first from sorted list (mobile > home > work > other)
        preferred = phones[0]["number"] if phones else None

        # Fallback to legacy columns if contact_phones is empty (pre-migration)
        if not phones:
            raw_phone = row["phone_mobile"] or row["phone_primary"] or row["phone_work"]
            preferred = normalize_phone(raw_phone) if raw_phone else None

        return cast(
            ContactInfo,
            {
                "full_name": row["full_name"],
                "phone": preferred,
                "phones": phones,
                "email": row["email"],
            },
        )
