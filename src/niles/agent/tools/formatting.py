# SPDX-License-Identifier: AGPL-3.0-only
"""Shared message transcript formatting for WhatsApp and Signal handlers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo


def format_message_transcript(
    messages: Sequence[Mapping[str, Any]],
    contact_name: str,
    timezone_str: str,
) -> dict[str, Any]:
    """Format messages into a readable chat transcript with date range.

    Returns dict with keys: chat_with, count, date_range, hinweis, transcript.

    Raises ValueError if *messages* is empty (callers must guard).
    """
    if not messages:
        raise ValueError("messages must not be empty")

    local_tz = ZoneInfo(timezone_str)
    lines = []
    for msg in messages:
        ts = datetime.fromtimestamp(msg["timestamp"], tz=timezone.utc).astimezone(local_tz)
        who = "Du" if msg["from_me"] else contact_name
        lines.append(f"[{ts:%d.%m. %H:%M}] {who}: {msg['text']}")

    transcript = "\n".join(lines)

    first_dt = datetime.fromtimestamp(messages[0]["timestamp"], tz=timezone.utc).astimezone(local_tz)
    last_dt = datetime.fromtimestamp(messages[-1]["timestamp"], tz=timezone.utc).astimezone(local_tz)

    if first_dt.date() == last_dt.date():
        date_range = first_dt.strftime("%d.%m.%Y")
    else:
        date_range = f"{first_dt.strftime('%d.%m.%Y')} \u2013 {last_dt.strftime('%d.%m.%Y')}"

    return {
        "chat_with": contact_name,
        "count": len(messages),
        "date_range": date_range,
        # Summarization instruction — keep in sync with:
        # - config/soul.md "Nachrichten lesen"
        # - tool description in core.py TOOLS
        "hinweis": (
            f"{len(messages)} Nachrichten ({date_range}). "
            "Fasse die wichtigsten Punkte zusammen: "
            "Termine, Abmachungen, offene Fragen, wichtige Infos. "
            "Gib NICHT das rohe Transcript wieder."
        ),
        "transcript": transcript,
    }
