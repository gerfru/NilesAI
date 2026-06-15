# SPDX-License-Identifier: AGPL-3.0-only
"""Helpers to redact PII and secrets before they reach logs.

Niles is privacy-first: tool arguments, message contents, phone numbers and
credential-bearing URLs must never appear in plaintext in the structured logs
(which are collected by Docker / a log aggregator). These helpers centralise
the masking so every call site redacts consistently.
"""

import re

# Masks the userinfo segment (login and password) that can precede the host in a URL.
_CREDENTIAL_RE = re.compile(r"://[^@/\s]+@")

# Tool-argument keys whose values may carry PII (recipients, message text,
# contact names, calendar/task titles, search queries, ...).
_SENSITIVE_KEYS = frozenset(
    {
        "to",
        "recipient",
        "phone",
        "number",
        "text",
        "message",
        "body",
        "content",
        "summary",
        "title",
        "description",
        "name",
        "contact",
        "query",
        "email",
    }
)


def redact_credentials(text: str) -> str:
    """Mask the userinfo (login:password) embedded in a URL before the host."""
    return _CREDENTIAL_RE.sub("://***@", text)


def redact_phone(phone: str | None) -> str:
    """Mask a phone number, keeping only the last two digits for correlation."""
    if not phone:
        return "***"
    digits = re.sub(r"\D", "", phone)
    if len(digits) <= 2:
        return "***"
    return f"***{digits[-2:]}"


def redact_tool_args(args: object) -> dict | str:
    """Return a log-safe copy of tool arguments with sensitive values masked.

    Non-sensitive keys keep their values; sensitive keys are replaced with a
    ``<redacted len=N>`` marker so the shape stays visible without the content.
    """
    if not isinstance(args, dict):
        return "<non-dict args>"
    safe: dict = {}
    for key, value in args.items():
        if key.lower() in _SENSITIVE_KEYS:
            length = len(value) if isinstance(value, (str, list, dict)) else "?"
            safe[key] = f"<redacted len={length}>"
        else:
            safe[key] = value
    return safe
