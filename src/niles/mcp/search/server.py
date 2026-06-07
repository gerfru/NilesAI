"""SearXNG Web Search MCP server.

Provides one tool:
- web_search: meta-search via a local SearXNG instance

Configuration via environment variables:
  SEARXNG_URL            SearXNG base URL (required, e.g. "http://searxng:8080")
  SEARXNG_RESULT_COUNT   Default max results (default: 10)
  SEARXNG_LANGUAGE       Default language code (default: "de")
"""

import os

import httpx
from mcp.server.fastmcp import FastMCP

from niles.http_retry import retry_http

mcp = FastMCP("search")

_DEFAULT_RESULT_COUNT = 10
_DEFAULT_LANGUAGE = "de"
_TIMEOUT = 10


def _get_config() -> tuple[str, int, str]:
    """Read SearXNG config from environment.

    Returns (base_url, result_count, language).
    Raises ValueError if SEARXNG_URL is not set.
    """
    url = os.environ.get("SEARXNG_URL", "")
    if not url:
        raise ValueError("SEARXNG_URL nicht konfiguriert. SearXNG-Instanz-URL muss gesetzt sein.")
    count = int(os.environ.get("SEARXNG_RESULT_COUNT", str(_DEFAULT_RESULT_COUNT)))
    lang = os.environ.get("SEARXNG_LANGUAGE", _DEFAULT_LANGUAGE)
    return url.rstrip("/"), count, lang


@retry_http
async def _fetch_searxng(base_url: str, params: dict) -> dict:
    """HTTP call to SearXNG API (retryable on transient failures)."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(f"{base_url}/search", params=params)
        resp.raise_for_status()
        return resp.json()


@mcp.tool()
async def web_search(
    query: str,
    result_count: int = 0,
    categories: list[str] | None = None,
    language: str | None = None,
    time_range: str | None = None,
) -> str:
    """Web-Suche ueber SearXNG Meta-Suchmaschine.

    Durchsucht mehrere Suchmaschinen gleichzeitig und liefert
    aggregierte Ergebnisse mit Titel, URL und Kurzbeschreibung.

    Args:
        query: Suchbegriff
        result_count: Maximale Anzahl Ergebnisse (0 = Standard)
        categories: Kategorien (z.B. ["general"], ["news"], ["images"])
        language: Sprachcode (z.B. "de", "en", "all")
        time_range: Zeitraum-Filter ("day", "week", "month", "year")
    """
    try:
        base_url, default_count, default_lang = _get_config()
    except ValueError as e:
        return str(e)

    if result_count <= 0:
        result_count = default_count

    params: dict[str, str] = {
        "q": query,
        "format": "json",
        "language": language or default_lang,
    }
    if categories:
        params["categories"] = ",".join(categories)
    if time_range:
        params["time_range"] = time_range

    try:
        data = await _fetch_searxng(base_url, params)
    except httpx.HTTPError as e:
        return f"Fehler bei der Websuche: {e}"

    results = data.get("results", [])
    if not results:
        return f"Keine Ergebnisse fuer '{query}' gefunden."

    results = results[:result_count]

    lines = []
    for i, r in enumerate(results, 1):
        title = r.get("title", "Ohne Titel")
        url = r.get("url", "")
        content = r.get("content", "")
        if content and len(content) > 200:
            content = content[:200] + "..."
        lines.append(f"{i}. [{title}]({url})\n   {content}")

    return "\n\n".join(lines)
