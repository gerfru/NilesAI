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
        "+43 660 123 4567" -> "4366012345678"
        "0660 123 4567"    -> "4366012345678"
        "004366012345678"   -> "4366012345678"
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

        Priority:
        1. Exact match on full_name
        2. Prefix match on full_name
        3. Partial match on full_name
        4. Match on first_name or last_name

        Returns dict with full_name, phone, email or None.
        """
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
