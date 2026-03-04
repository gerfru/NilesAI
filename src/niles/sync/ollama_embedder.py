"""Shared Ollama embedding client with persistent HTTP connection."""

import logging

import httpx

logger = logging.getLogger(__name__)

_EMBED_TIMEOUT = 30.0


class OllamaEmbedder:
    """Generates text embeddings via Ollama /api/embed.

    Uses a persistent httpx.AsyncClient for connection pooling.
    nomic-embed-text requires task prefixes for optimal retrieval:
    - "search_document: " for documents being indexed
    - "search_query: " for search queries
    """

    def __init__(self, ollama_base_url: str, model: str = "nomic-embed-text"):
        self._ollama_url = ollama_base_url.rstrip("/").removesuffix("/v1")
        self._model = model
        self._client = httpx.AsyncClient()

    async def embed(self, text: str, *, prefix: str = "") -> list[float] | None:
        """Generate embedding for a single text. Returns None on failure.

        Args:
            text: The text to embed.
            prefix: Task prefix (e.g. "search_query: ", "search_document: ").
        """
        try:
            response = await self._client.post(
                f"{self._ollama_url}/api/embed",
                json={"model": self._model, "input": f"{prefix}{text}"},
                timeout=_EMBED_TIMEOUT,
            )
            response.raise_for_status()
            data = response.json()
            embeddings = data.get("embeddings", [])
            if embeddings:
                return embeddings[0]
            return None
        except Exception:
            logger.exception("Ollama embedding request failed")
            return None

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()
