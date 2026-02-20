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
                SELECT full_name, first_name, last_name,
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
                SELECT full_name, first_name, last_name,
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

        # Phone priority: mobile > primary > work
        raw_phone = row["phone_mobile"] or row["phone_primary"] or row["phone_work"]
        phone = normalize_phone(raw_phone) if raw_phone else None

        return {
            "full_name": row["full_name"],
            "phone": phone,
            "email": row["email"],
        }
