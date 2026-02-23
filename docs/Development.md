# Niles AI Core -- Development Guide

> **Stand:** 2026-02-23

---

## 1. Voraussetzungen

| Software | Version | Zweck |
| -------- | ------- | ----- |
| Python | >= 3.11 | Runtime |
| Docker Desktop | aktuell | Container (PostgreSQL, Evolution API, Caddy) |
| Ollama | >= 0.13 | Lokale LLM Inference (nativ auf Host) |
| Git | aktuell | Versionskontrolle |
| Tailwind CSS CLI | v3.4.17 | CSS Build (Standalone Binary, kein Node.js) |

---

## 2. Lokaler Setup

### Repository klonen

```bash
git clone <repo-url> Niles
cd Niles
```

### Python-Umgebung

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Environment konfigurieren

```bash
cp .env.example .env
```

Die `.env.example` dokumentiert jede Variable inline. Hier die Uebersicht, woher die Werte kommen:

**Pflicht:**

| Variable | Herkunft |
| -------- | -------- |
| `EVOLUTION_POSTGRES_PASSWORD` | Frei waehlbar. Wird beim ersten Start als DB-Passwort gesetzt. |
| `EVOLUTION_API_KEY` | Frei waehlbar. Authentifiziert Niles gegenueber Evolution API und Webhook. |

**Empfohlen (stabile Sessions ueber Restarts):**

| Variable | Herkunft |
| -------- | -------- |
| `NILES_API_KEY` | Frei waehlbar, z.B. `openssl rand -hex 32`. Auto-generiert wenn leer. |
| `SESSION_SECRET` | Frei waehlbar, z.B. `openssl rand -hex 64`. Auto-generiert wenn leer. |
| `BASE_URL` | Eigene URL, z.B. `https://niles.tail1d4a0f.ts.net`. Fuer OAuth Redirect URIs. |

**Google OAuth (fuer Web-UI Login + Google Calendar):**

| Variable | Herkunft |
| -------- | -------- |
| `GOOGLE_CLIENT_ID` | [Google Cloud Console](https://console.cloud.google.com/apis/credentials) > OAuth 2.0 Client erstellen. |
| `GOOGLE_CLIENT_SECRET` | Gleiche Stelle. Redirect URIs: `<BASE_URL>/ui/callback/google` und `<BASE_URL>/ui/callback/google/calendar`. |
| `GOOGLE_ALLOWED_EMAILS` | Komma-separierte Whitelist, z.B. `user@gmail.com`. Leer = alle Google-Accounts erlaubt. |

**CardDAV / CalDAV (Kontakt- und Kalender-Sync):**

| Variable | Herkunft |
| -------- | -------- |
| `CARDDAV_USER` / `CARDDAV_PASSWORD` | Login-Daten des CardDAV-Anbieters (z.B. mailbox.org). Alternativ ueber Web-UI konfigurierbar. |
| `CALDAV_*` | Legacy. Wird beim ersten Start automatisch in die DB migriert. Neue Kalenderquellen ueber Web-UI (Settings > Kalenderquellen). |

**Vikunja (Todo/Task Management):**

| Variable | Herkunft |
| -------- | -------- |
| `VIKUNJA_JWT_SECRET` | Frei waehlbar, z.B. `openssl rand -hex 32`. Wird nur vom Vikunja-Container gebraucht. |
| `VIKUNJA_API_URL` | Fix: `http://vikunja:3456/api/v1` (Docker-interner Hostname). |
| `VIKUNJA_API_TOKEN` | In Vikunja Web-UI generieren: Settings > API Tokens > Create Token. Siehe Vikunja-Setup unten. |
| `FEATURE_VIKUNJA` | `true` zum Aktivieren, `false` zum Deaktivieren. |

Vollstaendige Settings-Tabelle mit Defaults: [Niles-Core-Spec.md §6.1](Niles-Core-Spec.md#61-settings).

### Ollama

1. Ollama installieren: `brew install ollama`
2. Modell laden: `ollama pull llama3.1:8b`
3. Ollama laeuft automatisch auf Port 11434

### Vikunja (optional -- Todo/Task Management)

Vikunja laeuft als separater Docker-Container. Die Datenbank `vikunja_db` wird von `./scripts/start.sh` automatisch erstellt.

**Ersteinrichtung:**

1. **JWT Secret generieren** (fuer stabile Login-Sessions ueber Restarts):

    ```bash
    openssl rand -hex 32
    ```

    Ergebnis in `.env` eintragen:

    ```bash
    VIKUNJA_JWT_SECRET=<generierter-hex-string>
    ```

2. **Weitere `.env`-Variablen setzen:**

    ```bash
    VIKUNJA_API_URL=http://vikunja:3456/api/v1
    VIKUNJA_API_TOKEN=               # kommt in Schritt 5
    FEATURE_VIKUNJA=true
    ```

    **Wichtig:** `VIKUNJA_API_URL` muss den Docker-internen Hostnamen `vikunja` verwenden (nicht `localhost`). Niles Core erreicht Vikunja ueber das Docker-Netzwerk.

3. **Container starten:**

    ```bash
    ./scripts/start.sh
    ```

    Erstellt automatisch die `vikunja_db` Datenbank. Beim allerersten Start ist die Registrierung in `docker-compose.yml` aktiviert (`ENABLEREGISTRATION: "true"`).

4. **Admin-Account erstellen:** Vikunja Web-UI oeffnen unter `http://localhost:3456` (oder `http://<tailscale-ip>:3456` bei Remote-Zugriff). Auf "Konto erstellen" klicken, Username und Passwort waehlen.

    Nach der Registrierung: Ein Standard-Projekt anlegen (z.B. "Inbox").

    **Danach Registrierung deaktivieren** in `docker-compose.yml`:

    ```yaml
    VIKUNJA_SERVICE_ENABLEREGISTRATION: "false"
    ```

5. **API-Token generieren:** In Vikunja einloggen, dann: Settings > API Tokens > Create Token. Rechte: mindestens `tasks` (Read + Write). Den generierten Token in `.env` eintragen:

    ```bash
    VIKUNJA_API_TOKEN=<token-aus-vikunja>
    ```

6. **Niles neu starten:**

    ```bash
    ./scripts/start.sh
    ```

    `start.sh` gibt einen Hinweis aus, falls `FEATURE_VIKUNJA=true` aber `VIKUNJA_API_TOKEN` noch leer ist.

**Verifizierung:** Im Chat "Was steht auf meiner Todo-Liste?" fragen -- Niles ruft `list_tasks` auf.

**Deaktivieren:** `FEATURE_VIKUNJA=false` in `.env` oder ueber die Web-UI (Settings). Task-Tools werden dann nicht an das LLM gesendet.

---

## 3. Tailwind CSS (Frontend-Styling)

Templates verwenden Tailwind CSS Utility Classes. Die generierte `style.css` wird von FastAPI als statische Datei serviert.

### Tailwind CLI (Standalone, kein Node.js)

```bash
# macOS ARM64:
curl -sLO https://github.com/tailwindlabs/tailwindcss/releases/download/v3.4.17/tailwindcss-macos-arm64
chmod +x tailwindcss-macos-arm64
mv tailwindcss-macos-arm64 tailwindcss
```

### CSS bauen

```bash
# Einmaliger Build:
./tailwindcss --minify -i src/niles/static/css/input.css -o src/niles/static/css/style.css

# Watch-Modus (bei Template-Aenderungen):
./tailwindcss --watch -i src/niles/static/css/input.css -o src/niles/static/css/style.css
```

### Docker Build

Im Dockerfile wird Tailwind CLI automatisch heruntergeladen und CSS gebaut (`python urllib.request.urlretrieve`). Bei Aenderungen an Templates oder `input.css` muss das Docker-Image neu gebaut werden -- oder `style.css` lokal gebaut und via Volume-Mount bereitgestellt werden.

**Konfiguration:** `tailwind.config.js` im Projekt-Root definiert Content-Pfade und Dark Mode (`class`).

---

## 4. Entwicklung starten

### Variante A: Lokal (ohne Docker)

```bash
./scripts/dev.sh
```

Startet uvicorn mit Auto-Reload auf `http://127.0.0.1:8000`. Setzt voraus, dass PostgreSQL und Evolution API extern laufen (z.B. via Docker).

### Variante B: Docker (komplett)

```bash
./scripts/start.sh
```

Startet alle Container (PostgreSQL, Evolution API, Niles Core, Caddy). Niles Core laeuft mit Volume-Mount und `--reload` fuer Live-Reload bei Code-Aenderungen.

**HTTPS:** Caddy terminiert TLS mit self-signed Zertifikaten. Fuer lokales Testen `--insecure` bei curl verwenden:

```bash
curl -k https://localhost/health
curl -k -X POST https://localhost/chat \
  -H "X-API-Key: <KEY>" \
  -H "Content-Type: application/json" \
  -d '{"message": "Test"}'
```

**Web-UI:** `https://localhost/ui/login` im Browser oeffnen.

Alternativ direkt ueber den Docker-internen Port (ohne TLS): `docker exec niles_core curl http://localhost:8000/health`

**Postgres Debugging:** Der Postgres-Port ist standardmaessig nicht erreichbar. Um direkt auf die Datenbank zuzugreifen (z.B. via `psql`), in `.env` setzen:

```bash
POSTGRES_HOST_PORT=5432
```

Dann: `psql -h 127.0.0.1 -U evolution -d evolution_db`

### Status pruefen

```bash
./scripts/status.sh
```

### Stoppen

```bash
./scripts/stop.sh
```

---

## 5. Tests

### Ausfuehren

```bash
./scripts/test.sh
```

Oder direkt:

```bash
source .venv/bin/activate
python -m pytest tests/ -v
```

### Teststruktur

```text
tests/
├── conftest.py                  # Shared Fixtures (Environment-Variablen)
├── test_config.py               # Settings-Validierung
├── test_contacts.py             # ContactsAction, normalize_phone, Multi-Phone
├── test_core.py                 # NilesAgent, Tool-Call-Pipeline, Text-Tool-Call-Fallback
├── test_health.py               # GET /health Endpoint
├── test_memory.py               # MemoryStore, ConversationHistory
├── test_features.py             # Feature Flags + Webhook Auth
├── test_carddav.py              # CardDAV Sync
├── test_caldav.py               # CalDAV Sync
├── test_ical_parser.py          # iCalendar Parser
├── test_rrule_expansion.py      # RRULE Expansion (Wiederkehrende Termine)
├── test_calendar_manager.py     # CalendarSourceManager (CRUD, Sync, Migration)
├── test_calendar_improvements.py # Kalender Query-Verbesserungen
├── test_google_auth.py          # Google Calendar OAuth (Token Refresh)
├── test_mcp.py                  # MCP Integration
├── test_security.py             # API Auth, Rate Limiting
├── test_settings_store.py       # Runtime Settings Store
├── test_web.py                  # Web-UI, Google OAuth, Sessions, CSRF
├── test_whatsapp_sessions.py    # Per-User WhatsApp Sessions
├── test_tasks.py                # Vikunja Task Management
└── test_vikunja_store.py        # Per-User Vikunja Credentials + Agent Resolution
```

### Konventionen

- Framework: pytest mit `pytest-asyncio`
- `asyncio_mode = "auto"` in `pyproject.toml` (kein `@pytest.mark.asyncio` noetig)
- Externe Dependencies (PostgreSQL, LLM) werden mit `unittest.mock.AsyncMock` gemockt
- `conftest.py` setzt Pflicht-Environment-Variablen via `monkeypatch`
- Testdateien: `tests/test_<modul>.py`
- Testklassen: `class Test<Klasse>:`
- Web-UI Tests verwenden signierte Session-Tokens via `itsdangerous.URLSafeTimedSerializer` mit separatem `_TEST_SESSION_SECRET`

---

## 6. Docker-Workflow

### Build

```bash
docker compose -f docker/docker-compose.yml --env-file .env build niles_core
```

### Logs

```bash
# Alle Container
docker compose -f docker/docker-compose.yml logs -f

# Nur Niles Core
docker compose -f docker/docker-compose.yml logs -f niles_core
```

### Neustart nach Aenderungen

Bei Aenderungen an `src/` ist kein Neustart noetig (Volume-Mount + `--reload`). Bei Aenderungen an `pyproject.toml` (neue Dependencies) muss der Container neu gebaut werden:

```bash
docker compose -f docker/docker-compose.yml --env-file .env up -d --build niles_core
```

---

## 7. Neue Komponente hinzufuegen

### Neues Tool (Agent-Faehigkeit)

1. Tool-Definition in `src/niles/agent/core.py` zur `TOOLS`-Liste hinzufuegen (OpenAI Function-Calling Format)
2. Handler in `NilesAgent._execute_tool_call()` ergaenzen
3. Tests in `tests/test_agent.py` (oder neue Testdatei)

### Neue Action (externe Integration)

1. Datei `src/niles/actions/<name>.py` erstellen
2. Klasse mit async Methoden implementieren
3. In `main.py` Lifespan instanziieren und an Agent uebergeben
4. Tests mit gemockten externen Aufrufen

### Neue Event-Source

1. Datei `src/niles/sources/<name>.py` erstellen
2. FastAPI-Router mit Webhook-Endpoint
3. Event-Dict erstellen und an `agent.process_event()` uebergeben
4. Router in `main.py` einbinden: `app.include_router(router)`

---

## 8. Konventionen

### Sprache

- **Code:** Englisch (Variablen, Funktionen, Kommentare, Docstrings)
- **Agent-Prompts:** Deutsch (soul.md, Tool-Beschreibungen)
- **Dokumentation:** Deutsch
- **Web-UI Labels:** Deutsch (Zielsprache des End-Users)

### Async

- Alle I/O-Operationen sind `async`
- PostgreSQL via `asyncpg` (Connection Pool)
- HTTP via `httpx.AsyncClient`
- LLM via `openai.AsyncOpenAI`

### Fehlerbehandlung

- Webhook-Handler: Exceptions fangen und loggen, immer HTTP 200 zurueckgeben
- Web-UI: Agent-Fehler abfangen, Fehlermeldung im Chat anzeigen
- LLM-Fehler: Fehlermeldung an User, kein Exception-Propagation
- Tool-Call-Fehler: `{"error": "..."}` als Tool-Result zurueck an LLM
- Startup: `ValidationError` bei fehlenden Pflicht-Variablen -> `sys.exit(1)`

### Text-basierter Tool-Call Fallback

Kleinere lokale LLMs (z.B. `llama3.1:8b` via Ollama) nutzen manchmal nicht die Function-Calling-API, sondern geben den Tool-Call als JSON-Text aus:

```json
{"name": "create_task", "parameters": {"title": "Einkaufen", "due_date": "2026-02-24"}}
```

`NilesAgent._try_parse_text_tool_call()` erkennt solche Antworten und fuehrt den Tool-Call trotzdem aus. Im Streaming-Modus werden JSON-artige Antworten gepuffert (nicht sofort an den User gestreamt), damit kein rohes JSON in der Chat-Bubble erscheint.

Hinweis: LLM-Parameter werden dabei manchmal als String statt als korrektem Typ geliefert (z.B. `"priority": "0"` statt `"priority": 0`). Actions muessen solche Typen robust handhaben (`int()` mit Fallback).

### Logging

- `logging.getLogger(__name__)` in jedem Modul
- Level konfigurierbar via `LOG_LEVEL` Environment-Variable
- Format: `%(asctime)s %(levelname)s %(name)s: %(message)s`

---

## 9. Weitere Dokumentation

- [Technische Spezifikation](Niles-Core-Spec.md) -- Architektur, Komponenten, Konfiguration, Roadmap
- [API Reference](API.md) -- Endpoints, Payloads, Beispiele
