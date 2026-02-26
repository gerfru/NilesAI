# Niles AI — 12-Factor App Vergleich

> **Quelle 12-Factor:** [12factor.net](https://12factor.net/) (Adam Wiggins, Heroku, 2011)  
> **Quelle Niles:** Niles-Core-Spec v7.1, Deployment Guide, Development Guide, docker-compose.yml, config.py, main.py

---

## Übersicht

| # | Factor | Status | Bewertung |
|---|--------|--------|-----------|
| I | Codebase | ✅ Erfüllt | Ein Repo, multiple Deploys |
| II | Dependencies | ✅ Erfüllt | pyproject.toml + Docker |
| III | Config | ✅ Erfüllt | .env + Pydantic Settings, Caddyfile via Env-Vars |
| IV | Backing Services | ✅ Erfüllt | Alle als attached resources |
| V | Build, Release, Run | ✅ Erfüllt | Versionierte Images, Dev/Prod getrennt |
| VI | Processes | ⚠️ Teilweise | Stateless-Prinzip, In-Memory State dokumentiert |
| VII | Port Binding | ✅ Erfüllt | FastAPI/Uvicorn self-contained |
| VIII | Concurrency | ⚠️ Teilweise | Single-Instance Design (dokumentiert) |
| IX | Disposability | ✅ Erfüllt | Graceful Shutdown mit SSE-Drain |
| X | Dev/Prod Parity | ✅ Erfüllt | Docker Compose, gleiche Backing Services |
| XI | Logs | ✅ Erfüllt | Strukturiertes JSON-Logging, Request-IDs, Prometheus-Metriken |
| XII | Admin Processes | ✅ Erfüllt | Scripts im Repo |

**Ergebnis: 10 von 12 vollständig erfüllt, 2 teilweise (dokumentierte Einschränkungen für Single-Instance).**

---

## Detailanalyse pro Factor

### I. Codebase — "One codebase tracked in revision control, many deploys"

**12-Factor fordert:** Ein Codebase in einem VCS (Git), mehrere Deploys (Dev, Staging, Prod) aus derselben Codebasis.

**Niles-Status: ✅ Erfüllt**

**Nachweis (Projektdokumentation):**
- Ein Git-Repository (`git clone <repo-url> Niles`)
- `.github/workflows/claude.yml` zeigt CI/CD-Integration (Claude Code GitHub Action)
- Derselbe Code wird lokal (`./scripts/dev.sh`) und in Docker (`./scripts/start.sh`) deployed
- Development Guide dokumentiert beide Modi: "Option A: Local" und "Option B: Docker"

**Was gut ist:** Klare 1:1-Beziehung zwischen Repo und App. Kein geteilter Code mit anderen Projekten.

---

### II. Dependencies — "Explicitly declare and isolate dependencies"

**12-Factor fordert:** Alle Dependencies explizit deklariert (z.B. in einem Manifest) und isoliert (keine impliziten System-Dependencies).

**Niles-Status: ✅ Erfüllt**

**Nachweis (Niles-Core-Spec v7.1, Abschnitt 8):**
- `pyproject.toml` deklariert alle Python-Dependencies mit Mindestversionen:
  ```
  fastapi>=0.129.0, uvicorn>=0.41.0, httpx>=0.28.1,
  asyncpg>=0.31.0, openai>=2.21.0, mcp>=1.26.0, etc.
  ```
- Dev-Dependencies separat: `pytest>=9.0.0, pytest-asyncio>=1.3.0`
- Docker-Container isoliert die Runtime vollständig
- Tailwind CSS als Standalone-Binary (kein Node.js nötig)
- Python venv für lokale Entwicklung: `python3 -m venv .venv`

**Was gut ist:** Keine impliziten System-Packages. Sowohl Declaration (pyproject.toml) als auch Isolation (Docker/venv) vorhanden.

---

### III. Config — "Store config in the environment"

**12-Factor fordert:** Konfiguration wird in Umgebungsvariablen gespeichert, nicht im Code. Strikte Trennung von Code und Config.

**Niles-Status: ✅ Erfüllt**

**Nachweis (src/niles/config.py):**
- Pydantic `BaseSettings` mit `env_file = ".env"` — alle Config kommt aus Environment-Variablen
- Keine Credentials im Code. Secrets werden generiert falls nicht gesetzt:
  ```python
  niles_api_key: str = Field(default_factory=lambda: secrets.token_urlsafe(32))
  session_secret: str = Field(default_factory=lambda: secrets.token_urlsafe(64))
  ```
- `docker-compose.yml` übergibt alle Config als Environment-Variablen
- Tests validieren: `test_settings_from_env()` prüft, dass Settings aus `monkeypatch.setenv` gelesen werden
- `test_settings_missing_postgres_password()` und `test_settings_missing_api_key()` prüfen Fehler bei fehlender Config
- Runtime-Overrides über `settings_overrides`-Tabelle in PostgreSQL (Web UI editierbar)
- Credential-Whitelist (`EDITABLE_SETTINGS`) verhindert Runtime-Änderung von Secrets

**Was gut ist:** Saubere Trennung. Kein einziger Credential-Wert ist hartkodiert. `.env.example` als Template.

**Hinweis:** Die `docker-compose.yml` enthält hardkodierte IPs im Caddyfile (`192.168.1.100`, `192.168.1.100`). Diese müssten pro Deployment angepasst werden. Das ist ein kleiner Verstoß gegen das Config-Prinzip — die IPs gehören in die `.env`.

---

### IV. Backing Services — "Treat backing services as attached resources"

**12-Factor fordert:** Backing Services (DB, Message Queue, etc.) werden als angehängte Ressourcen behandelt, austauschbar über Config-Änderung.

**Niles-Status: ✅ Erfüllt**

**Nachweis (Niles-Core-Spec v7.1, config.py):**

Alle externen Services sind via URL/Credentials konfigurierbar:

| Backing Service | Config-Variable | Austauschbar? |
|----------------|----------------|---------------|
| PostgreSQL | `postgres_host`, `postgres_port`, `postgres_password` | ✅ Ja |
| Ollama (LLM) | `llm_base_url`, `llm_model` | ✅ Ja (auch Cloud-kompatibel via OpenAI SDK) |
| Evolution API | `evolution_api_url`, `evolution_api_key` | ✅ Ja |
| Vikunja | `vikunja_api_url`, `vikunja_api_token` | ✅ Ja |
| CalDAV | `caldav_url`, `caldav_user`, `caldav_password` | ✅ Ja |
| CardDAV | `carddav_url`, `carddav_user`, `carddav_password` | ✅ Ja |
| Google Calendar | `google_client_id`, `google_client_secret` | ✅ Ja |

**Was gut ist:** Kein einziger Backing Service ist hardkodiert. Wechsel z.B. von lokalem Ollama zu Cloud-API erfordert nur Änderung von `LLM_BASE_URL` und `LLM_MODEL`.

---

### V. Build, Release, Run — "Strictly separate build and run stages"

**12-Factor fordert:** Drei strikt getrennte Phasen: Build (Code → Artefakt), Release (Artefakt + Config), Run (Release ausführen).

**Niles-Status: ✅ Erfüllt**

**Was vorhanden ist:**
- **Build:** `docker compose build niles_core` erstellt ein Docker-Image (inkl. Tailwind CSS Build). `scripts/build.sh` extrahiert die Version aus `pyproject.toml` und taggt das Image automatisch (z.B. `niles-core:0.1.0`).
- **Release:** Docker-Image wird mit `image: niles-core:${NILES_VERSION:-latest}` versioniert. Drittanbieter-Images sind gepinnt (Evolution API v2.3.7, PostgreSQL 15-alpine, Vikunja 1.1.0).
- **Run:** `docker compose up` startet die Container. Prod-Config nutzt das Dockerfile CMD (kein `--reload`). Dev-Modus über `scripts/dev.sh` (lokales Uvicorn).
- **Rollback:** Über Git-Tags und Docker-Image-Tags möglich: `git checkout v0.1.0 && ./scripts/build.sh && ./scripts/start.sh`

---

### VI. Processes — "Execute the app as one or more stateless processes"

**12-Factor fordert:** Prozesse sind stateless und share-nothing. Persistenter State gehört in Backing Services.

**Niles-Status: ⚠️ Teilweise erfüllt**

**Was stateless ist:**
- Chat-History in PostgreSQL (nicht im Prozess-Memory)
- Memory/Key-Value-Store in PostgreSQL
- User Sessions als signierte Cookies (kein Server-Side Session Store)
- Settings in PostgreSQL (`settings_overrides`-Tabelle)

**Was nicht stateless ist (vollständige Liste):**

| Store | Datei | Zweck | Multi-Worker-sicher? |
|-------|-------|-------|---------------------|
| `RateLimitMiddleware._hits` | `main.py:309` | Allgemeines Rate-Limiting (60 rpm), Max 10.000 IPs, LRU-Eviction | ❌ Nein |
| `_login_attempts` | `web.py:52` | Login-Brute-Force-Schutz (5 Versuche/5 Min) | ❌ Nein |
| `APScheduler` | `main.py:163` | Cron-Job-Scheduling (ohne persistenten Store) | ❌ Nein (doppelte Jobs) |
| `MCPManager._sessions` | `mcp/client.py:61` | MCP-Server-Verbindungen | ❌ Nein |
| `_pending_phone_choices` | `agent/core.py:349` | WhatsApp-Kontaktauswahl-State (5 Min TTL) | ❌ Nein |
| `_source_names_cache` | `agent/core.py:345` | Kalendernamen-Cache (5 Min TTL) | ✅ Ja (readonly Cache) |
| `_sent_ids` | `whatsapp.py:27` | Echo-Loop-Guard für gesendete Nachrichten (10s TTL) | ❌ Nein |

**Bewertung:** Für die aktuelle Single-Instance-Anwendung ist das pragmatisch und kein Problem. Für horizontale Skalierung (mehrere Instanzen) müssten Rate Limiter und Echo-Guard in Redis o.ä. verschoben werden. Scheduler bräuchte einen persistenten Job-Store. Die übrigen Stores (MCP, Phone-Choices) sind architekturbedingt per-Prozess.

---

### VII. Port Binding — "Export services via port binding"

**12-Factor fordert:** Die App ist self-contained und exportiert HTTP (oder andere Protokolle) durch Binding an einen Port.

**Niles-Status: ✅ Erfüllt**

**Nachweis:**
- FastAPI + Uvicorn bindet an Port 8000:
  ```yaml
  # docker-compose.yml
  command: >-
    sh -c "... exec uvicorn niles.main:app --host 0.0.0.0 --port 8000 --reload"
  ```
- Kein externer Webserver nötig (kein Apache/Nginx im Container)
- Caddy als Reverse Proxy ist eine separate Schicht davor (HTTPS-Terminierung), nicht Teil der App

---

### VIII. Concurrency — "Scale out via the process model"

**12-Factor fordert:** Skalierung durch mehrere Prozesse (horizontal), nicht durch einen größeren Prozess (vertikal).

**Niles-Status: ⚠️ Teilweise erfüllt**

**Was vorhanden ist:**
- Uvicorn unterstützt grundsätzlich Workers (`--workers N`)
- Die Architektur (FastAPI + asyncpg Pool) ist grundsätzlich für Concurrency geeignet

**Was fehlt:**
- Aktuell: Single-Worker-Modus (`--reload` im Dev-Modus impliziert Single Worker)
- In-Memory State (Rate Limiter, Scheduler, MCP) verhindert Multi-Worker-Betrieb
- Kein Load Balancer konfiguriert
- Kein horizontales Scaling dokumentiert oder getestet

**Bewertung:** Für ein On-Premise-Produkt auf einem Mac Mini ist Single-Instance Design pragmatisch richtig. Für Skalierung bräuchte es Redis für shared State und einen Load Balancer.

---

### IX. Disposability — "Maximize robustness with fast startup and graceful shutdown"

**12-Factor fordert:** Schneller Start, sauberes Herunterfahren (graceful shutdown). Robust gegen plötzlichen Prozess-Tod.

**Niles-Status: ✅ Erfüllt**

**Startup (main.py — lifespan):**
- Sequenziell und klar: Settings → DB Pool → Stores → Syncs → Scheduler → MCP → Agent
- `ValidationError` → `sys.exit(1)` mit klaren Fehlermeldungen
- Docker `restart: unless-stopped` auf allen Containern

**Shutdown (Graceful):**
- `shutdown_event` (asyncio.Event) signalisiert allen aktiven SSE-Streams, sich sauber zu beenden
- 0,5s Drain-Phase für laufende Streams
- MCP-Server werden via `AsyncExitStack.aclose()` sauber getrennt
- APScheduler: `shutdown(wait=False)` — non-blocking, alle Jobs sind cron-basiert und idempotent
- DB Pool: `await pool.close()` schliesst alle Verbindungen

**SIGTERM-Verhalten:** Uvicorn fängt SIGTERM ab und triggert den Lifespan-Shutdown. Die SSE-Drain-Logik sorgt dafür, dass Clients ein sauberes `done`-Event erhalten statt eines Connection-Abbruchs.

---

### X. Dev/Prod Parity — "Keep development, staging, and production as similar as possible"

**12-Factor fordert:** Minimale Unterschiede zwischen Entwicklung und Produktion in drei Dimensionen: Zeit, Personal, Tools.

**Niles-Status: ✅ Erfüllt**

**Nachweis:**
- **Gleiche Backing Services:** Docker Compose wird für Dev und Prod verwendet — gleiche PostgreSQL, gleiche Evolution API, gleicher Caddy
- **Gleiche Config-Mechanik:** `.env`-Datei für beide
- **Dev/Prod-Trennung:** Prod nutzt das Dockerfile CMD (kein `--reload`, kein Source-Mount). Dev nutzt `scripts/dev.sh` (lokales Uvicorn mit `--reload`) oder übergibt `--reload` manuell an Docker Compose.
- **Lokaler Dev-Modus:** `./scripts/dev.sh` startet Uvicorn direkt, nutzt aber dieselben Docker-Services für DB/Evolution

**Was gut ist:** Kein "SQLite in Dev, PostgreSQL in Prod"-Problem. Die Umgebungen sind nahezu identisch. Die einzigen Unterschiede (`--reload`, Source-Mount) sind Standard-Praxis und kein echtes Parity-Problem.

---

### XI. Logs — "Treat logs as event streams"

**12-Factor fordert:** Die App schreibt Logs als unbuffered Stream nach stdout. Log-Routing (Aggregation, Archivierung, Analyse) wird von der Execution-Umgebung übernommen, nicht von der App.

**Niles-Status: ✅ Erfüllt**

**Strukturiertes Logging (structlog):**
- JSON-Output nach stdout über `structlog` mit `ProcessorFormatter`
- Alle stdlib-Logger (uvicorn, httpx, asyncpg) werden automatisch im gleichen JSON-Format ausgegeben
- `LOG_LEVEL` konfigurierbar via Environment

**Request-IDs für End-to-End-Tracing:**
- `RequestIdMiddleware` generiert eine 12-Zeichen Request-ID pro HTTP-Request (oder übernimmt `X-Request-ID` Header)
- Request-ID wird via `structlog.contextvars` an alle Log-Einträge im Request-Kontext gebunden
- `chat_id` und `source` (web/whatsapp) werden bei Chat-Requests zusätzlich gebunden
- Jeder Log-Eintrag enthält automatisch: `request_id`, `chat_id`, `source` — ermöglicht End-to-End-Tracing (WhatsApp-Nachricht → Agent → Tool-Call → Antwort)

**Caddy:** JSON Access-Logs nach stdout (Docker Logging Driver übernimmt Routing)

**Prometheus-Metriken (`/metrics` Endpoint):**
- `niles_http_requests_total` (Counter) — Labels: method, endpoint, status
- `niles_http_request_duration_seconds` (Histogram) — Labels: method, endpoint
- `niles_llm_request_duration_seconds` (Histogram) — LLM-Antwortzeit
- `niles_llm_tokens_total` (Counter) — Labels: type (prompt/completion)
- `niles_tool_calls_total` (Counter) — Labels: tool_name, success
- `niles_active_sse_connections` (Gauge) — Aktive SSE-Streams

---

### XII. Admin Processes — "Run admin/management tasks as one-off processes"

**12-Factor fordert:** Admin-Tasks (DB-Migrationen, Scripts, Einmal-Aufgaben) laufen als eigene Prozesse, aber gegen dieselbe Codebase und Config.

**Niles-Status: ✅ Erfüllt**

**Nachweis:**
- `scripts/` Verzeichnis mit Admin-Tasks:
  - `setup-interactive.sh` — Geführte Ersteinrichtung
  - `backup.sh` / `restore.sh` — Datensicherung
  - `start.sh` / `stop.sh` / `status.sh` — Lifecycle-Management
  - `build.sh` — Container-Build
  - `cleanup.sh` — Full Reset
  - `test.sh` — Test-Runner
- Alle Scripts nutzen dieselbe `.env` und Docker-Umgebung
- DB-Initialisierung (z.B. `vikunja_db` erstellen) ist in `start.sh` integriert
- Admin-Tasks sind im selben Repo versioniert

---

## Zusammenfassung: Verbleibende Einschränkungen

| Prio | 12-Factor | Status | Anmerkung |
|------|-----------|--------|-----------|
| — | VI. Processes | ⚠️ Dokumentiert | In-Memory State für Single-Instance akzeptabel. Für Multi-Instance: Redis für Rate-Limiter, persistenter Scheduler-Store |
| — | VIII. Concurrency | ⚠️ Dokumentiert | Multi-Worker blockiert durch In-Memory State (Rate-Limiter, Scheduler, Echo-Guard). Für On-Premise Single-Instance irrelevant |

Alle anderen Faktoren (I-V, VII, IX-XII) sind vollständig erfüllt.

---

## Kontext: 12-Factor für On-Premise

Ein wichtiger Hinweis: Die 12-Factor-Methodik wurde für SaaS/Cloud-Apps konzipiert, nicht für On-Premise-Software. Nicht alle Faktoren sind gleich relevant für dein Szenario:

| Factor | Cloud-Relevanz | On-Premise-Relevanz |
|--------|---------------|---------------------|
| I-IV (Codebase, Dependencies, Config, Backing Services) | Hoch | **Hoch** — auch On-Premise profitiert |
| V (Build/Release/Run) | Hoch | **Hoch** — Kunden brauchen Updates mit Rollback |
| VI (Processes) | Hoch | **Mittel** — Single-Instance ist ok für On-Premise |
| VII (Port Binding) | Hoch | **Hoch** — Self-contained ist immer gut |
| VIII (Concurrency) | Hoch | **Niedrig** — Auf einem Mac Mini irrelevant |
| IX (Disposability) | Hoch | **Mittel** — Fast Startup hilft, Graceful Shutdown wichtig |
| X (Dev/Prod Parity) | Hoch | **Hoch** — Debugging wird einfacher |
| XI (Logs) | Hoch | **Mittel** — Kunden brauchen Logs für Support/Troubleshooting |
| XII (Admin Processes) | Hoch | **Hoch** — Updates, Backups, Migrationen |

Die **höchste Priorität** für ein verkaufbares On-Premise-Produkt haben: Build/Release/Run (V) für Updates, Logs (XI) für Support, und Disposability (IX) für Robustheit.