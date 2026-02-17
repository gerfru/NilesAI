"""System prompt loading."""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_PROMPT = (
    "Du bist Niles, ein persönlicher AI-Assistent. "
    "Antworte auf Deutsch, kurz und prägnant."
)


def load_system_prompt(path: str = "config/soul.md") -> str:
    """Load system prompt from soul.md file."""
    try:
        return Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.warning("soul.md not found at %s, using default prompt", path)
        return _DEFAULT_PROMPT
