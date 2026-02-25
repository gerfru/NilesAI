# Niles AI Core -- Technische Spezifikation

> **Version:** 7.0
> **Stand:** 2026-02-25
> **Status:** Stage 1-7, 9-10 abgeschlossen. PR #22-26, #29 abgeschlossen. Stage 8 geplant.

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
| Vikunja | 3456 | `http://localhost:3456` | Todo/Task Management |
| Caddy | -- | :443, :8443 | HTTPS Reverse Proxy |

**Netzwerk-Architektur:** Alle Docker-Services kommunizieren intern via HTTP. Externer Zugriff ausschliesslich ueber Caddy (HTTPS, self-signed). PostgreSQL und Service-Ports sind nicht exponiert.

**Datenbank:** `evolution_db`, User `evolution`, Passwort via `EVOLUTION_POSTGRES_PASSWORD`. Vikunja verwendet eine eigene Datenbank `vikunja_db` (einmalig: `CREATE DATABASE vikunja_db OWNER evolution;`).

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
                         │    ├─ actions/calendar.py      │──> PostgreSQL :5432
                         │    └─ actions/tasks.py         │──> Vikunja :3456
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

Alle Komponenten laufen in Docker-Containern im selben Netzwerk (`niles_network`). Ollama laeuft nativ auf dem Host und ist ueber `host.docker.internal:11434` erreichbar.

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
│       ├── whatsapp_store.py        # Per-User WhatsApp Sessions (PostgreSQL)
│       ├── agent/
│       │   ├── core.py               # NilesAgent, Tool-Definitionen
│       │   └── prompts.py            # System Prompt laden/bauen
│       ├── memory/
│       │   ├── store.py              # Key-Value Memory (PostgreSQL)
│       │   └── history.py            # Konversations-Historie
│       ├── actions/
│       │   ├── briefing.py           # BriefingGenerator (Tages-/Wochen-Uebersicht)
│       │   ├── whatsapp.py           # WhatsApp senden (Evolution API)
│       │   ├── contacts.py           # Kontakt-Lookup + normalize_phone
│       │   ├── calendar.py           # Kalender-Abfragen
│       │   └── tasks.py              # Vikunja Task Management
│       ├── jobs/
│       │   └── briefing.py           # Scheduler-Jobs fuer Briefing
│       ├── sources/
│       │   ├── whatsapp.py           # Webhook-Handler (Token-Auth)
│       │   └── web.py                # Web-UI Router (OAuth, htmx, Sessions)
│       ├── sync/
│       │   ├── carddav.py            # CardDAV Kontakt-Sync
│       │   ├── caldav.py             # CalDAV Kalender-Sync
│       │   ├── google_auth.py        # Google Calendar OAuth (Bearer + Refresh)
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
│   ├── test_config.py               # Settings-Validierung
│   ├── test_contacts.py             # ContactsAction, normalize_phone, Multi-Phone
│   ├── test_core.py                 # NilesAgent, Tool-Call-Pipeline
│   ├── test_health.py               # GET /health Endpoint
│   ├── test_memory.py               # MemoryStore, ConversationHistory
│   ├── test_features.py             # Feature Flags + Webhook Auth
│   ├── test_carddav.py              # CardDAV Sync
│   ├── test_caldav.py               # CalDAV Sync
│   ├── test_ical_parser.py          # iCalendar Parser
│   ├── test_rrule_expansion.py      # RRULE Expansion (Wiederkehrende Termine)
│   ├── test_calendar_manager.py     # CalendarSourceManager (CRUD, Sync, Migration)
│   ├── test_calendar_improvements.py # Kalender Query-Verbesserungen
│   ├── test_google_auth.py          # Google Calendar OAuth (Token Refresh)
│   ├── test_mcp.py                  # MCP Integration
│   ├── test_security.py             # API Auth, Rate Limiting
│   ├── test_settings_store.py       # Runtime Settings Store
│   ├── test_web.py                  # Web-UI, Google OAuth, Sessions, CSRF
│   ├── test_whatsapp_sessions.py    # Per-User WhatsApp Sessions
│   ├── test_tasks.py                # Vikunja Task Management
│   ├── test_self_chat.py            # WhatsApp Self-Chat Trigger
│   └── test_briefing.py             # BriefingGenerator + Zeitparsing
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

### 2.3 Datenfluss: WhatsApp-Nachricht

```text
1. Evolution API empfaengt WhatsApp-Nachricht
2. Evolution API sendet Webhook POST an /webhook/whatsapp
3. sources/whatsapp.py filtert auf messages.upsert
   3a. Eigene Nachrichten (fromMe=true):
       - "Hey Niles" Trigger → Agent verarbeitet, Antwort senden (Self-Chat)
       - Ohne Trigger → Ignorieren (Notizen, Links etc.)
   3b. Fremde Nachrichten → ignorieren (kein LLM-Call, kein Web-Chat, kein Auto-Reply).
       Evolution API speichert Nachrichten intern. Agent liest via findMessages API.
4. [Self-Chat] Extrahiert Absender (JID -> Telefonnummer) und Text
5. Erstellt Event: {"type": "whatsapp", "from": "wa-self-{nr}", "content": "..."}
6. Ruft agent.process_event(event) auf
   6a. Laedt alle Memory-Eintraege -> injiziert in System Prompt
   6b. Laedt letzte 20 Nachrichten der Konversation
   6c. Baut Messages: [system, ...history, user]
   6d. Speichert User-Nachricht in History
   6e. Ruft LLM auf (OpenAI-kompatible API)
   6f. Falls Tool-Calls: ausfuehren, Ergebnisse zurueck an LLM (max 5 Runden)
   6g. Speichert Antwort in History
7. Self-Chat: sources/whatsapp.py sendet Antwort via WhatsAppAction zurueck
   Fremde: Nachricht von Evolution API gespeichert (abfragbar via get_whatsapp_messages Tool)
8. Gibt HTTP 200 zurueck (unabhaengig vom Ergebnis)
```

### 2.4 Datenfluss: Web-UI Chat (SSE Streaming)

```text
1. User oeffnet /ui/chat (GET)
2. sources/web.py prueft signierte Session-Cookie (itsdangerous)
3. Laedt per-User Chat-History (chat_id = "web-user-{uid}")
4. Rendert chat.html mit Jinja2, setzt CSRF-Cookie
5. User sendet Nachricht (Enter/Senden-Button)
6. JavaScript: User-Bubble sofort anzeigen, Input leeren, "Niles denkt nach..." anzeigen
7. fetch() POST an /ui/api/chat/stream (SSE)
8. sources/web.py prueft Session + CSRF (Double-Submit Pattern)
9. Erstellt Event: {"type": "web", "from": "web-user-1", "content": "..."}
10. Ruft agent.process_event_stream(event) auf
    10a. Tool-Calls laufen nicht-streaming (yield status updates)
    10b. Finale Antwort wird gestreamt (yield chunks Wort fuer Wort)
11. JavaScript: Assistant-Bubble erstellen, Text chunk-weise einfuegen
12. Nach Stream-Ende: Markdown rendern (marked.js + DOMPurify)
```

### 2.5 Datenfluss: Google OAuth Login

```text
1. User klickt "Mit Google anmelden" auf /ui/login
2. Redirect zu Google OAuth (/ui/login/google)
   - State-Token als Cookie gesetzt (CSRF-Schutz)
   - Redirect URI aus BASE_URL (oder Request Headers als Fallback)
3. Google zeigt Consent Screen (openid email profile)
4. Google Callback an /ui/callback/google mit Auth-Code
5. Server prueft State-Token, tauscht Code gegen Access-Token
6. Server ruft Google Userinfo API auf (Email, Name, Avatar)
7. Prueft email_verified und GOOGLE_ALLOWED_EMAILS Whitelist
8. user_store.create_or_update() -> INSERT ON CONFLICT UPDATE
9. Signierte Session-Cookie setzen (itsdangerous, 30 Tage)
10. Redirect zu /ui/chat
```

---

## 3. Komponenten

### 3.1 FastAPI Main (`src/niles/main.py`)

Einstiegspunkt. Verwaltet den Application Lifecycle via `lifespan()`:

1. Settings laden (ValidationError bei fehlenden Secrets -> `sys.exit(1)`)
2. Logging konfigurieren (Level via `LOG_LEVEL` Env-Variable)
3. NILES_API_KEY pruefen (auto-generiert wenn nicht gesetzt, Key wird nicht geloggt)
4. asyncpg Connection Pool erstellen (min=2, max=10)
5. MemoryStore + ConversationHistory initialisieren (CREATE TABLE IF NOT EXISTS)
6. UserStore initialisieren (Users-Tabelle fuer Google OAuth)
7. WhatsAppSessionStore initialisieren (Per-User WhatsApp Sessions)
8. SettingsStore initialisieren (Runtime Overrides aus DB laden)
9. CardDAV Sync initialisieren (+ Scheduler wenn carddav_url konfiguriert)
10. CalDAV Sync initialisieren (Legacy, wenn caldav_url konfiguriert)
11. CalendarSourceManager initialisieren (DB-Schema, Auto-Migration von .env CalDAV-Config, Sync-Scheduler)
12. APScheduler starten (CardDAV 03:00, Kalenderquellen 03:20)
13. MCP Manager starten
14. Actions und Agent instanziieren (inkl. wa_store)
15. Alles auf `app.state` speichern

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
    postgres_host: str = "evolution_postgres"
    postgres_port: int = 5432
    postgres_db: str = "evolution_db"
    postgres_user: str = "evolution"
    postgres_password: str  # validation_alias="EVOLUTION_POSTGRES_PASSWORD"
    # Evolution API (WhatsApp)
    evolution_api_url: str = "http://evolution_api:8080"
    evolution_api_key: str  # Required
    evolution_instance: str = "niles-whatsapp"
    # Auth
    niles_api_key: str      # Auto-generated via secrets.token_urlsafe(32)
    session_secret: str     # Auto-generated via secrets.token_urlsafe(64)
    base_url: str = ""      # For OAuth redirect URI
    # Timezone
    timezone: str = "Europe/Vienna"
    # Features
    feature_whatsapp_send_others: bool = True  # Darf Niles anderen WhatsApp senden?
    # CardDAV (configured via Settings UI)
    carddav_url: str = ""
    carddav_user: str = ""
    carddav_password: str = ""
    # CalDAV (Legacy, auto-migriert in calendar_sources)
    caldav_url: str = "https://dav.example.com/caldav/"
    caldav_user: str = ""
    caldav_password: str = ""
    caldav_calendars: str = ""  # Comma-separated collection hrefs
    # Google OAuth (optional)
    google_client_id: str = ""
    google_client_secret: str = ""
    google_allowed_emails: str = ""
    # Vikunja (Todo/Task Management)
    vikunja_api_url: str = ""
    vikunja_api_token: str = ""
    feature_vikunja: bool = False
    # Briefing / Digest
    feature_briefing_daily: bool = False
    feature_briefing_weekly: bool = False
    briefing_daily_time: str = "07:30"        # HH:MM, Mo-Fr
    briefing_weekly_time: str = "07:15"       # HH:MM, Montag
```

Laedt aus `.env` und Environment-Variablen. `extra = "ignore"`.

`apply_overrides(settings, overrides)` gibt eine neue Settings-Instanz mit den uebergebenen Werten zurueck (via `model_copy`).

Vollstaendige Settings-Tabelle mit Defaults und Env-Variablen: siehe §6.1.

### 3.3 Agent Core (`src/niles/agent/core.py`)

`NilesAgent` verarbeitet Events ueber eine Tool-Call-Pipeline:

```python
class NilesAgent:
    def __init__(self, config, contacts, whatsapp, memory, history,
                 mcp_manager, calendar, calendar_manager, wa_store,
                 tasks=None): ...
    async def process_event(self, event: dict) -> str: ...
    async def process_event_stream(self, event: dict): ...  # SSE async generator
    async def _execute_tool_call(self, tool_call, chat_id) -> dict: ...
    async def _resolve_wa_instance(self, chat_id) -> str | None: ...
    async def _handle_phone_choice(self, chat_id, content) -> str | None: ...
```

`process_event_stream()` ist ein Async-Generator fuer SSE Streaming. Tool-Calls laufen nicht-streaming (yield `{"type": "status"}`), die finale Antwort wird Wort fuer Wort gestreamt (yield `{"type": "chunk"}`). Am Ende yield `{"type": "done"}`.

**Event-Format:**

```json
{"type": "whatsapp|chat|web", "from": "436601234...|api|web-user-1", "content": "..."}
```

**Registrierte Tools:**

| Tool | Parameter | Beschreibung |
| ---- | --------- | ------------ |
| `find_contact` | `name: str` | Kontaktsuche in PostgreSQL. Gibt `full_name`, `phone` (bevorzugte), `phones` (alle mit Typ), `email` zurueck. |
| `send_whatsapp` | `to: str, text: str` | Nachricht senden (Nummer oder Name). Multi-Phone: fragt User bei mehreren Nummern (TTL 5 min). Per-User Instance Resolution. |
| `get_whatsapp_messages` | `contact: str, limit?: int` | WhatsApp-Chatverlauf lesen (nach Kontaktname oder Telefonnummer). Max 50, 30-Tage-Window. Via Evolution API `findMessages`. Result enthaelt `date_range` und `hinweis` fuer LLM-Zusammenfassung. |
| `remember` | `key: str, value: str` | Fakt im Memory speichern |
| `recall` | `key: str` | Fakt aus Memory abrufen |
| `find_event` | `query?, date_from?, date_to?, calendar?` | Kalender-Events suchen (max 10 Ergebnisse). Unterstuetzt Datumsfilter und Kalender-Auswahl. |
| `create_event` | `summary: str, start: str, end?, description?, location?` | Kalender-Event auf beschreibbarer Quelle erstellen (via CalendarSourceManager). |
| `list_tasks` | `project?, include_done?` | Offene Aufgaben aus Vikunja auflisten (max 50). Feature-Flag: `feature_vikunja`. |
| `create_task` | `title: str, description?, due_date?, priority?, project?` | Neue Aufgabe in Vikunja erstellen. |
| `complete_task` | `title: str` | Aufgabe als erledigt markieren (Suche nach Titel). |

**Pipeline pro Event:**

1. Pending Phone-Choice pruefen (bypass LLM bei Multi-Phone-Auswahl, TTL 5 min)
2. Alle Memory-Eintraege laden -> in System-Prompt injizieren
3. Kalenderquellen-Namen laden (gecacht, 5 min TTL) -> in System-Prompt injizieren
4. Letzte 20 Nachrichten der Konversation laden
5. Messages bauen: System + History + User
6. LLM aufrufen (max 5 Tool-Call-Runden)
7. User- und Assistant-Nachricht zusammen in History speichern (atomar, keine orphaned Records)
8. Response zurueckgeben

**Per-User WhatsApp Instance Resolution:** Bei `chat_id` mit Prefix `web-user-` wird die WhatsApp-Instance aus `whatsapp_sessions` aufgeloest. Fallback auf globale Instance (`config.evolution_instance`).

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
    "feature_whatsapp_send_others",
    "caldav_calendars",
    "carddav_url", "carddav_user", "carddav_password",
    "feature_vikunja",
}

class SettingsStore:
    async def initialize(self) -> None
    async def get_all(self) -> dict[str, Any]
    async def set(self, key: str, value: Any) -> None  # Validates key
    async def delete(self, key: str) -> None
```

Nur Keys in `EDITABLE_SETTINGS` koennen geaendert werden. Credentials und Infrastruktur-Settings sind gesperrt.

### 3.8 WhatsApp Session Store (`src/niles/whatsapp_store.py`)

Per-User WhatsApp Sessions in PostgreSQL (Tabelle `whatsapp_sessions`).

```python
class WhatsAppSessionStore:
    async def initialize(self) -> None
    async def get_session(self, user_id: int) -> dict | None
    async def get_by_instance(self, instance_name: str) -> dict | None  # Webhook-Routing
    async def upsert_session(self, user_id, instance_name, status, phone_number) -> None
    async def update_status(self, user_id, status, phone_number) -> None
    async def delete_session(self, user_id: int) -> None
```

Jeder Web-UI User kann eine eigene WhatsApp-Instance verbinden (via QR-Code in der Web-UI). Status: `disconnected`, `connecting`, `connected`. Die Instance wird beim Webhook-Empfang zur Chat-ID-Aufloesung verwendet und beim Senden als Absender-Instance.

### 3.9 System Prompts (`src/niles/agent/prompts.py`)

```python
def load_system_prompt(path: str | None = None) -> str
def build_system_prompt(base_prompt: str, memories: list[dict]) -> str
```

`load_system_prompt` laedt `config/soul.md`. `build_system_prompt` haengt einen "Dein Gedaechtnis"-Abschnitt mit allen Memory-Eintraegen an.

### 3.10 Web-UI (`src/niles/sources/web.py`)

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

### 3.11 WhatsApp Source (`src/niles/sources/whatsapp.py`)

Webhook-Handler fuer Evolution API v2.3.7:

- Token-Authentifizierung via Query-Parameter (`?token=...`, hmac.compare_digest)
- Filtert auf `event == "messages.upsert"`
- Extrahiert Text aus `message.conversation` oder `extendedTextMessage.text`
- Gibt 401 fuer Auth-Fehler zurueck, 200 fuer alle anderen Faelle (verhindert Retry-Spam)

**Self-Chat Trigger:** Eigene Nachrichten (`fromMe: true`) werden auf Trigger-Phrasen geprueft ("Hey Niles", "Hi Niles", "Hallo Niles", "Niles" — case-insensitive, word-boundary). Bei Trigger: Phrase entfernen, Agent verarbeitet den Rest, Antwort an eigene Nummer senden. Ohne Trigger: Ignorieren. Echo-Loop-Guard: Gesendete Message-IDs werden 10s gecacht, echote Webhooks werden uebersprungen.

**Self-Chat chat_id:** `wa-self-{nummer}` — eigene Konversations-Historie, getrennt von fremden Chats und Web-UI.

**LID-Adressierung:** WhatsApp nutzt seit 2025 LID (Linked Identity Device) Adressen. Neue Nachrichten haben `key.remoteJid = "...@lid"` statt `"...@s.whatsapp.net"`. Die Phone-JID steht in `key.remoteJidAlt`. Der Webhook-Handler erkennt `@lid`-JIDs und verwendet stattdessen `remoteJidAlt` fuer Sender-Extraktion, chat_id und Reply-Routing.

**Fremde Nachrichten:** Werden von der Evolution API intern gespeichert (kein LLM-Call, kein Web-Chat, kein Auto-Reply). Der Agent liest sie per `get_whatsapp_messages`-Tool direkt via Evolution API `findMessages`-Endpoint ("Was hat mir Max geschrieben?"). Kontaktname wird per `contacts.find_by_name()` zu Telefonnummer aufgeloest, dann als JID an die API uebergeben. 30-Tage-Window, max 50 Nachrichten. Niles antwortet fremden Personen nur wenn der Benutzer ihn explizit via `send_whatsapp`-Tool dazu auffordert (gesteuert durch `feature_whatsapp_send_others`).

**Per-User Instance Routing:** Der Webhook identifiziert die Evolution API Instance (`payload.instance`). Fuer Self-Chat wird die Instance aus dem Webhook-Payload verwendet. Fuer `get_whatsapp_messages` wird die Instance per `_resolve_wa_instance(chat_id)` aus der `whatsapp_sessions`-Tabelle ermittelt.

**Hinweis:** Webhook-Token wird als Query-Parameter uebergeben, da Evolution API v2.3.x keine Custom-Header unterstuetzt (siehe [Issue #1933](https://github.com/EvolutionAPI/evolution-api/issues/1933)).

### 3.12 WhatsApp Action (`src/niles/actions/whatsapp.py`)

```python
class WhatsAppAction:
    async def send_message(self, to: str, text: str, instance: str | None = None) -> dict
    async def fetch_messages(self, remote_jid: str, limit: int = 50, instance: str | None = None) -> list[dict]
    async def create_instance(self, instance_name: str, webhook_url: str) -> dict
    async def get_connection_state(self, instance_name: str) -> str
    async def get_qr_code(self, instance_name: str) -> dict
    async def logout_instance(self, instance_name: str) -> dict
    async def delete_instance(self, instance_name: str) -> dict
```

`send_message` sendet via `POST /message/sendText/{instance}` an Evolution API. Timeout 30s. Optionaler `instance`-Parameter fuer Per-User WhatsApp Sessions (Fallback: globale `evolution_instance` aus Config).

`fetch_messages` fragt Nachrichten via `POST /chat/findMessages/{instance}` ab. Der Filter-Payload setzt sowohl `remoteJid` als auch `remoteJidAlt` auf die Phone-JID — Evolution API's Baileys-Override (PR #2249) kombiniert diese mit OR, sodass sowohl alte Phone-JIDs als auch neue LID-Nachrichten gefunden werden. Beide Keys muessen gesetzt sein (bei nur einem Key erzeugt der OR-Clause einen leeren Match, Prisma-Bug). Client-seitiger 30-Tage-Filter, max 50 Nachrichten, chronologisch sortiert.

**Tool-Result Metadaten:** Das `get_whatsapp_messages`-Tool gibt neben dem Transcript zusaetzlich `date_range` (formatierter Zeitraum) und `hinweis` (Zusammenfassungs-Anweisung) zurueck — analog zum `hinweis`-Feld in `find_event`. Diese Felder helfen dem 8B-LLM, strukturierte Zusammenfassungen statt roher Transcript-Dumps zu produzieren.

Instance-Management-Methoden steuern Evolution API Instanzen fuer den Per-User WhatsApp-Flow (erstellen, QR-Code abrufen, Verbindungsstatus pruefen, trennen, loeschen).

### 3.13 Kontakt-Lookup (`src/niles/actions/contacts.py`)

```python
def normalize_phone(phone: str) -> str        # +43/00/0 -> 43...
class ContactsAction:
    async def find_by_name(self, name: str) -> dict | None
```

Suche mit Prioritaet: exakt > prefix > partial > first/last name.
Multi-Word-Suche: Bei mehreren Woertern (z.B. "Thomas Brunner") muss jedes Wort in mindestens einem Namensfeld vorkommen (full_name, first_name, last_name).
Telefon-Normalisierung: Oesterreich-spezifisch (fuehrende 0 -> 43).

**Multi-Phone Support:** Kontakte koennen mehrere Telefonnummern haben (Tabelle `contact_phones`, 1:N). `find_by_name` gibt zurueck:

- `phone`: bevorzugte Nummer (Prioritaet: mobile > home > work > other)
- `phones`: alle Nummern mit Typ (`[{"type": "mobile", "number": "436601234567"}, ...]`)
- Fallback auf Legacy-Spalten (`phone_primary`, `phone_mobile`, `phone_work`) wenn `contact_phones` leer.

### 3.14 CardDAV Sync (`src/niles/sync/carddav.py`)

PROPFIND fuer vCard-URLs, vCard-Parsing (TEL, EMAIL, FN, N), UPSERT via UID. Unterstuetzt Multi-Phone pro Kontakt (Tabelle `contact_phones`). Phone-Migration von Legacy-Spalten automatisch.
APScheduler fuer taeglichen Sync (03:00, wenn `carddav_url` konfiguriert). CardDAV-Credentials koennen ueber die Web-UI konfiguriert und hot-reloaded werden.

### 3.15 Kalender-Sync (`src/niles/sync/`)

**CalendarSourceManager** (`manager.py`) verwaltet alle Kalenderquellen (ICS, CalDAV, Google) ueber die `calendar_sources`-Tabelle. CRUD-Operationen, Sync-Orchestrierung und Auto-Migration von `.env` CalDAV-Config beim ersten Start.

**CalDAVSync** (`caldav.py`) synchronisiert einzelne CalDAV- und Google-Quellen via PROPFIND/REPORT. Parameterisierter Constructor (URL, Auth, Timezone, source_id). Google-Quellen nutzen dieselbe CalDAV-Logik mit Bearer-Token statt Basic-Auth.

**GoogleCalendarAuth** (`google_auth.py`) ist eine httpx.Auth-Klasse fuer Google Calendar OAuth. Haelt einen In-Memory-Cache des Access-Tokens und refresht automatisch via `refresh_token` wenn abgelaufen. Wird pro Sync-Lauf instanziiert.

**iCalendar Parser** (`ical_parser.py`) ist ein Shared Parser fuer VEVENT-Daten, genutzt von CalDAV und ICS-Sync. Unterstuetzt RRULE-Expansion fuer wiederkehrende Termine (DAILY, WEEKLY, MONTHLY, YEARLY, BYDAY, BYMONTH, EXDATE, UNTIL, COUNT). Max 500 Occurrences pro Event. Abhaengigkeit: `python-dateutil`.

**Google Calendar OAuth Flow** (`web.py`): `/ui/api/calendar/google/connect` leitet zu Google OAuth mit Calendar-Scope weiter. Der Callback `/ui/callback/google/calendar` tauscht den Code gegen Tokens, entdeckt alle Kalender via Google Calendar REST API und erstellt automatisch `calendar_sources`-Eintraege. Separater Flow vom Login-OAuth (anderer Scope, anderer Callback).

APScheduler fuer taeglichen Sync: CardDAV 03:00 (wenn `carddav_url` konfiguriert), Kalenderquellen 03:20 (wenn Quellen vorhanden). Neue Kalenderquellen werden ueber die Web-UI verwaltet und automatisch gesynct.

### 3.16 MCP Client (`src/niles/mcp/client.py`)

MCP Server Manager fuer externe Tool-Integrationen. Konfiguration via `config/mcp_servers.yaml`.

**Destructive Tool Blocking:** Bei der Tool-Entdeckung werden MCP-Tools mit destruktiven Namenspraefixen automatisch geblockt (delete, remove, drop, destroy, purge, erase, wipe, truncate, clear). Case-insensitive. Geblockte Tools werden geloggt aber nicht registriert. Dies verhindert, dass ein MCP-Server versehentlich Loesch-Faehigkeiten an das LLM exponiert.

### 3.17 Task Management (`src/niles/actions/tasks.py`)

Interface zur Vikunja REST API. Feature-Flag-gesteuert (`feature_vikunja`). Task-Tools werden nur an das LLM gesendet wenn Vikunja konfiguriert ist.

```python
class TasksAction:
    def __init__(self, api_url: str, api_token: str): ...
    async def list_tasks(self, project="", include_done=False) -> list[dict]
    async def create_task(self, title, description="", due_date="",
                          priority=0, project="") -> dict
    async def complete_task(self, title: str) -> dict
```

- `list_tasks`: GET /tasks/all, Ergebnis-Vereinfachung fuer LLM-Kontext (max 50 Aufgaben)
- `create_task`: PUT /projects/{id}/tasks, unterstuetzt Projekt-Zuweisung, Faelligkeit und Prioritaet (0-4)
- `complete_task`: Sucht offene Aufgaben nach Titel, markiert als erledigt (POST /tasks/{id}). Fehler bei keinem oder mehreren Treffern.
- Default-Projekt-ID wird gecacht (erster Aufruf loest HTTP-Request aus)

### 3.18 Briefing (`src/niles/actions/briefing.py`, `src/niles/jobs/briefing.py`)

Automatische Tages- und Wochen-Uebersicht per WhatsApp. Kein LLM — reine DB-Abfragen + Template-Formatierung.

```python
class BriefingGenerator:
    def __init__(self, pool, timezone, vikunja_api_url, vikunja_api_token): ...
    async def generate_daily(self) -> str    # Mo-Fr: Termine + Tasks
    async def generate_weekly(self) -> str   # Mo: Woche nach Tagen (Mo-Fr)
```

- **Taeglich (Mo-Fr):** Heutige Termine, ueberfaellige Tasks, heute faellige Tasks, Zusammenfassung offener Aufgaben
- **Woechentlich (Mo):** Mo-Fr Termine nach Tagen gruppiert, offene Aufgaben kompakt
- **Events:** SQL SELECT aus `events`-Tabelle (mit `calendar_sources` JOIN)
- **Tasks:** Vikunja REST API (`GET /tasks/all?filter=done=false`), optional (leer wenn nicht konfiguriert)
- **Scheduler:** APScheduler Cron-Jobs (`briefing_daily`, `briefing_weekly`), registriert wenn Feature-Flag aktiv
- **Versand:** Via `WhatsAppAction.send_message()` an automatisch erkannte verbundene Nummer (Evolution API `get_connection_state` + `get_owner_jid`)
- **Settings-UI:** Toggle und Uhrzeiten konfigurierbar. WhatsApp muss verbunden sein

---

## 4. Datenbankschema

Alle Tabellen liegen in der Datenbank `evolution_db` (User `evolution`). Tabellen werden beim Start automatisch erstellt (`CREATE TABLE IF NOT EXISTS`).

### users

```sql
-- Erstellt durch UserStore (Google OAuth)
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL,
    avatar_url TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    last_login TIMESTAMP DEFAULT NOW()
);
```

### whatsapp_sessions

```sql
-- Erstellt durch WhatsAppSessionStore (Per-User WhatsApp Instances)
CREATE TABLE IF NOT EXISTS whatsapp_sessions (
    user_id INTEGER PRIMARY KEY REFERENCES users(id),
    instance_name TEXT UNIQUE NOT NULL,
    phone_number TEXT,
    status TEXT NOT NULL DEFAULT 'disconnected'
        CHECK (status IN ('disconnected', 'connecting', 'connected')),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### contacts

```sql
-- Erstellt/befuellt durch CardDAV-Sync
CREATE TABLE contacts (
    id SERIAL PRIMARY KEY,
    full_name TEXT,
    first_name TEXT,
    last_name TEXT,
    phone_primary TEXT,   -- Legacy, wird durch contact_phones ersetzt
    phone_mobile TEXT,    -- Legacy
    phone_work TEXT,      -- Legacy
    email TEXT,
    cardav_uid TEXT,
    cardav_url TEXT
);
```

### contact_phones

```sql
-- Multi-Phone Support (1:N pro Kontakt)
CREATE TABLE IF NOT EXISTS contact_phones (
    id SERIAL PRIMARY KEY,
    contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    type TEXT NOT NULL,      -- 'mobile', 'home', 'work', 'other'
    number TEXT NOT NULL,
    UNIQUE (contact_id, type, number)
);
```

### memory

```sql
CREATE TABLE IF NOT EXISTS memory (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_memory_updated
ON memory (updated_at DESC);
```

### conversations

```sql
CREATE TABLE IF NOT EXISTS conversations (
    id SERIAL PRIMARY KEY,
    chat_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_conversations_chat
ON conversations (chat_id, created_at);
```

### calendar_sources

```sql
-- Erstellt durch CalendarSourceManager (sync/manager.py)
CREATE TABLE IF NOT EXISTS calendar_sources (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    source_type TEXT NOT NULL DEFAULT 'ics',   -- 'ics', 'caldav', 'google'
    writable BOOLEAN DEFAULT FALSE,
    enabled BOOLEAN DEFAULT TRUE,
    auth_user TEXT,
    auth_password TEXT,
    google_refresh_token TEXT,
    google_token_expiry TIMESTAMP WITH TIME ZONE,
    last_synced TIMESTAMP WITH TIME ZONE,
    last_error TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(url, source_type)
);
```

### events (Erweiterung)

```sql
-- source_id verknuepft Events mit ihrer Kalenderquelle (NULL = Legacy)
ALTER TABLE events ADD COLUMN IF NOT EXISTS
    source_id INTEGER REFERENCES calendar_sources(id) ON DELETE CASCADE;
CREATE INDEX IF NOT EXISTS idx_events_source_id ON events (source_id);
```

`ON DELETE CASCADE` entfernt automatisch alle Events einer Quelle beim Loeschen.

### settings_overrides

```sql
-- Runtime Settings, editierbar ueber Web-UI
CREATE TABLE IF NOT EXISTS settings_overrides (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW()
);
```

---

## 5. Security

### 5.1 Netzwerk

- **HTTPS via Caddy:** Alle externen Zugriffe ueber self-signed TLS-Zertifikate (`tls internal`)
- **Keine exponierten Ports:** PostgreSQL, Niles Core und Evolution API sind nur via Docker-Netzwerk erreichbar
- **Security Headers (Caddy + Middleware):** `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`, Server-Header entfernt
- **CSP:** `default-src 'self'; script-src 'self' https://unpkg.com https://cdn.jsdelivr.net; style-src 'self'; img-src 'self' data: https://*.googleusercontent.com; connect-src 'self'`
- **CDN-Ressourcen** (htmx, marked.js, DOMPurify): SRI-Hashes fuer Integritaetspruefung

### 5.2 Authentifizierung

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

### 5.3 Rate Limiting

- In-Memory Rate Limiter: 60 Requests/Minute pro Client-IP
- `/health` und `/static` sind exempt
- Memory Safeguard: Max 10.000 IPs tracked, aelteste werden evicted
- HTTP 429 bei Ueberschreitung

### 5.4 Docker

- Niles Core laeuft als Non-Root User (UID/GID 1000)
- PostgreSQL-Port nicht exponiert

### 5.5 Access Logs

- Caddy schreibt JSON-formatierte Access Logs pro Service
- Log-Rotation: 10 MB pro Datei, 3 Dateien behalten
- Dateien: `access-niles.log`, `access-evolution.log`

### 5.6 Datenintegritaet (Keine Loeschungen)

Niles folgt dem Prinzip **"Lesen und Erstellen, niemals Loeschen"**:

- **Kein LLM-Tool hat Loesch-Faehigkeiten.** `complete_task` markiert Aufgaben als erledigt (kein Delete). `remember` ueberschreibt per UPSERT (kein Delete).
- **`MemoryStore.delete()` existiert** aber ist NICHT als Tool exponiert — nur intern fuer Web-UI.
- **MCP-Tools:** Destruktive Namenspraefixe werden automatisch geblockt (§3.16).
- **Evolution API:** Niles nutzt nur `sendText` und `findMessages` — keine Delete-Endpunkte.
- **soul.md Regel 7:** Das LLM wird explizit angewiesen, dass es keine Daten loeschen kann und bei Loesch-Anfragen auf die jeweilige App verweisen soll.

| Integration | Lesen | Erstellen | Aendern | Loeschen |
| ----------- | ----- | --------- | ------- | -------- |
| WhatsApp (Evolution) | Ja | Ja (senden) | Nein | Nein |
| Kalender (CalDAV/Google) | Ja | Ja | Nein | Nein |
| Tasks (Vikunja) | Ja | Ja | Ja (complete) | Nein |
| Kontakte (CardDAV) | Ja | Nein | Nein | Nein |
| Memory (PostgreSQL) | Ja | Ja | Ja (update) | Nein |

---

## 6. Konfiguration

### 6.1 Settings

Pydantic Settings (`src/niles/config.py`) laedt Werte aus `.env` und Environment-Variablen. `extra = "ignore"` verhindert Fehler bei unbekannten Variablen.

| Feld | Default | Env-Variable | Pflicht |
| ---- | ------- | ------------ | ------- |
| `log_level` | `"INFO"` | `LOG_LEVEL` | Nein |
| `llm_base_url` | `"http://host.docker.internal:11434/v1"` | `LLM_BASE_URL` | Nein |
| `llm_model` | `"llama3.1:8b"` | `LLM_MODEL` | Nein |
| `postgres_host` | `"evolution_postgres"` | `POSTGRES_HOST` | Nein |
| `postgres_port` | `5432` | `POSTGRES_PORT` | Nein |
| `postgres_db` | `"evolution_db"` | `POSTGRES_DB` | Nein |
| `postgres_user` | `"evolution"` | `POSTGRES_USER` | Nein |
| `postgres_password` | -- | `EVOLUTION_POSTGRES_PASSWORD` | Ja |
| `evolution_api_url` | `"http://evolution_api:8080"` | `EVOLUTION_API_URL` | Nein |
| `evolution_api_key` | -- | `EVOLUTION_API_KEY` | Ja |
| `evolution_instance` | `"niles-whatsapp"` | `EVOLUTION_INSTANCE` | Nein |
| `niles_api_key` | auto-generiert | `NILES_API_KEY` | Nein |
| `session_secret` | auto-generiert | `SESSION_SECRET` | Nein |
| `base_url` | `""` | `BASE_URL` | Nein\* |
| `timezone` | `"Europe/Vienna"` | `TIMEZONE` | Nein |
| `feature_whatsapp_send_others` | `true` | `FEATURE_WHATSAPP_SEND_OTHERS` | Nein |
| `carddav_url` | `""` | `CARDDAV_URL` | Nein |
| `carddav_user` | `""` | `CARDDAV_USER` | Nein |
| `carddav_password` | `""` | `CARDDAV_PASSWORD` | Nein |
| `caldav_url` | `"https://dav.example.com/caldav/"` | `CALDAV_URL` | Nein\* |
| `caldav_user` | `""` | `CALDAV_USER` | Nein\* |
| `caldav_password` | `""` | `CALDAV_PASSWORD` | Nein\* |
| `caldav_calendars` | `""` | `CALDAV_CALENDARS` | Nein\* |
| `google_client_id` | `""` | `GOOGLE_CLIENT_ID` | Nein\*\* |
| `google_client_secret` | `""` | `GOOGLE_CLIENT_SECRET` | Nein\*\* |
| `google_allowed_emails` | `""` | `GOOGLE_ALLOWED_EMAILS` | Nein |
| `vikunja_api_url` | `""` | `VIKUNJA_API_URL` | Nein\*\*\* |
| `vikunja_api_token` | `""` | `VIKUNJA_API_TOKEN` | Nein\*\*\* |
| `feature_vikunja` | `false` | `FEATURE_VIKUNJA` | Nein |
| `feature_briefing_daily` | `false` | `FEATURE_BRIEFING_DAILY` | Nein |
| `feature_briefing_weekly` | `false` | `FEATURE_BRIEFING_WEEKLY` | Nein |
| `briefing_daily_time` | `"07:30"` | `BRIEFING_DAILY_TIME` | Nein |
| `briefing_weekly_time` | `"07:15"` | `BRIEFING_WEEKLY_TIME` | Nein |

\* `base_url` wird empfohlen wenn Google OAuth hinter einem Reverse Proxy laeuft (verhindert Redirect-URI aus untrusted Headers).

\*\* Pflicht wenn Google OAuth gewuenscht. Ohne Google OAuth wird API-Key Login verwendet.

\*\*\* Pflicht wenn Vikunja-Integration gewuenscht. Erfordert zusaetzlich `FEATURE_VIKUNJA=true`.

Briefing: WhatsApp-Nummer wird automatisch erkannt (verbundene Instanz). Keine manuelle Konfiguration noetig.

\* `caldav_url/user/password` sind Legacy-Felder. Beim ersten Start werden sie automatisch in die `calendar_sources`-Tabelle migriert. Neue Kalenderquellen werden ueber die Web-UI verwaltet (Settings > Kalenderquellen).

`postgres_password` verwendet `validation_alias="EVOLUTION_POSTGRES_PASSWORD"` -- die Env-Variable heisst anders als das Python-Feld, weil die bestehende PostgreSQL-Instanz bereits diese Variable erwartet.

### 6.2 Runtime Overrides

Feature-Flags und ausgewaehlte Text-Settings (siehe `EDITABLE_SETTINGS` in §3.7) koennen ueber die Web-UI geaendert werden. Aenderungen werden in der `settings_overrides`-Tabelle persistiert und beim Start geladen via `apply_overrides()`.

### 6.3 .env Template

```bash
# Pflicht
EVOLUTION_POSTGRES_PASSWORD=<passwort>
EVOLUTION_API_KEY=<api-key>

# Session (empfohlen fuer stabile Sessions ueber Container-Restarts)
SESSION_SECRET=<zufaelliger-string>
BASE_URL=https://niles.example.com

# Google OAuth (optional)
GOOGLE_CLIENT_ID=<client-id>
GOOGLE_CLIENT_SECRET=<client-secret>
GOOGLE_ALLOWED_EMAILS=user1@gmail.com,user2@gmail.com

# Vikunja (optional)
VIKUNJA_API_URL=http://vikunja:3456/api/v1
VIKUNJA_API_TOKEN=<api-token>
FEATURE_VIKUNJA=false

# Optional
NILES_API_KEY=<api-key>
CARDDAV_USER=<user>
CARDDAV_PASSWORD=<passwort>
LOG_LEVEL=INFO
```

### 6.4 Environment-Variablen

**Pflicht:** `EVOLUTION_POSTGRES_PASSWORD`, `EVOLUTION_API_KEY`.

**Optional:** `NILES_API_KEY`, `SESSION_SECRET`, `BASE_URL`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_ALLOWED_EMAILS`, `CARDDAV_URL`, `CARDDAV_USER`, `CARDDAV_PASSWORD`, `CALDAV_URL`, `CALDAV_USER`, `CALDAV_PASSWORD`, `CALDAV_CALENDARS` (Legacy, auto-migriert in DB), `VIKUNJA_API_URL`, `VIKUNJA_API_TOKEN`, `FEATURE_VIKUNJA`, `VIKUNJA_JWT_SECRET` (Docker only), `FEATURE_BRIEFING_DAILY`, `FEATURE_BRIEFING_WEEKLY`, `BRIEFING_DAILY_TIME`, `BRIEFING_WEEKLY_TIME`, `LOG_LEVEL`, `LLM_BASE_URL`, `LLM_MODEL`, `TIMEZONE`, `EVOLUTION_API_URL`, `EVOLUTION_INSTANCE`, `FEATURE_WHATSAPP_SEND_OTHERS`, `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_HOST_PORT` (Docker-Debugging).

Siehe `.env.example` fuer vollstaendige Dokumentation.

---

## 7. Docker

### 7.1 Dockerfile (`docker/Dockerfile.niles`)

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

### 7.2 Docker Compose Services

| Container | Image | Exponierter Port | Zweck |
| --------- | ----- | ---------------- | ----- |
| `niles_caddy` | `caddy:2-alpine` | 443, 8443 | HTTPS Reverse Proxy |
| `niles_core` | Build (Dockerfile.niles) | -- (via Caddy) | Python Backend + Web-UI |
| `niles_evolution_postgres` | `postgres:15-alpine` | -- | PostgreSQL |
| `niles_evolution_api` | `evoapicloud/evolution-api:v2.3.7` | -- (via Caddy) | WhatsApp Gateway |
| `vikunja` | `vikunja/vikunja:latest` | 3456 | Todo/Task Management |

### 7.3 Netzwerk

Alle Container im Bridge-Netzwerk `niles_network`. Container-Namen dienen als Hostnamen fuer die interne Kommunikation:

- `niles_core` -> `evolution_postgres:5432`
- `niles_core` -> `evolution_api:8080` (nur fuer WhatsApp senden)
- `evolution_api` -> `niles_core:8000` (Webhook)
- `niles_core` -> `vikunja:3456` (Task Management API)
- `niles_core` -> `host.docker.internal:11434` (Ollama auf dem Host)

### 7.4 Volumes

| Volume | Mount | Zweck |
| ------ | ----- | ----- |
| `evolution_postgres` | `/var/lib/postgresql/data` | PostgreSQL-Daten |
| `vikunja_files` | `/app/vikunja/files` | Vikunja-Dateien |
| `caddy_data` | `/data` | TLS-Zertifikate |
| `caddy_config` | `/config` | Caddy-Konfiguration |
| `~/.evolution/instances` | `/evolution/instances` | WhatsApp-Sessions |
| `../src` | `/app/src` | Live-Reload (Dev) |
| `../config` | `/app/config:ro` | Agent-Konfiguration |

### 7.5 Dev-Modus

Im `docker-compose.yml` ueberschreibt der `command` das Dockerfile-CMD:

```yaml
command: uvicorn niles.main:app --host 0.0.0.0 --port 8000 --reload
```

Zusammen mit dem Volume-Mount `../src:/app/src` ermoeglicht das Live-Reload bei Code-Aenderungen.

---

## 8. Technologie-Stack & Dependencies

| Komponente | Technologie | Version |
| ---------- | ----------- | ------- |
| Runtime | Python | >= 3.11 |
| Web Framework | FastAPI | >= 0.129.0 |
| ASGI Server | uvicorn | >= 0.41.0 |
| HTTP Client | httpx | >= 0.28.1 |
| PostgreSQL Driver | asyncpg | >= 0.31.0 |
| LLM Client | openai (Python SDK) | >= 2.21.0 |
| Config | pydantic-settings | >= 2.13.0 |
| Templates | Jinja2 | >= 3.1.0 |
| Session Signing | itsdangerous | >= 2.0 |
| CSS Framework | Tailwind CSS | v3.4.17 (Standalone CLI) |
| Markdown Rendering | marked.js + DOMPurify | CDN (SRI) |
| Frontend Interaktion | htmx | 2.0.4 (CDN) |
| RRULE Expansion | python-dateutil | >= 2.8.0 |
| Scheduling | APScheduler | >= 3.11.2 |
| Container | Docker Compose | -- |
| LLM Inference | Ollama (nativ auf Host) | lokal |
| WhatsApp Gateway | Evolution API | v2.3.7 |

### pyproject.toml Dependencies

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
python-dateutil>=2.8.0    # RRULE Expansion (Wiederkehrende Kalendertermine)
```

Dev: `pytest>=9.0.0`, `pytest-asyncio>=1.3.0`, `httpx` (TestClient).

---

## 9. Implementierungsstatus

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
| -- | `feat/whatsapp-per-user-sessions` | #22 | Abgeschlossen | Per-User WhatsApp Sessions, Multi-Phone, RRULE, CardDAV UI |
| -- | `feat/whatsapp-self-chat` | #25 | Abgeschlossen | WhatsApp Self-Chat ("Hey Niles" Trigger), TRANSP (busy/free), Feature-Flag-Umbau |
| -- | `fix/calendar-filter-guard` | #26 | Abgeschlossen | Calendar-Filter-Guard, Hallucination-Guard (hinweis-Feld) |
| -- | `feat/whatsapp-inbox` | #29 | Abgeschlossen | WhatsApp Inbox (findMessages statt lokale DB), LID-Adressierung, Zusammenfassungs-Metadaten, MCP Destructive-Tool-Blocking, No-Delete-Policy |

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

**PR #22 -- Abgeschlossen (WhatsApp per-user Sessions):**

- Per-User WhatsApp Sessions (eigene Evolution API Instance pro Web-UI User)
- WhatsApp verbinden/trennen ueber Web-UI (QR-Code)
- Per-User Instance Routing bei Webhook-Empfang
- Multi-Phone Support (contact_phones Tabelle, 1:N)
- Multi-Phone Choice Flow (LLM-Bypass, nummerierte Liste, TTL 5 min)
- Multi-Word Kontaktsuche
- RRULE Expansion fuer wiederkehrende Kalendertermine
- CardDAV UI (Verbinden/Trennen/Sync ueber Web-UI)
- Editierbare CardDAV Credentials via Settings

**PR #25 -- Abgeschlossen (WhatsApp Self-Chat + TRANSP):**

- WhatsApp Self-Chat: "Hey Niles" Trigger (case-insensitive, word-boundary)
- Trigger-Stripping, Echo-Loop-Guard (_sent_ids Cache, TTL 10s)
- Eigene chat_id `wa-self-{nummer}` fuer separate History
- Fremde Nachrichten: kein LLM-Call, kein Web-Chat. Agent liest via Evolution API `findMessages` (30-Tage-Window, Tool `get_whatsapp_messages`)
- Feature-Flag-Umbau: `feature_whatsapp_auto_reply` + `feature_tool_send_whatsapp` → `feature_whatsapp_send_others`
- TRANSP (Beschaeftigt/Verfuegbar): iCalendar TRANSP Property (RFC 5545) durch gesamte Pipeline (Parser → DB → Sync → Query → API)
- Kalender-Events mit `status: "verfuegbar"` wenn TRANSP=TRANSPARENT

**PR #26 -- Abgeschlossen (Calendar Filter Guard):**

- Calendar-Filter-Guard: Droppt `calendar`-Filter wenn `query` leer ist (verhindert LLM-Fehler)
- Hallucination-Guard: `hinweis`-Feld in find_event-Ergebnissen ("Nenne NUR diese Termine")

---

## 10. Hinweise

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

---

## 11. Weitere Dokumentation

- [API Reference](API.md) -- Endpoints, Payloads, Beispiele
- [Development Guide](Development.md) -- Setup, Testing, Konventionen
