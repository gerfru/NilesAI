# SPDX-License-Identifier: AGPL-3.0-only
"""Token counting / budgeting helpers.

Uses tiktoken's ``cl100k_base`` encoder as a model-agnostic APPROXIMATION. The
local model (llama3.1:8b) tokenises differently, so counts are estimates — good
enough to keep the assembled context inside the window and to cap oversized tool
results, which is the goal here.
"""

from __future__ import annotations

import tiktoken

# Per-message formatting overhead (role markers etc.) — a small constant so the
# budget stays conservative rather than optimistic.
_MSG_OVERHEAD = 4

_encoder = None


def _enc() -> tiktoken.Encoding:
    global _encoder
    if _encoder is None:
        _encoder = tiktoken.get_encoding("cl100k_base")
    return _encoder


def count_tokens(text: str) -> int:
    """Approximate token count of *text*."""
    if not text:
        return 0
    return len(_enc().encode(text))


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    """Truncate *text* to at most *max_tokens* tokens (no-op if already within)."""
    if max_tokens <= 0:
        return ""
    enc = _enc()
    toks = enc.encode(text)
    if len(toks) <= max_tokens:
        return text
    return enc.decode(toks[:max_tokens])


def fit_history(history: list[dict], budget_tokens: int) -> list[dict]:
    """Keep the most recent messages whose cumulative tokens fit *budget_tokens*.

    Input/output are in chronological order (oldest → newest). Oldest messages
    are dropped first when the budget is exceeded.
    """
    if budget_tokens <= 0:
        return []
    kept: list[dict] = []
    used = 0
    for msg in reversed(history):
        cost = count_tokens(msg.get("content", "")) + _MSG_OVERHEAD
        if used + cost > budget_tokens:
            break
        kept.append(msg)
        used += cost
    kept.reverse()
    return kept
