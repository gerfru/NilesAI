"""Contact lookup in PostgreSQL."""

import logging
import re

import asyncpg

logger = logging.getLogger(__name__)


def normalize_phone(phone: str) -> str:
    """
    Normalize phone number for WhatsApp.

    - Remove +, spaces, dashes, parentheses, dots
    - Remove leading 00
    - Convert leading 0 to 43 (Austria)

    Examples:
        "+43 660 123 4567" -> "436601234567"
        "0660 123 4567"    -> "436601234567"
        "00436601234567"   -> "436601234567"
    """
    phone = re.sub(r"[\s\-\(\)\.]", "", phone)
    phone = phone.lstrip("+")
    if phone.startswith("00"):
        phone = phone[2:]
    if phone.startswith("0"):
        phone = "43" + phone[1:]
    return phone


class ContactsAction:
    """Search contacts by name and return phone numbers."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def find_by_name(self, name: str) -> dict | None:
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
            word_conditions = []
            params = []
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

            query = f"""
                SELECT id, full_name, first_name, last_name,
                       phone_primary, phone_mobile, phone_work, email
                FROM contacts
                WHERE {where_clause}
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

        phones = [
            {"type": p["type"], "number": normalize_phone(p["number"])}
            for p in phone_rows
        ]

        # Preferred phone: first from sorted list (mobile > home > work > other)
        preferred = phones[0]["number"] if phones else None

        # Fallback to legacy columns if contact_phones is empty (pre-migration)
        if not phones:
            raw_phone = row["phone_mobile"] or row["phone_primary"] or row["phone_work"]
            preferred = normalize_phone(raw_phone) if raw_phone else None

        return {
            "full_name": row["full_name"],
            "phone": preferred,
            "phones": phones,
            "email": row["email"],
        }
