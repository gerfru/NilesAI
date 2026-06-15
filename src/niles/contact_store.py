# SPDX-License-Identifier: AGPL-3.0-only
"""Data-access for contacts (contacts + contact_phones tables).

Owns the raw SQL the service layer used to run inline. CardDAV *sync writes*
live in CardDAVSourceManager; this store covers the read/lookup + maintenance
queries the agent/web layers need.
"""

import logging
from collections.abc import Mapping, Sequence

import asyncpg

logger = logging.getLogger(__name__)


class ContactStore:
    """Read/maintenance queries for contacts. Fails closed without a user_id."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def count_and_last_sync(self, user_id: int | None = None) -> dict:
        """Return {cnt, last_sync}, optionally scoped to a user."""
        if user_id is not None:
            row = await self.pool.fetchrow(
                "SELECT COUNT(*) AS cnt, MAX(updated_at) AS last_sync FROM contacts WHERE user_id = $1",
                user_id,
            )
        else:
            row = await self.pool.fetchrow("SELECT COUNT(*) AS cnt, MAX(updated_at) AS last_sync FROM contacts")
        return dict(row) if row else {"cnt": 0, "last_sync": None}

    async def clear(self, user_id: int | None = None) -> None:
        """Delete contacts, optionally scoped to a user."""
        if user_id is not None:
            await self.pool.execute("DELETE FROM contacts WHERE user_id = $1", user_id)
            logger.info("Contacts cleared for user %d", user_id)
        else:
            await self.pool.execute("DELETE FROM contacts")
            logger.info("All contacts cleared")

    async def find_contact_row(self, name: str, *, user_id: int | None) -> Mapping | None:
        """Find the best-matching contact row, scoped to the user.

        Fails closed: without a ``user_id`` no lookup runs, so an unresolved
        chat context can never read another user's contacts.

        Multi-word queries require each word to match a name field (handles
        "Brunner Thomas" vs "Thomas Brunner"); ranking prefers exact > prefix >
        partial full_name matches.
        """
        if user_id is None:
            logger.warning("find_contact_row called without user_id — failing closed (no lookup)")
            return None

        words = name.split()
        if len(words) > 1:
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
            uid_param = f"${len(params) + 1}"
            params.append(user_id)

            query = f"""
                SELECT id, full_name, first_name, last_name,
                       phone_primary, phone_mobile, phone_work, email
                FROM contacts
                WHERE {where_clause} AND user_id = {uid_param}
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
            return await self.pool.fetchrow(query, *params)

        return await self.pool.fetchrow(
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

    async def get_phones(self, contact_id: int) -> Sequence[Mapping]:
        """Return phone rows for a contact, sorted mobile > home > work > other."""
        return await self.pool.fetch(
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
