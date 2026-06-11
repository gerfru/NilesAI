"""System prompt loading and building."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from niles.types import MemoryEntry

logger = logging.getLogger(__name__)

_DEFAULT_PROMPT = "Du bist Niles, ein persönlicher AI-Assistent. Antworte auf Deutsch, kurz und prägnant."


def load_system_prompt(path: str | None = None) -> str:
    """Load base system prompt from soul.md file."""
    if path is None:
        # Default: config/soul.md relative to project root
        path = Path(__file__).parent.parent.parent.parent / "config" / "soul.md"
    else:
        path = Path(path)

    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.warning("soul.md not found at %s, using default prompt", path)
        return _DEFAULT_PROMPT


def build_system_prompt(
    base_prompt: str,
    memories: list[MemoryEntry],
    timezone: str = "Europe/Vienna",
    calendar_sources: list[str] | None = None,
) -> str:
    """Build full system prompt with current datetime and memory context."""
    try:
        tz = ZoneInfo(timezone)
    except KeyError, ValueError:
        logger.warning("Invalid timezone '%s', falling back to Europe/Vienna", timezone)
        timezone = "Europe/Vienna"
        tz = ZoneInfo(timezone)
    now = datetime.now(tz)
    weekdays_de = [
        "Montag",
        "Dienstag",
        "Mittwoch",
        "Donnerstag",
        "Freitag",
        "Samstag",
        "Sonntag",
    ]
    weekday = weekdays_de[now.weekday()]

    time_section = (
        "\n\n## Aktuelle Zeit\n"
        f"Heute ist {weekday}, der {now.strftime('%d.%m.%Y')}. "
        f"Es ist {now.strftime('%H:%M')} Uhr ({timezone})."
    )

    # Add upcoming 7 days so the LLM doesn't have to calculate weekday→date
    upcoming_lines = []
    for i in range(1, 8):
        day = now + timedelta(days=i)
        day_name = weekdays_de[day.weekday()]
        upcoming_lines.append(f"- {day_name}: {day.strftime('%d.%m.%Y')}")
    time_section += "\n\nKommende Tage:\n" + "\n".join(upcoming_lines)

    prompt = base_prompt + time_section

    if calendar_sources:
        prompt += "\n\n## Verfügbare Kalender\n"
        for name in calendar_sources:
            prompt += f"- {name}\n"

    if memories:
        memory_lines = [f"- {e['key']}: {e['value']}" for e in memories]
        prompt += "\n\n## Dein Gedächtnis\nFolgende Dinge hast du dir gemerkt:\n" + "\n".join(memory_lines)

    return prompt


# ---------------------------------------------------------------------------
# Notion RAG mode — minimal prompt for small models (llama3.1:8b)
# ---------------------------------------------------------------------------

_NOTION_RAG_PROMPT = (
    "Du bist Niles, ein persoenlicher AI-Assistent. "
    "Du beantwortest Fragen anhand der bereitgestellten "
    "Notion-Abschnitte.\n\n"
    "## Regeln\n"
    "1. Stuetze deine Antwort auf die [Notion-Kontext]-Abschnitte.\n"
    "2. Wenn die Abschnitte thematisch zur Frage passen, fasse die "
    "relevanten Inhalte zusammen. Wenn kein Abschnitt auch nur entfernt "
    "relevant ist, sage: "
    '"Dazu habe ich keine Informationen in deinem Notion-Wissensspeicher."\n'
    "3. Nenne die Quellen als Markdown-Links: [Seitentitel](URL).\n"
    "4. Priorisiere die relevantesten Abschnitte. Auch teilweise "
    "passende Inhalte koennen hilfreich sein.\n"
    "5. Erfinde KEINE Informationen. Nutze KEIN Vorwissen.\n"
    "6. Antworte auf Deutsch, kurz und praegnant."
)


def build_notion_rag_prompt(
    memories: list[MemoryEntry] | None = None,
    timezone: str = "Europe/Vienna",
) -> str:
    """Build a minimal system prompt for Notion RAG mode.

    Excludes tool instructions, calendar sources, and upcoming days
    to maximise token budget for RAG context chunks.
    """
    try:
        tz = ZoneInfo(timezone)
    except KeyError, ValueError:
        tz = ZoneInfo("Europe/Vienna")
    now = datetime.now(tz)
    weekdays_de = [
        "Montag",
        "Dienstag",
        "Mittwoch",
        "Donnerstag",
        "Freitag",
        "Samstag",
        "Sonntag",
    ]
    weekday = weekdays_de[now.weekday()]

    prompt = _NOTION_RAG_PROMPT
    prompt += f"\n\nHeute ist {weekday}, der {now.strftime('%d.%m.%Y')}."

    if memories:
        memory_lines = [f"- {e['key']}: {e['value']}" for e in memories]
        prompt += "\n\n## Gedaechtnis\n" + "\n".join(memory_lines)

    return prompt
