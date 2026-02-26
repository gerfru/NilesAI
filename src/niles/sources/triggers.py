"""Shared trigger-phrase detection for messaging sources (WhatsApp, Signal)."""

TRIGGER_PHRASES = ("hey niles", "hi niles", "hallo niles", "niles")
# Case-insensitive trigger phrases. Checked against the start of the message.


def is_niles_trigger(text: str) -> bool:
    """Check if a message starts with a Niles trigger phrase.

    Requires a word boundary after the phrase to avoid false positives
    like "Nilesh" or "nilesarmy".
    """
    lower = text.strip().lower()
    for phrase in TRIGGER_PHRASES:
        if lower.startswith(phrase):
            rest = lower[len(phrase) :]
            if not rest or not rest[0].isalpha():
                return True
    return False


def strip_trigger(text: str) -> str:
    """Remove the trigger phrase from the beginning of the message.

    Returns the remaining text after the trigger, stripped of leading
    whitespace, commas, and colons.

    Examples:
        "Hey Niles, was steht heute an?" → "was steht heute an?"
        "Hey Niles was steht heute an?"  → "was steht heute an?"
        "Niles: Termin morgen?"          → "Termin morgen?"
        "Hey Niles"                      → ""
    """
    lower = text.strip().lower()
    for phrase in TRIGGER_PHRASES:
        if lower.startswith(phrase):
            rest = lower[len(phrase) :]
            if not rest or not rest[0].isalpha():
                return text.strip()[len(phrase) :].lstrip(" ,:-").strip()
    return text.strip()
