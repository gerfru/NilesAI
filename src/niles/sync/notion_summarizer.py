"""Generate page summaries via Ollama LLM for hierarchical chunking."""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

_GENERATE_TIMEOUT = 60.0

_SUMMARIZE_PROMPT = """\
Summarize the following document in 2-4 sentences. \
Capture the main topic, key points, and purpose. \
Write the summary in the same language as the document.

Document title: {title}

{content}

Summary:"""


class NotionSummarizer:
    """Generates concise page summaries via Ollama LLM.

    Uses the raw Ollama /api/generate endpoint (consistent with OllamaEmbedder).
    Summaries are used as Level-0 (parent) chunks in hierarchical RAG.
    """

    def __init__(
        self,
        ollama_base_url: str,
        model: str = "llama3.1:8b",
        max_input_chars: int = 4000,
        max_tokens: int = 200,
    ):
        self._ollama_url = ollama_base_url.rstrip("/").removesuffix("/v1")
        self._model = model
        self._max_input = max_input_chars
        self._max_tokens = max_tokens
        self._client = httpx.AsyncClient()

    @property
    def model(self) -> str:
        """Return the configured model name."""
        return self._model

    async def summarize(self, content: str, title: str = "") -> str | None:
        """Generate a summary for a page. Returns None on failure.

        Long content (> max_input_chars) is truncated: first half + [...] + last half.
        """
        if len(content) > self._max_input:
            half = self._max_input // 2
            content = content[:half] + "\n[...]\n" + content[-half:]

        prompt = _SUMMARIZE_PROMPT.format(title=title, content=content)
        try:
            response = await self._client.post(
                f"{self._ollama_url}/api/generate",
                json={
                    "model": self._model,
                    "prompt": prompt,
                    "stream": False,
                    "think": False,
                    "options": {"num_predict": self._max_tokens},
                },
                timeout=_GENERATE_TIMEOUT,
            )
            response.raise_for_status()
            text = response.json().get("response", "").strip()
            return text or None
        except Exception:
            logger.exception("Summary generation failed for '%s'", title[:50])
            return None

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()
