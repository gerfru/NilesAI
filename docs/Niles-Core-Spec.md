# Niles AI Core -- Technische Spezifikation

> **Version:** 4.0
> **Stand:** 2026-02-19
> **Status:** Stage 1-7, 9-10 abgeschlossen. Stage 8 geplant.

---

## 1. Projektuebersicht

### 1.1 Vision

Niles ist ein lokaler, privater AI-Butler auf einem Mac Mini M4. Er empfaengt Events aus verschiedenen Quellen (WhatsApp, Web-UI, API), verarbeitet sie mit einem lokalen LLM und fuehrt Aktionen aus.

### 1.2 Kernprinzipien

- **KISS** -- Keep It Simple, Stupid
- **100% Lokal** -- Keine Cloud-Abhaengigkeiten fuer Core-Funktionen
- **Privacy First** -- Alle Daten bleiben auf dem eigenen Server
- **Erweiterbar** -- MCP-Protokoll fuer Community-Module

### 1.3 Infrastruktur

| Komponente | Interner Port | Externer Zugang | Zweck |
| ---------- | ------------- | --------------- | ----- |
| Ollama (llama3.1:8b) | 11434 (Host) | `http://localhost:11434` | LLM Inference (OpenAI-kompatibel) |
| PostgreSQL | 5432 | Nicht exponiert | Datenbank (evolution_db) |
| Evolution API v2.3.7 | 8080 | `https://localhost:8443` | WhatsApp Gateway |
| Niles Core (FastAPI) | 8000 | `https://localhost` | Python Backend + Web-UI |
| Caddy | -- | :443, :8443 | HTTPS Reverse Proxy |

**Netzwerk-Architektur:** Alle Docker-Services kommunizieren intern via HTTP. Externer Zugriff ausschliesslich ueber Caddy (HTTPS, self-signed). PostgreSQL und Service-Ports sind nicht exponiert.

**Datenbank:** `evolution_db`, User `evolution`, Passwort via `EVOLUTION_POSTGRES_PASSWORD`.

---

## 2. Architektur

### 2.1 Systemuebersicht

```text
Externe Clients (Browser, curl, Tailscale)
    |
    v HTTPS (self-signed)
┌─────────────────────────────────────────┐
│  Caddy Reverse Proxy                    │
│  :443 -> niles_core:8000                │
│  :8443 -> evolution_api:8080            │
│  Security Headers, Access Logs          │
└──────────────┬──────────────────────────┘
               | HTTP (intern)
               v
Event Sources                Niles Core (FastAPI :8000)              External
                         ┌────────────────────────────────┐
WhatsApp ─── Webhook ──> │  sources/whatsapp.py           │
                         │         │                      │
Browser ─── /ui/* ─────> │  sources/web.py (htmx/Jinja2) │
                         │    │ Google OAuth + Sessions    │
                         │    │                           │
                         │         v                      │
POST /chat  ──────────> │  agent/core.py (NilesAgent)    │──> Ollama :11434
                         │    │  Tool-Call Loop (max 5)   │
                         │    │                           │
                         │    ├─ memory/store.py          │──> PostgreSQL :5432
                         │    ├─ memory/history.py        │──> PostgreSQL :5432
                         │    ├─ actions/contacts.py      │──> PostgreSQL :5432
                         │    ├─ actions/whatsapp.py      │──> Evolution API :8080
                         │    └─ actions/calendar.py      │──> PostgreSQL :5432
                         │                                │
                         │  Middleware:                    │
                         │    SecurityHeadersMiddleware    │
                         │    RateLimitMiddleware (60/min) │
                         │    API Key Auth (X-API-Key)     │
                         │                                │
                         │  GET  /health (unauthenticated) │
                         │  POST /chat (authenticated)    │
                         │  POST /webhook/whatsapp (token) │
                         │  /ui/* (Session Cookie / OAuth) │
                         └────────────────────────────────┘
```

### 2.2 Ordnerstruktur

```text
Niles/
├── src/
│   └── niles/                        # Python Backend
│       ├── __init__.py
│       ├── main.py                   # FastAPI + Lifespan + Middleware
│       ├── config.py                 # Pydantic Settings + apply_overrides
│       ├── user_store.py             # User-Verwaltung (Google OAuth)
│       ├── settings_store.py         # Runtime Settings Overrides (PostgreSQL)
│       ├── agent/
│       │   ├── core.py               # NilesAgent, Tool-Definitionen
│       │   └── prompts.py            # System Prompt laden/bauen
│       ├── memory/
│       │   ├── store.py              # Key-Value Memory (PostgreSQL)
│       │   └── history.py            # Konversations-Historie
│       ├── actions/
│       │   ├── whatsapp.py           # WhatsApp senden (Evolution API)
│       │   ├── contacts.py           # Kontakt-Lookup + normalize_phone
│       │   └── calendar.py           # Kalender-Abfragen
│       ├── sources/
│       │   ├── whatsapp.py           # Webhook-Handler (Token-Auth)
│       │   └── web.py                # Web-UI Router (OAuth, htmx, Sessions)
│       ├── sync/
│       │   ├── carddav.py            # CardDAV Kontakt-Sync
│       │   ├── caldav.py             # CalDAV Kalender-Sync
│       │   ├── ical_parser.py        # Shared iCalendar Parser
│       │   └── manager.py            # CalendarSourceManager (CRUD, Sync, Migration)
│       ├── mcp/
│       │   └── client.py             # MCP Server Manager
│       ├── templates/
│       │   ├── base.html             # Layout (Nav, CSP, Tailwind CSS, htmx)
│       │   ├── login.html            # Login (Google + API-Key Fallback)
│       │   ├── chat.html             # Chat-UI mit SSE Streaming
│       │   ├── settings.html         # Settings Dashboard
│       │   └── fragments/            # htmx-Fragmente
│       │       ├── message.html
│       │       ├── history.html
│       │       ├── toast.html
│       │       ├── calendars.html
│       │       └── calendar_sources.html
│       └── static/
│           ├── css/
│           │   ├── input.css         # Tailwind Direktiven + Custom Components
│           │   └── style.css         # Generierter Tailwind Output
│           └── js/app.js             # SSE Streaming, Dark Mode, CSRF
├── tests/
│   ├── conftest.py                   # Shared Fixtures (Env-Variablen)
│   ├── test_config.py
│   ├── test_contacts.py
│   ├── test_health.py
│   ├── test_memory.py
│   ├── test_features.py              # Feature Flags + Webhook Auth
│   ├── test_carddav.py               # CardDAV Sync
│   ├── test_caldav.py                # CalDAV Sync
│   ├── test_ical_parser.py           # iCalendar Parser
│   ├── test_calendar_manager.py      # CalendarSourceManager
│   ├── test_mcp.py                   # MCP Integration
│   ├── test_security.py              # API Auth, Rate Limiting
│   ├── test_settings_store.py        # Runtime Settings
│   └── test_web.py                   # Web-UI, OAuth, Sessions
├── config/
│   └── soul.md                       # Agent-Persoenlichkeit
├── docker/
│   ├── docker-compose.yml
│   ├── Dockerfile.niles              # Non-root User (UID 1000)
│   └── Caddyfile                     # HTTPS, Security Headers, Access Logs
├── scripts/
│   ├── dev.sh                        # Lokaler Dev-Server
│   ├── test.sh                       # pytest Runner
│   ├── build.sh                      # Docker Images bauen
│   ├── start.sh                      # Docker starten
│   ├── stop.sh                       # Docker stoppen
│   └── status.sh                     # Service-Status pruefen
├── docs/
├── tailwind.config.js          # Tailwind CSS Konfiguration
├── pyproject.toml
├── .env
└── .env.example
```

---

## 3. Komponenten

### 3.1 FastAPI Main (`src/niles/main.py`)

Einstiegspunkt. Verwaltet den Application Lifecycle via `lifespan()`:

1. Settings laden (ValidationError bei fehlenden Secrets -> `sys.exit(1)`)
2. Logging konfigurieren (Level via `LOG_LEVEL` Env-Variable)
3. NILES_API_KEY pruefen (auto-generiert wenn nicht gesetzt, Key wird nicht geloggt)
4. asyncpg Connection Pool erstellen
5. MemoryStore + ConversationHistory initialisieren (CREATE TABLE IF NOT EXISTS)
6. UserStore initialisieren (Users-Tabelle fuer Google OAuth)
7. SettingsStore initialisieren (Runtime Overrides aus DB laden)
8. CardDAV + CalDAV Sync initialisieren (+ Scheduler wenn Feature aktiv)
9. CalendarSourceManager initialisieren (DB-Schema, Auto-Migration von .env CalDAV-Config, Sync-Scheduler)
10. MCP Manager starten
11. Actions und Agent instanziieren
12. Alles auf `app.state` speichern

**Middleware:**

- `SecurityHeadersMiddleware` (X-Content-Type-Options, X-Frame-Options, etc.)
- `RateLimitMiddleware` (60 req/min pro IP, /health und /static exempt, max 10.000 IPs tracked)

**Endpoints:** siehe `docs/API.md`.

### 3.2 Config (`src/niles/config.py`)

```python
class Settings(BaseSettings):
    # Logging
    log_level: str = "INFO"
    # LLM
    llm_base_url: str = "http://host.docker.internal:11434/v1"
    llm_model: str = "llama3.1:8b"
    # PostgreSQL
    postgres_password: str  # validation_alias="EVOLUTION_POSTGRES_PASSWORD"
    # Evolution API
    evolution_api_key: str  # Required
    # Auth
    niles_api_key: str      # Auto-generated via secrets.token_urlsafe(32)
    session_secret: str     # Auto-generated via secrets.token_urlsafe(64)
    base_url: str = ""      # For OAuth redirect URI
    # Features
    feature_whatsapp_auto_reply: bool = False
    feature_tool_send_whatsapp: bool = True
    feature_carddav_sync: bool = False
    feature_caldav_sync: bool = False
    # Google OAuth (optional)
    google_client_id: str = ""
    google_client_secret: str = ""
    google_allowed_emails: str = ""
```

Laedt aus `.env` und Environment-Variablen. `extra = "ignore"`.

`apply_overrides(settings, overrides)` gibt eine neue Settings-Instanz mit den uebergebenen Werten zurueck (via `model_copy`).

### 3.3 Agent Core (`src/niles/agent/core.py`)

`NilesAgent` verarbeitet Events ueber eine Tool-Call-Pipeline:

```python
class NilesAgent:
    def __init__(self, config, contacts, whatsapp, memory, history,
                 mcp_manager, calendar, calendar_manager): ...
    async def process_event(self, event: dict) -> str: ...
    async def process_event_stream(self, event: dict): ...  # SSE async generator
    async def _execute_tool_call(self, tool_call) -> dict: ...
```

`process_event_stream()` ist ein Async-Generator fuer SSE Streaming. Tool-Calls laufen nicht-streaming (yield `{"type": "status"}`), die finale Antwort wird Wort fuer Wort gestreamt (yield `{"type": "chunk"}`). Am Ende yield `{"type": "done"}`.

**Event-Format:**

```json
{"type": "whatsapp|chat|web", "from": "436601234...|api|web-user-1", "content": "..."}
```

**Registrierte Tools:**

| Tool | Parameter | Beschreibung |
| ---- | --------- | ------------ |
| `find_contact` | `name: str` | Kontaktsuche in PostgreSQL |
| `send_whatsapp` | `to: str, text: str` | Nachricht senden (Nummer oder Name) |
| `remember` | `key: str, value: str` | Fakt im Memory speichern |
| `recall` | `key: str` | Fakt aus Memory abrufen |
| `find_events` | `query: str` | Kalender-Events suchen |
| `create_event` | `title, start, end, ...` | Kalender-Event erstellen |

**Pipeline pro Event:**

1. Alle Memory-Eintraege laden -> in System-Prompt injizieren
2. Letzte 20 Nachrichten der Konversation laden
3. Messages bauen: System + History + User
4. User-Nachricht in History speichern
5. LLM aufrufen (max 5 Tool-Call-Runden)
6. Antwort in History speichern
7. Response zurueckgeben

### 3.4 Memory Store (`src/niles/memory/store.py`)

Key-Value Store in PostgreSQL (Tabelle `memory`).

```python
class MemoryStore:
    async def initialize(self) -> None       # CREATE TABLE + INDEX
    async def get(self, key: str) -> Any | None
    async def set(self, key: str, value: Any) -> None  # UPSERT
    async def delete(self, key: str) -> bool
    async def search(self, prefix: str) -> list[dict]
    async def list_all(self) -> list[dict]   # Fuer System-Prompt
```

### 3.5 Conversation History (`src/niles/memory/history.py`)

Per-Chat Nachrichtenverlauf in PostgreSQL (Tabelle `conversations`).

```python
class ConversationHistory:
    async def initialize(self) -> None
    async def add_message(self, chat_id: str, role: str, content: str) -> None
    async def get_recent(self, chat_id: str, limit: int = 20) -> list[dict]
    async def clear(self, chat_id: str) -> int
```

`chat_id` entspricht `event["from"]` (Telefonnummer bei WhatsApp, `"api"` bei /chat, `"web-user-{uid}"` bei Web-UI).

### 3.6 User Store (`src/niles/user_store.py`)

User-Verwaltung fuer Google OAuth in PostgreSQL (Tabelle `users`).

```python
class UserStore:
    async def initialize(self) -> None
    async def get_by_email(self, email: str) -> dict | None
    async def create_or_update(self, email, display_name, avatar_url) -> dict
    async def get_by_id(self, user_id: int) -> dict | None
```

User werden beim ersten Google-Login automatisch erstellt (INSERT ON CONFLICT UPDATE).

### 3.7 Settings Store (`src/niles/settings_store.py`)

Runtime Setting Overrides in PostgreSQL (Tabelle `settings_overrides`).

```python
EDITABLE_SETTINGS = {
    "llm_base_url", "llm_model", "timezone", "log_level",
    "feature_whatsapp_auto_reply", "feature_tool_send_whatsapp",
    "feature_carddav_sync", "feature_caldav_sync",
}

class SettingsStore:
    async def initialize(self) -> None
    async def get_all(self) -> dict[str, Any]
    async def set(self, key: str, value: Any) -> None  # Validates key
    async def delete(self, key: str) -> None
```

Nur Keys in `EDITABLE_SETTINGS` koennen geaendert werden. Credentials und Infrastruktur-Settings sind gesperrt.

### 3.8 System Prompts (`src/niles/agent/prompts.py`)

```python
def load_system_prompt(path: str | None = None) -> str
def build_system_prompt(base_prompt: str, memories: list[dict]) -> str
```

`load_system_prompt` laedt `config/soul.md`. `build_system_prompt` haengt einen "Dein Gedaechtnis"-Abschnitt mit allen Memory-Eintraegen an.

### 3.9 Web-UI (`src/niles/sources/web.py`)

Web-Interface mit Jinja2 Templates, Tailwind CSS und htmx. Chat verwendet SSE Streaming (custom JavaScript), Settings/History/Kalender verwenden htmx:

**Authentifizierung (zwei parallele Systeme):**

- **Google OAuth 2.0** -> Web-UI Login (signierte Session-Cookies via itsdangerous)
- **API-Key** -> Fallback-Login (wenn Google OAuth nicht konfiguriert)

**Session Management:**

- Signierte Cookies via `URLSafeTimedSerializer` (itsdangerous)
- Separates `session_secret` (nicht `niles_api_key`)
- CSRF Double-Submit Pattern (Cookie + X-CSRF-Token Header)
- Per-User Chat-IDs: `web-user-{uid}`

**Routen:** siehe `docs/API.md`.

### 3.10 WhatsApp Source (`src/niles/sources/whatsapp.py`)

Webhook-Handler fuer Evolution API v2.3.7:

- Token-Authentifizierung via Query-Parameter (`?token=...`, hmac.compare_digest)
- Filtert auf `event == "messages.upsert"`
- Ignoriert eigene Nachrichten (`fromMe: true`)
- Extrahiert Text aus `message.conversation` oder `extendedTextMessage.text`
- Gibt 401 fuer Auth-Fehler zurueck, 200 fuer alle anderen Faelle (verhindert Retry-Spam)

**Hinweis:** Webhook-Token wird als Query-Parameter uebergeben, da Evolution API v2.3.x keine Custom-Header unterstuetzt (siehe [Issue #1933](https://github.com/EvolutionAPI/evolution-api/issues/1933)).

### 3.11 WhatsApp Action (`src/niles/actions/whatsapp.py`)

```python
class WhatsAppAction:
    async def send_message(self, to: str, text: str) -> dict
```

Sendet via `POST /message/sendText/{instance}` an Evolution API. Timeout 30s.

### 3.12 Kontakt-Lookup (`src/niles/actions/contacts.py`)

```python
def normalize_phone(phone: str) -> str        # +43/00/0 -> 43...
class ContactsAction:
    async def find_by_name(self, name: str) -> dict | None
```

Suche mit Prioritaet: exakt > prefix > partial > first/last name.
Telefon-Normalisierung: Oesterreich-spezifisch (fuehrende 0 -> 43).

### 3.13 CardDAV Sync (`src/niles/sync/carddav.py`)

PROPFIND fuer vCard-URLs, vCard-Parsing (TEL, EMAIL, FN, N), UPSERT via UID.
APScheduler fuer taeglichen Sync (03:00). Feature Flag: `FEATURE_CARDDAV_SYNC`.

### 3.14 Kalender-Sync (`src/niles/sync/`)

**CalendarSourceManager** (`manager.py`) verwaltet alle Kalenderquellen (ICS, CalDAV, Google) ueber die `calendar_sources`-Tabelle. CRUD-Operationen, Sync-Orchestrierung und Auto-Migration von `.env` CalDAV-Config beim ersten Start.

**CalDAVSync** (`caldav.py`) synchronisiert einzelne CalDAV-Quellen via PROPFIND/REPORT. Parameterisierter Constructor (URL, Auth, Timezone, source_id).

**iCalendar Parser** (`ical_parser.py`) ist ein Shared Parser fuer VEVENT-Daten, genutzt von CalDAV und ICS-Sync.

APScheduler fuer taeglichen Sync: CardDAV 03:00, CalDAV 03:15, Kalenderquellen 03:20.
Feature Flag `FEATURE_CALDAV_SYNC` aktiviert den Legacy-CalDAV-Sync. Neue Kalenderquellen werden unabhaengig davon ueber die Web-UI verwaltet und automatisch gesynct.

### 3.15 MCP Client (`src/niles/mcp/client.py`)

MCP Server Manager fuer externe Tool-Integrationen. Konfiguration via `config/mcp_servers.yaml`.

---

## 4. Security

### 4.1 Netzwerk

- **HTTPS via Caddy:** Alle externen Zugriffe ueber self-signed TLS-Zertifikate (`tls internal`)
- **Keine exponierten Ports:** PostgreSQL, Niles Core und Evolution API sind nur via Docker-Netzwerk erreichbar
- **Security Headers (Caddy + Middleware):** `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`, Server-Header entfernt
- **CSP:** `default-src 'self'; script-src 'self' https://unpkg.com https://cdn.jsdelivr.net; style-src 'self'; img-src 'self' data: https://*.googleusercontent.com; connect-src 'self'`
- **CDN-Ressourcen** (htmx, marked.js, DOMPurify): SRI-Hashes fuer Integritaetspruefung

### 4.2 Authentifizierung

**API (programmatisch):**

- **API Key:** `/chat` erfordert `X-API-Key` Header (hmac.compare_digest, max 256 Zeichen)
- **Webhook Token:** `/webhook/whatsapp` erfordert `?token=` Query-Parameter
- **Auto-generierter Key:** `NILES_API_KEY` wird per `secrets.token_urlsafe(32)` generiert wenn nicht gesetzt
- **Key wird nicht geloggt:** Nur Hinweis auf `docker exec niles_core printenv NILES_API_KEY`

**Web-UI:**

- **Google OAuth 2.0:** Login via Google Account (openid email profile)
- **Email-Whitelist:** `GOOGLE_ALLOWED_EMAILS` beschraenkt Zugriff auf benannte Accounts
- **email_verified Check:** Nur verifizierte Google-Accounts werden akzeptiert
- **API-Key Fallback:** Wenn kein Google OAuth konfiguriert, Login mit `NILES_API_KEY`
- **Signed Session Cookies:** `itsdangerous.URLSafeTimedSerializer` mit dediziertem `SESSION_SECRET`
- **CSRF:** Double-Submit Pattern (Cookie + `X-CSRF-Token` Header) fuer alle POST-Endpoints
- **OAuth State:** CSRF-Schutz fuer OAuth-Flow via State-Parameter in Cookie
- **Logout:** POST (nicht GET) um Logout-CSRF zu verhindern
- **Login Rate Limiting:** Max 5 Versuche pro IP in 5 Minuten (API-Key Login)
- **base_url Config:** OAuth Redirect URI aus Config statt aus untrusted Request-Headers

### 4.3 Rate Limiting

- In-Memory Rate Limiter: 60 Requests/Minute pro Client-IP
- `/health` und `/static` sind exempt
- Memory Safeguard: Max 10.000 IPs tracked, aelteste werden evicted
- HTTP 429 bei Ueberschreitung

### 4.4 Docker

- Niles Core laeuft als Non-Root User (UID/GID 1000)
- PostgreSQL-Port nicht exponiert

### 4.5 Access Logs

- Caddy schreibt JSON-formatierte Access Logs pro Service
- Log-Rotation: 10 MB pro Datei, 3 Dateien behalten
- Dateien: `access-niles.log`, `access-evolution.log`

---

## 5. Dependencies

```toml
fastapi>=0.129.0          # Web Framework
uvicorn[standard]>=0.41.0 # ASGI Server
httpx>=0.28.1             # Async HTTP Client (+ Google OAuth)
asyncpg>=0.31.0           # PostgreSQL
openai>=2.21.0            # LLM Client (OpenAI-kompatibel)
mcp>=1.26.0               # MCP SDK
pydantic-settings>=2.13.0 # Config Management
pyyaml>=6.0.3             # YAML Parsing
apscheduler>=3.11.2       # Scheduling (CardDAV/CalDAV Sync)
jinja2>=3.1.0             # HTML Templates (Web-UI)
aiofiles>=24.0.0          # Static File Serving
itsdangerous>=2.0         # Signed Session Cookies
```

Dev: `pytest>=9.0.0`, `pytest-asyncio>=1.3.0`, `httpx` (TestClient).

---

## 6. Docker

### 6.1 Dockerfile (`docker/Dockerfile.niles`)

```dockerfile
FROM python:3.12-slim
WORKDIR /app
RUN pip install uv
COPY pyproject.toml .
COPY src/ ./src/
# Download Tailwind standalone CLI (via Python, kein curl/wget in slim) und baue CSS
COPY tailwind.config.js .
RUN python -c "import urllib.request; urllib.request.urlretrieve('https://github.com/tailwindlabs/tailwindcss/releases/download/v3.4.17/tailwindcss-linux-x64', '/usr/local/bin/tailwindcss')" \
    && chmod +x /usr/local/bin/tailwindcss \
    && tailwindcss --minify \
       -i src/niles/static/css/input.css \
       -o src/niles/static/css/style.css
RUN uv pip install --system .
COPY config/ ./config/
RUN groupadd --gid 1000 niles && \
    useradd --uid 1000 --gid niles --no-create-home niles && \
    chown -R niles:niles /app
USER niles
ENV PYTHONPATH=/app/src
CMD ["uvicorn", "niles.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Hinweis:** `python:3.12-slim` enthaelt weder `curl` noch `wget`. Tailwind CLI wird daher via Python `urllib.request.urlretrieve` heruntergeladen.

### 6.2 Docker Compose Services

| Container | Image | Exponierter Port | Zweck |
| --------- | ----- | ---------------- | ----- |
| `niles_caddy` | `caddy:2-alpine` | 443, 8443 | HTTPS Reverse Proxy |
| `niles_core` | Build (Dockerfile.niles) | -- (via Caddy) | Python Backend + Web-UI |
| `niles_evolution_postgres` | `postgres:15-alpine` | -- | PostgreSQL |
| `niles_evolution_api` | `evoapicloud/evolution-api:v2.3.7` | -- (via Caddy) | WhatsApp Gateway |

### 6.3 Volumes

| Volume | Zweck |
| ------ | ----- |
| `evolution_postgres` | PostgreSQL-Daten |
| `caddy_data` | TLS-Zertifikate |
| `caddy_config` | Caddy-Konfiguration |
| `~/.evolution/instances` | WhatsApp-Sessions |

---

## 7. Implementierungsstatus

| Stage | Branch | PR | Status | Beschreibung |
| ----- | ------ | -- | ------ | ------------ |
| 1 | `stage/1-scaffold` | #1 | Abgeschlossen | FastAPI, Docker, pytest, /health |
| 2 | `stage/2-whatsapp-loop` | #4 | Abgeschlossen | WhatsApp empfangen, LLM, antworten |
| 3 | `stage/3-memory` | #6 | Abgeschlossen | Key-Value Memory, Chat-History, Feature Flags |
| 4 | `stage/4-carddav-sync` | #8 | Abgeschlossen | CardDAV Kontakt-Sync |
| 5 | `stage/5-security-hardening` | #9, #10 | Abgeschlossen | Auth, Rate Limiting, HTTPS, Security Headers |
| 6 | `stage/6-mcp` | #11 | Abgeschlossen | MCP Integration |
| 7 | `stage/7-caldav-calendar` | #12 | Abgeschlossen | CalDAV Kalender-Sync |
| 8 | -- | -- | Geplant | Email als Event-Quelle |
| 9 | `stage/9-web-gui` | #13 | Abgeschlossen | Web GUI (Chat, Settings, htmx) |
| 10 | `stage/10-oauth-gui-v2` | #14 | Abgeschlossen | Google OAuth, Multi-User, Tailwind CSS, SSE Streaming |

### Roadmap

**Stage 8 -- Email:**

- `src/niles/sources/email.py` -- IMAP Poller (alle 5 min)
- Neue Agent-Tools: `draft_email`

**Stage 10 -- Abgeschlossen (GUI v2):**

- Tailwind CSS Migration (von Pico CSS, Standalone CLI ohne Node.js)
- SSE Streaming (Wort-fuer-Wort Antworten)
- Sofortige User-Bubble bei Senden (kein Server-Roundtrip)
- Message Timestamps (DD.MM. HH:MM)
- Rollen-Badges (Du / Niles)
- Dark Mode Toggle (class="dark" auf html, localStorage)
- Mobile Responsiveness
- Markdown Rendering (marked.js + DOMPurify, SRI)

---

## 8. Hinweise

### Docker Networking

Alle Container im `niles_network`. Container-Namen als Hostnamen:

- `evolution_postgres` (PostgreSQL)
- `evolution_api` (Evolution API)
- `niles_core` (Niles, auch fuer Webhooks)
- `host.docker.internal:11434` (Ollama auf dem Host)

### Evolution API Webhook

Format v2.3.7 (nested):

```json
{
  "webhook": {
    "enabled": true,
    "url": "http://niles_core:8000/webhook/whatsapp?token=<NILES_API_KEY>",
    "events": ["MESSAGES_UPSERT"]
  }
}
```

### Environment-Variablen

Pflicht: `EVOLUTION_POSTGRES_PASSWORD`, `EVOLUTION_API_KEY`.

Optional: `NILES_API_KEY`, `SESSION_SECRET`, `BASE_URL`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_ALLOWED_EMAILS`, `CARDDAV_USER`, `CARDDAV_PASSWORD`, `CALDAV_USER`, `CALDAV_PASSWORD` (Legacy, auto-migriert in DB), `FEATURE_CARDDAV_SYNC`, `FEATURE_CALDAV_SYNC`, `LOG_LEVEL`, `LLM_BASE_URL`, `LLM_MODEL`, `TIMEZONE`.

Siehe `.env.example` fuer vollstaendige Dokumentation.

---

## 9. Weitere Dokumentation

- [Architecture](Architecture.md) -- Detaillierte Systemarchitektur
- [API Reference](API.md) -- Endpoints, Payloads, Beispiele
- [Development Guide](Development.md) -- Setup, Testing, Konventionen
