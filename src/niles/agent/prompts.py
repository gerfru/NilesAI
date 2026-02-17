"""System prompt loading and building."""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_PROMPT = (
    "Du bist Niles, ein persönlicher AI-Assistent. "
    "Antworte auf Deutsch, kurz und prägnant."
)


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


def build_system_prompt(base_prompt: str, memories: list[dict]) -> str:
    """Build full system prompt with memory context."""
    if not memories:
        return base_prompt

    memory_lines = []
    for entry in memories:
        key = entry["key"]
        value = entry["value"]
        memory_lines.append(f"- {key}: {value}")

    memory_section = (
        "\n\n## Dein Gedächtnis\n"
        "Folgende Dinge hast du dir gemerkt:\n"
        + "\n".join(memory_lines)
    )

    return base_prompt + memory_section
