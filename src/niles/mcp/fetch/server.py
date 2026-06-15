# SPDX-License-Identifier: AGPL-3.0-only
"""Web Fetch MCP server — extracts clean text from URLs.

Provides one tool:
- fetch_url: Downloads a web page and extracts the main text content.

Configuration via environment variables:
  FETCH_MAX_CHARS      Max characters to return (default: 8000)
  FETCH_TIMEOUT        HTTP timeout in seconds (default: 15)
  FETCH_USER_AGENT     User-Agent header (default: "Niles AI/1.0")
"""

import os
from urllib.parse import urlsplit, urlunsplit

import httpx
import trafilatura
from mcp.server.fastmcp import FastMCP

from niles.network import resolve_public_ip

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


def _validate_url(url: str) -> tuple[str, str | None]:
    """Validate and normalize a URL.

    Returns (clean_url, None) on success, or ("", error_message) on failure.
    """
    if not url or not url.strip():
        return "", "Fehler: Keine URL angegeben."

    url = url.strip()
    url_lower = url.lower()

    for scheme in _BLOCKED_SCHEMES:
        if url_lower.startswith(scheme):
            return "", f"Fehler: URL-Schema '{scheme}' ist nicht erlaubt."

    if not url_lower.startswith(("http://", "https://")):
        url = "https://" + url

    # SSRF is enforced at connect time in _pinned_get (resolve-then-connect),
    # which is robust against DNS rebinding. No host check here.
    return url, None


async def _pinned_get(
    client: httpx.AsyncClient,
    url: str,
    *,
    user_agent: str,
) -> tuple[httpx.Response | None, str | None]:
    """GET *url*, pinning the TCP connection to a freshly validated public IP.

    Resolves the host once, validates it is public, then connects to that exact
    IP while preserving the original Host header and TLS SNI/cert hostname (via
    the ``sni_hostname`` extension). This defeats DNS rebinding: the address we
    validate is the address we connect to — there is no second resolution.

    Returns (response, None) or (None, error_message).
    """
    parts = urlsplit(url)
    host = parts.hostname
    if not host:
        return None, "Fehler: Ungueltige URL."
    ip = resolve_public_ip(host)
    if ip is None:
        return None, "Fehler: Zugriff auf interne Adressen ist nicht erlaubt."
    netloc = f"[{ip}]" if ":" in ip else ip
    if parts.port:
        netloc += f":{parts.port}"
    ip_url = urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, ""))
    host_header = host if parts.port is None else f"{host}:{parts.port}"
    response = await client.get(
        ip_url,
        headers={"Host": host_header, "User-Agent": user_agent},
        extensions={"sni_hostname": host},
    )
    return response, None


async def _fetch_with_redirects(
    url: str,
    timeout: int,
    user_agent: str,
) -> tuple[str, str | None]:
    """Follow redirects with SSRF protection at each hop.

    Returns (html_text, None) on success, or ("", error_message) on failure.
    """
    try:
        async with httpx.AsyncClient(
            follow_redirects=False,
            timeout=timeout,
            headers={"User-Agent": user_agent},
        ) as client:
            current_url = url
            for _redirect_i in range(5):
                # Each hop resolves-then-connects to a validated public IP, so a
                # redirect target pointing at an internal address is blocked here.
                response, err = await _pinned_get(client, current_url, user_agent=user_agent)
                if err or response is None:
                    return "", err or "Fehler: Keine Antwort."
                if response.is_redirect:
                    location = response.headers.get("location", "")
                    if not location:
                        return "", "Fehler: Redirect ohne Location-Header."
                    # Resolve relative redirects
                    if location.startswith("/"):
                        parts = current_url.split("://", 1)
                        host_part = parts[1].split("/", 1)[0] if len(parts) > 1 else ""
                        location = f"{parts[0]}://{host_part}{location}"
                    elif not location.lower().startswith(("http://", "https://")):
                        return "", f"Fehler: URL-Schema in Redirect nicht erlaubt: {location}"
                    current_url = location
                    continue
                break
            else:
                return "", "Fehler: Zu viele Redirects (max 5)."
            if response is None:  # defensive: the loop only breaks with a response
                return "", "Fehler: Keine Antwort."
            response.raise_for_status()

            # Content-Type check
            content_type = response.headers.get("content-type", "")
            if not any(t in content_type for t in ("text/html", "text/plain", "application/xhtml")):
                return "", f"Fehler: Unerwarteter Content-Type '{content_type}'. Nur HTML/Text wird unterstuetzt."

            # Size check
            if len(response.content) > _MAX_RESPONSE_BYTES:
                return "", f"Fehler: Seite zu gross ({len(response.content)} Bytes, max {_MAX_RESPONSE_BYTES})."

            return response.text, None

    except httpx.TimeoutException:
        return "", f"Fehler: Timeout nach {timeout} Sekunden beim Laden von {url}"
    except httpx.HTTPStatusError as e:
        return "", f"Fehler: HTTP {e.response.status_code} beim Laden von {url}"
    except httpx.ConnectError:
        return "", f"Fehler: Verbindung zu {url} fehlgeschlagen."
    except Exception as e:
        return "", f"Fehler: {type(e).__name__}: {e}"


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

    url, err = _validate_url(url)
    if err:
        return err

    html, err = await _fetch_with_redirects(url, timeout, user_agent)
    if err:
        return err

    # Extract main text content
    try:
        text = trafilatura.extract(
            html,
            include_comments=False,
            include_tables=True,
            favor_recall=True,  # Lieber zu viel als zu wenig
            deduplicate=True,
        )
    except Exception as e:
        return f"Fehler bei Textextraktion: {type(e).__name__}: {e}"

    if not text or not text.strip():
        return f"Kein Textinhalt auf der Seite gefunden ({url})."

    # Truncate to max_chars
    text = text.strip()
    if len(text) > max_chars:
        # Cut at last sentence boundary before limit
        cut_text = text[:max_chars]
        last_period = cut_text.rfind(". ")
        if last_period > max_chars * 0.7:
            text = cut_text[: last_period + 1]
        else:
            text = cut_text + "..."
        text += f"\n\n[Gekuerzt auf {max_chars} Zeichen. Originaltext ist laenger.]"

    return text
