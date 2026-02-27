# Niles AI — Web Fetch MCP Server Spec

> **Version:** 1.0  
> **Date:** 2026-02-27  
> **Scope:** MCP-Server zum Abrufen und Extrahieren von Webseiten-Inhalten  
> **Aufwand:** ~0,5 Tage  
> **Voraussetzung:** Niles-Core-Spec v7.3, MCP-Infrastruktur (Weather-Server als Referenz)  
> **Abhängigkeit:** Kann unabhängig von der Web-Search-Spec implementiert werden, ergänzt sie aber ideal

---

## 1. Motivation

Die Web-Search-Spec (SearXNG) liefert Suchergebnisse mit Titel, URL und kurzem Snippet (~200 Zeichen). Für viele Recherche-Aufgaben reicht das nicht — der Agent braucht den vollständigen Inhalt einer Seite, z.B.:

- "Lies diesen Artikel und fasse ihn zusammen": Agent hat die URL, braucht den Text
- "Was steht auf dieser Seite?": Direkte URL vom Benutzer
- Multi-Step-Recherche: Suche → Ergebnis-URLs → Inhalte lesen → Zusammenfassung

Ohne `fetch_url` endet die Recherche beim Snippet. Mit `fetch_url` kann der Agent Webseiten vollständig lesen.

---

## 2. Architektur-Entscheidung

### Eigener MCP-Server (wie Weather)

| Kriterium | Eigener Server | `@modelcontextprotocol/server-fetch` |
|-----------|---------------|--------------------------------------|
| Sprache | Python (wie Weather) | Node.js |
| Dependency | `trafilatura` (Apache 2.0) | Node.js Runtime im Container |
| Kontrolle | Volle Kontrolle (Timeout, Max-Länge, Domain-Filter) | Konfigurierbar, aber Black Box |
| Template | `mcp/weather/server.py` existiert | Neues Pattern |
| Docker-Impact | Keine neue Runtime | Node.js nötig |

**Entscheidung:** Eigener Python-MCP-Server. Folgt dem etablierten Pattern, keine neue Runtime.

### Text-Extraktion: trafilatura

- **Quelle:** [github.com/adbar/trafilatura](https://github.com/adbar/trafilatura)
- **Lizenz:** Apache 2.0 (ab v1.8.0)
- **PyPI:** `trafilatura>=2.0.0`
- **Funktion:** HTML → reiner Text. Entfernt Header, Footer, Navigation, Ads, Cookie-Banner. Behält Absätze, Überschriften, Listen
- **Benchmarks:** Beste Open-Source-Bibliothek in ScrapingHub-Evaluation (F1-Score), ROUGE-LSum (Bevendorff et al. 2023)
- **Genutzt von:** HuggingFace, IBM, Microsoft Research, Stanford, Allen Institute

---

## 3. Server-Implementierung

### Dateistruktur

```
src/niles/mcp/
├── weather/
│   ├── __init__.py
│   ├── __main__.py
│   └── server.py          # Referenz-Implementation
├── fetch/                  # NEU
│   ├── __init__.py
│   ├── __main__.py
│   └── server.py
└── client.py               # MCPManager (unchanged)
```

### `src/niles/mcp/fetch/__init__.py`

```python
```

### `src/niles/mcp/fetch/__main__.py`

```python
"""Entry point for ``python -m niles.mcp.fetch``."""

from .server import mcp

mcp.run(transport="stdio")
```

### `src/niles/mcp/fetch/server.py`

```python
"""Web Fetch MCP server — extracts clean text from URLs.

Provides one tool:
- fetch_url: Downloads a web page and extracts the main text content.

Configuration via environment variables:
  FETCH_MAX_CHARS      Max characters to return (default: 8000)
  FETCH_TIMEOUT        HTTP timeout in seconds (default: 15)
  FETCH_USER_AGENT     User-Agent header (default: "Niles AI/1.0")
"""

import os

import httpx
import trafilatura
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("fetch")

# Defaults
_DEFAULT_MAX_CHARS = 8000
_DEFAULT_TIMEOUT = 15
_DEFAULT_USER_AGENT = "Niles AI/1.0 (local assistant)"

# Blocked schemes / patterns for safety
_BLOCKED_SCHEMES = ("file://", "ftp://", "data:", "javascript:")
_MAX_RESPONSE_BYTES = 5 * 1024 * 1024  # 5 MB


def _get_config() -> tuple[int, int, str]:
    """Read config from environment.

    Returns (max_chars, timeout, user_agent).
    """
    max_chars = int(os.environ.get("FETCH_MAX_CHARS", str(_DEFAULT_MAX_CHARS)))
    timeout = int(os.environ.get("FETCH_TIMEOUT", str(_DEFAULT_TIMEOUT)))
    user_agent = os.environ.get("FETCH_USER_AGENT", _DEFAULT_USER_AGENT)
    return max_chars, timeout, user_agent


@mcp.tool()
async def fetch_url(url: str, max_chars: int = 0) -> str:
    """Ruft den Textinhalt einer Webseite ab.

    Laedt die URL herunter, extrahiert den Haupttext (ohne Navigation,
    Werbung, Footer) und gibt ihn als reinen Text zurueck.

    Args:
        url: Die vollstaendige URL der Webseite (https://...)
        max_chars: Maximale Anzahl Zeichen (0 = Standard aus Konfiguration)

    Returns:
        Extrahierter Textinhalt der Seite, oder Fehlermeldung.
    """
    config_max, timeout, user_agent = _get_config()
    if max_chars <= 0:
        max_chars = config_max

    # --- Validation ---
    if not url or not url.strip():
        return "Fehler: Keine URL angegeben."

    url = url.strip()

    # Block dangerous schemes
    url_lower = url.lower()
    for scheme in _BLOCKED_SCHEMES:
        if url_lower.startswith(scheme):
            return f"Fehler: URL-Schema '{scheme}' ist nicht erlaubt."

    # Ensure https:// or http://
    if not url_lower.startswith(("http://", "https://")):
        url = "https://" + url

    # --- Fetch ---
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=timeout,
            headers={"User-Agent": user_agent},
            max_redirects=5,
        ) as client:
            response = await client.get(url)
            response.raise_for_status()

            # Content-Type check
            content_type = response.headers.get("content-type", "")
            if not any(t in content_type for t in ("text/html", "text/plain", "application/xhtml")):
                return f"Fehler: Unerwarteter Content-Type '{content_type}'. Nur HTML/Text wird unterstuetzt."

            # Size check
            if len(response.content) > _MAX_RESPONSE_BYTES:
                return f"Fehler: Seite zu gross ({len(response.content)} Bytes, max {_MAX_RESPONSE_BYTES})."

            html = response.text

    except httpx.TimeoutException:
        return f"Fehler: Timeout nach {timeout} Sekunden beim Laden von {url}"
    except httpx.HTTPStatusError as e:
        return f"Fehler: HTTP {e.response.status_code} beim Laden von {url}"
    except httpx.ConnectError:
        return f"Fehler: Verbindung zu {url} fehlgeschlagen."
    except Exception as e:
        return f"Fehler: {type(e).__name__}: {e}"

    # --- Extract ---
    try:
        text = trafilatura.extract(
            html,
            include_comments=False,
            include_tables=True,
            favor_recall=True,      # Lieber zu viel als zu wenig
            deduplicate=True,
        )
    except Exception as e:
        return f"Fehler bei Textextraktion: {type(e).__name__}: {e}"

    if not text or not text.strip():
        return f"Kein Textinhalt auf der Seite gefunden ({url})."

    # --- Truncate ---
    text = text.strip()
    if len(text) > max_chars:
        # Cut at last sentence boundary before limit
        cut_text = text[:max_chars]
        last_period = cut_text.rfind(". ")
        if last_period > max_chars * 0.7:
            text = cut_text[:last_period + 1]
        else:
            text = cut_text + "..."
        text += f"\n\n[Gekuerzt auf {max_chars} Zeichen. Originaltext ist laenger.]"

    return text
```

---

## 4. Konfiguration

### `config/mcp_servers.yaml` — neuer Eintrag

```yaml
  fetch:
    command: python
    args: ["-m", "niles.mcp.fetch"]
    env:
      FETCH_MAX_CHARS: "8000"
      FETCH_TIMEOUT: "15"
      FETCH_USER_AGENT: "Niles AI/1.0 (local assistant)"
```

**Kein Feature-Flag nötig.** Im Gegensatz zu SearXNG (das einen extra Docker-Container braucht) ist der Fetch-Server ein reiner Python-Prozess ohne externe Abhängigkeiten. Er kann immer aktiv sein — analog zum Weather-Server.

### `pyproject.toml` — neue Dependency

```toml
dependencies = [
    # ... existing ...
    # HTML text extraction for web fetch MCP server
    "trafilatura>=2.0.0",
]
```

### `soul.md` — Ergänzung

```markdown
### Webseiten lesen

- Du hast ein `mcp__fetch__fetch_url`-Tool um Webseiten-Inhalte abzurufen
- Nutze es wenn:
  - Der Benutzer eine URL teilt und fragt "was steht da?"
  - Du nach einer Web-Suche den vollständigen Inhalt eines Ergebnisses lesen willst
  - Der Benutzer "lies diesen Artikel" oder "fasse diese Seite zusammen" sagt
- Das Tool extrahiert den Haupttext (ohne Navigation, Werbung, Footer)
- Bei langen Seiten wird der Text automatisch gekürzt
- Erfinde NIEMALS Inhalte von Webseiten. Wenn das Tool einen Fehler zurückgibt, sage das dem Benutzer
```

---

## 5. Sicherheit

### URL-Validation

| Schutzmaßnahme | Implementation |
|----------------|---------------|
| Blocked Schemes | `file://`, `ftp://`, `data:`, `javascript:` → abgelehnt |
| HTTPS Default | URL ohne Schema → `https://` prepended |
| Max Response Size | 5 MB Limit → Seiten über 5 MB werden abgelehnt |
| Content-Type Check | Nur `text/html`, `text/plain`, `application/xhtml` erlaubt |
| Timeout | Konfigurierbar, Default 15 Sekunden |
| Max Redirects | 5 Redirects, dann Abbruch |
| User-Agent | Identifiziert sich als "Niles AI" (kein Browser-Spoofing) |

### Was der Server NICHT tut

- Kein JavaScript-Rendering (kein Playwright/Selenium)
- Keine Cookies, keine Sessions, kein Login
- Keine Dateien herunterladen (nur HTML/Text)
- Kein Caching (jeder Aufruf ist frisch)
- Keine lokalen URLs (Private IPs wie 127.0.0.1 oder 192.168.x.x werden von httpx nicht speziell blockiert — bei Bedarf: SSRF-Check ergänzen)

### [Nicht verifiziert] SSRF-Risiko

Der Server kann auf interne Docker-Netzwerk-Adressen zugreifen (z.B. `http://evolution_postgres:5432`). In der aktuellen Architektur ist das Risiko gering, weil nur der Agent (LLM) die URL bestimmt und der Agent über `soul.md` angewiesen wird. Bei kommerziellem Einsatz mit unvertrauenswürdigen User-Eingaben sollte ein SSRF-Guard ergänzt werden (Private-IP-Blocklist).

---

## 6. Tests

### `tests/test_fetch_mcp.py`

```python
"""Tests for the web fetch MCP server."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from niles.mcp.fetch.server import fetch_url


class TestFetchUrl:
    async def test_empty_url(self):
        result = await fetch_url("")
        assert "Keine URL" in result

    async def test_blocked_scheme_file(self):
        result = await fetch_url("file:///etc/passwd")
        assert "nicht erlaubt" in result

    async def test_blocked_scheme_javascript(self):
        result = await fetch_url("javascript:alert(1)")
        assert "nicht erlaubt" in result

    async def test_prepends_https(self):
        """URL without scheme gets https:// prepended."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "text/html"}
        mock_response.content = b"<html><body><p>Hello World</p></body></html>"
        mock_response.text = "<html><body><p>Hello World</p></body></html>"
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("niles.mcp.fetch.server.httpx.AsyncClient", return_value=mock_client):
            with patch("niles.mcp.fetch.server.trafilatura.extract", return_value="Hello World"):
                result = await fetch_url("example.com")
                # Verify https:// was prepended
                call_args = mock_client.get.call_args[0][0]
                assert call_args == "https://example.com"
                assert "Hello World" in result

    async def test_timeout_error(self):
        import httpx as httpx_mod

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx_mod.TimeoutException("timeout"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("niles.mcp.fetch.server.httpx.AsyncClient", return_value=mock_client):
            result = await fetch_url("https://slow-site.example.com")
            assert "Timeout" in result

    async def test_wrong_content_type(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/pdf"}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("niles.mcp.fetch.server.httpx.AsyncClient", return_value=mock_client):
            result = await fetch_url("https://example.com/doc.pdf")
            assert "Content-Type" in result

    async def test_successful_extraction(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "text/html; charset=utf-8"}
        mock_response.content = b"<html><body><article><p>Main content here.</p></article></body></html>"
        mock_response.text = "<html><body><article><p>Main content here.</p></article></body></html>"
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("niles.mcp.fetch.server.httpx.AsyncClient", return_value=mock_client),
            patch("niles.mcp.fetch.server.trafilatura.extract", return_value="Main content here."),
        ):
            result = await fetch_url("https://example.com/article")
            assert "Main content here." in result

    async def test_truncation(self):
        long_text = "Dies ist ein Satz. " * 500  # ~9500 chars
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "text/html"}
        mock_response.content = b"<html><body>long</body></html>"
        mock_response.text = "<html><body>long</body></html>"
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("niles.mcp.fetch.server.httpx.AsyncClient", return_value=mock_client),
            patch("niles.mcp.fetch.server.trafilatura.extract", return_value=long_text),
            patch.dict(os.environ, {"FETCH_MAX_CHARS": "200"}),
        ):
            result = await fetch_url("https://example.com")
            assert "Gekuerzt" in result
            assert len(result) < 400  # 200 + truncation notice

    async def test_no_content_extracted(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "text/html"}
        mock_response.content = b"<html><body></body></html>"
        mock_response.text = "<html><body></body></html>"
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("niles.mcp.fetch.server.httpx.AsyncClient", return_value=mock_client),
            patch("niles.mcp.fetch.server.trafilatura.extract", return_value=None),
        ):
            result = await fetch_url("https://example.com/empty")
            assert "Kein Textinhalt" in result
```

---

## 7. Zusammenspiel mit Web Search

### Recherche-Flow (Search + Fetch)

```
User: "Recherchiere aktuelle Kritiken zum neuen iPhone"
    │
Agent: Tool-Call → mcp__searxng__search("iPhone 17 Kritiken Reviews 2026")
    │
SearXNG: 10 Ergebnisse (Titel + URL + Snippet)
    │
Agent: "Ergebnis 3 von The Verge sieht relevant aus"
    │
Agent: Tool-Call → mcp__fetch__fetch_url("https://theverge.com/iphone-17-review")
    │
Fetch-Server: Lädt Seite, extrahiert Text (max 8000 Zeichen)
    │
Agent: Fasst Verge-Artikel + andere Snippets zusammen
    │
User: Bekommt 5 Kernpunkte mit Quellen
```

### soul.md für den kombinierten Flow

```markdown
### Recherche-Strategie

Wenn der Benutzer eine tiefere Recherche will:
1. Suche zuerst mit `mcp__searxng__search` nach dem Thema
2. Wenn die Snippets nicht ausreichen, lies 1-2 der relevantesten Ergebnisse mit `mcp__fetch__fetch_url`
3. Fasse alles zusammen: Kernpunkte + Quellen
4. Maximal 2 Seiten vollständig lesen (Token-Budget beachten)
```

Dieser Abschnitt ist nur relevant wenn **beide** Specs implementiert sind (Search + Fetch). Fetch funktioniert aber auch alleine — wenn ein Benutzer direkt eine URL teilt.

---

## 8. Dateien-Übersicht

### Neue Dateien

| Datei | Zweck |
|-------|-------|
| `src/niles/mcp/fetch/__init__.py` | Package init |
| `src/niles/mcp/fetch/__main__.py` | Entry point (`python -m niles.mcp.fetch`) |
| `src/niles/mcp/fetch/server.py` | MCP-Server mit `fetch_url`-Tool |
| `tests/test_fetch_mcp.py` | Unit Tests |

### Geänderte Dateien

| Datei | Änderung |
|-------|----------|
| `pyproject.toml` | `trafilatura>=2.0.0` |
| `config/mcp_servers.yaml` | `fetch`-Server-Eintrag |
| `config/soul.md` | "Webseiten lesen"-Anweisung |
| `docs/Niles-Core-Spec.md` | Fetch-Server in MCP-Section dokumentieren |

---

## 9. Verifikation

- [ ] `python -m niles.mcp.fetch` startet ohne Fehler (stdio mode)
- [ ] MCP-Server in Logs: `MCP server 'fetch' started (1/1 tools registered)`
- [ ] Chat: "Lies diese Seite: https://example.com" → Agent ruft `fetch_url` auf, gibt Inhalt zurück
- [ ] Chat: URL ohne https → wird automatisch ergänzt
- [ ] `file:///etc/passwd` → "nicht erlaubt"
- [ ] Timeout bei nicht erreichbarer URL → saubere Fehlermeldung
- [ ] PDF-URL → "Content-Type nicht unterstützt"
- [ ] Leere Seite → "Kein Textinhalt gefunden"
- [ ] Seite > 8000 Zeichen → Truncation mit Hinweis
- [ ] Alle Tests bestehen (`pytest tests/test_fetch_mcp.py -v`)
- [ ] Bestehende 455 Tests unverändert bestehen
- [ ] `ruff check src/ tests/` — keine Lint-Fehler