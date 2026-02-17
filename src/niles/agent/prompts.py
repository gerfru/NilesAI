"""System prompt loading."""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_PROMPT = (
    "Du bist Niles, ein persönlicher AI-Assistent. "
    "Antworte auf Deutsch, kurz und prägnant."
)


def load_system_prompt(path: str | None = None) -> str:
    """Load system prompt from soul.md file."""
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
