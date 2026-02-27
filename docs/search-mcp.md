# Niles AI — Web Search via MCP + SearXNG

> **Version:** 1.0
> **Date:** 2026-02-27
> **Scope:** Web-Recherche-Fähigkeit für Niles via MCP-Server + self-hosted SearXNG
> **Aufwand:** ~1 Tag
> **Voraussetzung:** Niles-Core-Spec v7.3, MCP-Infrastruktur funktionsfähig (Weather-Server als Referenz)

---

## 1. Entscheidung

### Gewählt: SearXNG (self-hosted) + `searxng-simple-mcp`

| Kriterium | SearXNG | Brave Search | Tavily |
|-----------|---------|-------------|--------|
| Privacy / Lokal | ✅ Self-hosted, kein API-Key | ❌ Cloud API | ❌ Cloud API |
| Kosten | ✅ Kostenlos | ⚠️ Free Tier 2.000/Monat | ⚠️ Free Tier 1.000/Monat |
| Niles-Prinzip "100% Local" | ✅ Passt | ❌ Bricht Prinzip | ❌ Bricht Prinzip |
| Setup-Aufwand | ⚠️ Docker-Container extra | ✅ Nur API-Key | ✅ Nur API-Key |
| MCP-Server verfügbar | ✅ `searxng-simple-mcp` (PyPI, MIT, stdio) | ✅ Mehrere | ✅ Offiziell |
| Qualität der Ergebnisse | ⚠️ Meta-Suchmaschine (Google, Bing, DuckDuckGo) | ✅ Eigener Index | ✅ AI-optimiert |

**Begründung:** SearXNG ist die einzige Option, die zum Niles-Kernprinzip "100% Local / Privacy First" passt. Kein API-Key, keine Cloud-Abhängigkeit, keine Kosten. Die Ergebnisqualität ist gut genug (aggregiert Google, Bing, DuckDuckGo).

### MCP-Server: `searxng-simple-mcp`

- **Quelle:** [github.com/Sacode/searxng-simple-mcp](https://github.com/Sacode/searxng-simple-mcp)
- **Lizenz:** MIT
- **Transport:** stdio (passt zu Niles MCPManager)
- **Python:** >= 3.10 (kompatibel)
- **PyPI:** `searxng-simple-mcp`
- **Tools exposed:** `search` (query, max_results, language, time_range)
- **Design:** Minimalistisch, optimiert für LLM-Kontext (wenig Token-Verbrauch)

---

## 2. Architektur

### Datenfluss

```
User: "Recherchiere aktuelle Entwicklungen bei Apple Vision Pro"
    │
    v
NilesAgent (agent/core.py)
    │ Tool-Call-Loop
    v
MCPManager.call_tool("mcp__searxng__search", {"query": "Apple Vision Pro 2026"})
    │ stdio
    v
searxng-simple-mcp (Python-Prozess)
    │ HTTP GET
    v
SearXNG (Docker-Container, Port 8888)
    │ aggregiert
    v
Google, Bing, DuckDuckGo, Wikipedia, ...
    │
    v
Ergebnisse → MCPManager → Agent → LLM fasst zusammen → User
```

### Docker-Netzwerk

```
niles_network (bridge)
├── niles_core          :8000
├── evolution_postgres  :5432
├── evolution_api       :8080
├── vikunja             :3456
├── niles_caddy         :443, :8443
├── signal_api          :8080  (optional)
└── searxng             :8888  (NEU)
```

SearXNG läuft im selben Docker-Netzwerk. Der MCP-Server `searxng-simple-mcp` läuft als stdio-Prozess innerhalb des `niles_core`-Containers und greift auf SearXNG via `http://searxng:8888` zu.

---

## 3. Implementierungsplan

### Step 1: SearXNG Docker-Service hinzufügen

**Datei:** `docker/docker-compose.yml`

```yaml
  # SearXNG (Privacy-focused meta search engine)
  searxng:
    image: searxng/searxng:latest
    container_name: niles_searxng
    restart: unless-stopped
    # No port exposed — access only via Docker network
    environment:
      - SEARXNG_BASE_URL=http://searxng:8888/
    volumes:
      - searxng_data:/etc/searxng
    networks:
      - niles_network
    profiles:
      - search
```

**Volume:**

```yaml
volumes:
  # ... existing volumes ...
  searxng_data:
```

**Profil `search`:** Wie bei Signal (`profiles: [signal]`) — SearXNG startet nur wenn aktiviert. Aktivierung via `docker compose --profile search up`.

[Nicht verifiziert] Das SearXNG-Image ist ~150-200 MB RAM im Betrieb. Auf einem Mac Mini M4 mit 16 GB kein Problem.

### Step 2: SearXNG-Konfiguration

**Datei:** `config/searxng/settings.yml` (neu, gemounted in Container)

```yaml
general:
  instance_name: "Niles Search"
  debug: false

search:
  safe_search: 0
  default_lang: "de"
  formats:
    - html
    - json       # Wichtig: JSON-API für MCP-Server

server:
  port: 8888
  bind_address: "0.0.0.0"
  secret_key: "niles-searxng-secret-change-me"

engines:
  # Aktivierte Suchmaschinen (nur die zuverlässigsten)
  - name: google
    engine: google
    shortcut: g
    disabled: false
  - name: duckduckgo
    engine: duckduckgo
    shortcut: ddg
    disabled: false
  - name: wikipedia
    engine: wikipedia
    shortcut: wp
    disabled: false
  - name: bing
    engine: bing
    shortcut: bi
    disabled: false
```

**Volume-Mount Update** in docker-compose.yml:

```yaml
    volumes:
      - searxng_data:/etc/searxng
      - ../config/searxng/settings.yml:/etc/searxng/settings.yml:ro
```

### Step 3: MCP-Server-Dependency installieren

**Datei:** `pyproject.toml`

```toml
dependencies = [
    # ... existing ...
    # MCP Web Search (SearXNG client, optional — only used when searxng configured)
    "searxng-simple-mcp>=0.3.0",
]
```

**Datei:** `docker/Dockerfile.niles` — keine Änderung nötig, da `uv pip install --system .` die neue Dependency automatisch installiert.

### Step 4: Feature-Flag hinzufügen

**Datei:** `src/niles/config.py`

```python
    # Web Search (SearXNG)
    feature_search: bool = False
    searxng_url: str = "http://searxng:8888"
```

**Datei:** `.env.example`

```bash
# Web Search (SearXNG, optional)
# FEATURE_SEARCH=true
# SEARXNG_URL=http://searxng:8888
```

### Step 5: MCP-Server-Konfiguration

**Datei:** `config/mcp_servers.yaml`

```yaml
servers:
  weather:
    command: python
    args: ["-m", "niles.mcp.weather"]
    env:
      WEATHER_LATITUDE: "${WEATHER_LATITUDE}"
      WEATHER_LONGITUDE: "${WEATHER_LONGITUDE}"
      WEATHER_TIMEZONE: "${WEATHER_TIMEZONE}"

  # Web Search via SearXNG (aktiviert wenn FEATURE_SEARCH=true)
  searxng:
    command: python
    args: ["-m", "searxng_simple_mcp.server", "--searxng-url", "${SEARXNG_URL}"]
    env:
      SEARXNG_MCP_SEARXNG_URL: "${SEARXNG_URL}"
      SEARXNG_MCP_MAX_RESULTS: "10"
      SEARXNG_MCP_LANGUAGE: "de"
```

### Step 6: Bedingtes MCP-Server-Laden

**Problem:** Aktuell lädt `MCPManager.start_all()` alle Server aus der YAML. Der SearXNG-Server soll nur starten wenn `feature_search=true`.

**Lösung A (einfach, empfohlen):** Feature-Flag-Check in `main.py` lifespan, vor MCP start. Wenn `feature_search=false`, SearXNG-Eintrag temporär aus der Config entfernen.

**Lösung B (sauberer, mehr Aufwand):** `mcp_servers.yaml` um ein `enabled`-Feld erweitern:

```yaml
  searxng:
    command: python
    args: ["-m", "searxng_simple_mcp.server"]
    enabled: "${FEATURE_SEARCH}"    # Nur starten wenn true
    env:
      SEARXNG_MCP_SEARXNG_URL: "${SEARXNG_URL}"
```

Dann in `MCPManager._load_config()`:

```python
for name, config in servers.items():
    enabled = config.get("enabled", "true")
    if isinstance(enabled, str):
        enabled = _expand_env(enabled)
    if str(enabled).lower() not in ("true", "1", "yes"):
        logger.info("MCP server '%s' disabled via config", name)
        continue
    # ... start server
```

**Empfehlung:** Lösung B. Generisch, wiederverwendbar für alle zukünftigen MCP-Server. Kleiner Eingriff in `client.py` (5 Zeilen).

### Step 7: soul.md Recherche-Anweisung

**Datei:** `config/soul.md` — neuer Abschnitt:

```markdown
### Web-Recherche

- Du hast Zugriff auf eine Websuche (SearXNG). Nutze sie wenn der Benutzer:
  - "recherchiere", "suche im Internet", "google mal" sagt
  - nach aktuellen Ereignissen, Nachrichten oder Preisen fragt
  - nach Informationen fragt die du nicht sicher weißt
- Rufe das `mcp__searxng__search`-Tool auf mit einer präzisen Suchanfrage
- Fasse die Ergebnisse in 3-5 Kernpunkten zusammen
- Nenne die Quellen (Titel + URL) am Ende
- Wenn die erste Suche nicht genug ergibt, suche nochmal mit anderen Begriffen
- Sage dem Benutzer ehrlich wenn du nichts Relevantes findest
- Erfinde NIEMALS Suchergebnisse
```

### Step 8: Settings UI (optional, aber empfehlenswert)

Analog zu Signal: Ein Toggle `feature_search` in der Settings-Seite.

**Datei:** `src/niles/settings_store.py` — `EDITABLE_SETTINGS` erweitern:

```python
EDITABLE_SETTINGS = {
    # ... existing ...
    "feature_search",
    "searxng_url",
}
```

**Datei:** `src/niles/templates/settings.html` — neuer Abschnitt "Web Search" mit Toggle + URL-Feld.

---

## 4. Dateien-Übersicht

### Neue Dateien

| Datei | Zweck |
|-------|-------|
| `config/searxng/settings.yml` | SearXNG-Konfiguration (Engines, Sprache, JSON-API) |

### Geänderte Dateien

| Datei | Änderung |
|-------|----------|
| `docker/docker-compose.yml` | SearXNG-Service + Volume + Profile `search` |
| `pyproject.toml` | `searxng-simple-mcp>=0.3.0` Dependency |
| `src/niles/config.py` | `feature_search`, `searxng_url` Settings |
| `.env.example` | `FEATURE_SEARCH`, `SEARXNG_URL` Dokumentation |
| `config/mcp_servers.yaml` | SearXNG-Server-Eintrag mit `enabled`-Flag |
| `src/niles/mcp/client.py` | `enabled`-Feld Support in `_load_config()` (~5 Zeilen) |
| `config/soul.md` | Recherche-Anweisungen für den Agent |
| `src/niles/settings_store.py` | `feature_search`, `searxng_url` als editable |
| `src/niles/templates/settings.html` | Web Search Toggle + URL (analog Signal-Section) |
| `docs/Deployment.md` | Neuer Abschnitt "Web Search (SearXNG)" |
| `docs/Niles-Core-Spec.md` | SearXNG in Infrastruktur-Tabelle + MCP-Section |

---

## 5. Start-Prozedur

### Erstmalige Aktivierung

```bash
# 1. .env ergänzen
FEATURE_SEARCH=true
SEARXNG_URL=http://searxng:8888

# 2. Start mit search-Profil
docker compose -f docker/docker-compose.yml --profile search --env-file .env up -d

# 3. SearXNG Health-Check
curl -s http://localhost:8888/healthz
# Oder intern: docker exec niles_core curl -s http://searxng:8888/healthz
```

### Alternativ via Settings UI

1. Settings > Web Search > Toggle ON
2. URL: `http://searxng:8888` (default)
3. Niles startet den MCP-Server beim nächsten Restart automatisch

---

## 6. Risiken und Mitigationen

| Risiko | Wahrscheinlichkeit | Mitigation |
|--------|-------------------|------------|
| llama3.1:8b ruft das Search-Tool nicht zuverlässig auf | **Hoch** | soul.md Anweisungen so explizit wie möglich. Text-Tool-Call-Fallback existiert bereits. Langfristig: LLM-Evaluierung (Roadmap #10) |
| SearXNG wird von Google/Bing rate-limited | Mittel | Nur bei sehr häufiger Nutzung. SearXNG hat eingebautes Rate-Limiting. Bei Bedarf: Engines rotieren |
| `searxng-simple-mcp` wird nicht mehr gepflegt | Niedrig | MIT-Lizenz, Code ist einfach (~200 Zeilen). Kann bei Bedarf geforkt oder durch eigenen MCP-Server ersetzt werden (Pattern: `mcp/weather/server.py`) |
| SearXNG-Container verbraucht zu viel RAM | Niedrig | ~150-200 MB. Profile-basiert — nur aktiv wenn gewünscht |
| Suchergebnisse enthalten problematische Inhalte | Mittel | SearXNG `safe_search` konfigurierbar. LLM filtert via soul.md |

---

## 7. Verifikation

- [ ] `docker compose --profile search up -d` — SearXNG startet
- [ ] `curl http://searxng:8888/search?q=test&format=json` — gibt JSON zurück
- [ ] MCP-Server wird in Logs registriert: `MCP server 'searxng' started (X/Y tools registered)`
- [ ] Web-UI Chat: "Recherchiere aktuelle Nachrichten zu Apple" → Agent ruft Search-Tool auf
- [ ] WhatsApp Self-Chat: "Hey Niles, suche im Internet nach..." → funktioniert
- [ ] Signal Self-Chat: "Hey Niles, google mal..." → funktioniert
- [ ] `FEATURE_SEARCH=false` → SearXNG-MCP-Server wird NICHT gestartet
- [ ] Alle 455 bestehenden Tests bestehen weiterhin
- [ ] `ruff check src/ tests/` — keine Lint-Fehler

---

## 8. Zukünftige Erweiterungen

| Erweiterung | Aufwand | Trigger |
|-------------|---------|---------|
| `web_fetch`-Tool (URL-Inhalte lesen) | 1 Tag | User fragt "lies diese URL" |
| Brave Search als Alternative (Cloud) | 0,5 Tag | User will bessere Ergebnisqualität |
| Multi-Step Research Mode | 3-5 Tage | Nach LLM-Evaluierung (stärkeres Modell) |
| Ergebnisse in Memory speichern | 0,5 Tag | "Merke dir die Ergebnisse dieser Recherche" |