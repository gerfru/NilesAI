# Niles AI Core -- Architektur

> **Stand:** 2026-02-19

---

## 1. Systemuebersicht

```text
Browser / curl / WhatsApp
    |
    v  HTTPS (Caddy, self-signed)
┌──────────────────────────────────────────────────┐
│  Caddy Reverse Proxy                             │
│  :443  -> niles_core:8000                        │
│  :8443 -> evolution_api:8080                     │
│  Security Headers, Access Logs                   │
└──────────────┬───────────────────────────────────┘
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
                         │                                │
                         │  GET  /health (unauthenticated) │
                         │  POST /chat (API Key)          │
                         │  POST /webhook/whatsapp (token) │
                         │  /ui/* (Session Cookie / OAuth) │
                         └────────────────────────────────┘
```

Alle Komponenten laufen in Docker-Containern im selben Netzwerk (`niles_network`). Ollama laeuft nativ auf dem Host und ist ueber `host.docker.internal:11434` erreichbar.

---

## 2. Modulstruktur

```text
src/niles/
├── main.py              # FastAPI App, Lifespan, Middleware, /chat, /health
├── config.py            # Pydantic Settings + apply_overrides()
├── user_store.py        # User-Verwaltung (Google OAuth, PostgreSQL)
├── settings_store.py    # Runtime Settings Overrides (PostgreSQL)
├── agent/
│   ├── core.py          # NilesAgent, Tool-Call-Pipeline
│   └── prompts.py       # System Prompt laden/bauen
├── memory/
│   ├── store.py         # Key-Value Memory (PostgreSQL)
│   └── history.py       # Konversations-Historie (PostgreSQL)
├── actions/
│   ├── whatsapp.py      # WhatsApp senden (Evolution API)
│   ├── contacts.py      # Kontakt-Lookup (PostgreSQL)
│   └── calendar.py      # Kalender-Abfragen (PostgreSQL)
├── sources/
│   ├── whatsapp.py      # Webhook-Handler (Evolution API)
│   └── web.py           # Web-UI Router (htmx, Google OAuth, Sessions)
├── sync/
│   ├── carddav.py       # CardDAV Kontakt-Sync
│   ├── caldav.py        # CalDAV Kalender-Sync
│   ├── google_auth.py   # Google Calendar OAuth (Bearer Token + Refresh)
│   ├── ical_parser.py   # Shared iCalendar Parser (VEVENT -> dict)
│   └── manager.py       # CalendarSourceManager (CRUD, Sync, Migration)
├── mcp/
│   └── client.py        # MCP Server Manager
├── templates/
│   ├── base.html        # Layout (Nav, CSP, Tailwind CSS, htmx)
│   ├── login.html       # Login (Google OAuth + API-Key Fallback)
│   ├── chat.html        # Chat-UI mit SSE Streaming
│   ├── settings.html    # Settings Dashboard
│   └── fragments/       # htmx-Fragmente (message, history, toast, calendars, calendar_sources)
└── static/
    ├── css/
    │   ├── input.css    # Tailwind Direktiven + Custom Components
    │   └── style.css    # Generierter Tailwind Output
    └── js/app.js        # SSE Chat-Streaming, Dark Mode, CSRF
```

### agent/

Zentrale Event-Verarbeitung. `NilesAgent` empfaengt Events, baut den LLM-Kontext (System Prompt + Memory + History + User-Nachricht), ruft das LLM auf und fuehrt Tool-Calls aus. `prompts.py` laedt die Agent-Persoenlichkeit aus `config/soul.md` und injiziert Memory-Eintraege in den System Prompt.

### memory/

Persistente Datenhaltung fuer den Agent. `MemoryStore` ist ein Key-Value Store (JSONB) fuer Fakten und Wissen. `ConversationHistory` speichert den Nachrichtenverlauf pro Chat-ID fuer LLM-Kontext.

### actions/

Ausfuehrbare Aktionen, die der Agent ueber Tool-Calls triggern kann. `WhatsAppAction` sendet Nachrichten ueber die Evolution API. `ContactsAction` sucht Kontakte in PostgreSQL. `CalendarAction` fragt Kalender-Events ab.

### sources/

Event-Quellen, die eingehende Nachrichten empfangen und an den Agent weiterleiten. `whatsapp.py` ist ein FastAPI-Router fuer Evolution API Webhooks. `web.py` ist der Web-UI Router mit Google OAuth, Session Management und htmx-Endpoints.

### sync/

Hintergrund-Synchronisation externer Datenquellen. `carddav.py` synchronisiert Kontakte, `caldav.py` synchronisiert Kalender-Events via CalDAV-Protokoll (PROPFIND/REPORT). `ical_parser.py` ist ein Shared Parser fuer iCalendar-Daten (VEVENT -> dict), genutzt von CalDAV und ICS-Sync. `google_auth.py` implementiert eine httpx.Auth-Klasse fuer Google Calendar OAuth (Bearer Token mit automatischem Refresh via refresh_token). `manager.py` enthaelt den `CalendarSourceManager`, der alle Kalenderquellen verwaltet (CRUD, Sync-Orchestrierung, Auto-Migration von `.env` CalDAV-Config). Sync-Jobs laufen als Cronjobs via APScheduler.

### templates/ & static/

Jinja2 Templates fuer die Web-UI. `base.html` definiert das Layout (Tailwind CSS, htmx, Navigation mit User-Avatar). Templates verwenden Tailwind Utility Classes fuer Styling. Dark Mode via `class="dark"` auf `<html>`. Chat-Antworten werden via SSE gestreamt (Wort fuer Wort), Markdown client-seitig gerendert (marked.js + DOMPurify). `static/css/input.css` enthaelt Tailwind-Direktiven und Custom Components (Toggle-Switch, Animationen), `style.css` ist der generierte Output (via Tailwind CLI).

---

## 3. Datenfluss: WhatsApp-Nachricht

```text
1. Evolution API empfaengt WhatsApp-Nachricht
2. Evolution API sendet Webhook POST an /webhook/whatsapp
3. sources/whatsapp.py filtert auf messages.upsert, ignoriert fromMe
4. Extrahiert Absender (JID -> Telefonnummer) und Text
5. Erstellt Event: {"type": "whatsapp", "from": "4366...", "content": "..."}
6. Ruft agent.process_event(event) auf
   6a. Laedt alle Memory-Eintraege -> injiziert in System Prompt
   6b. Laedt letzte 20 Nachrichten der Konversation
   6c. Baut Messages: [system, ...history, user]
   6d. Speichert User-Nachricht in History
   6e. Ruft LLM auf (OpenAI-kompatible API)
   6f. Falls Tool-Calls: ausfuehren, Ergebnisse zurueck an LLM (max 5 Runden)
   6g. Speichert Antwort in History
7. sources/whatsapp.py sendet Antwort via WhatsAppAction zurueck
8. Gibt HTTP 200 zurueck (unabhaengig vom Ergebnis)
```

## 4. Datenfluss: Web-UI Chat (SSE Streaming)

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

## 5. Datenfluss: Google OAuth Login

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

## 6. Datenbankschema

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

### contacts

```sql
-- Erstellt/befuellt durch CardDAV-Sync
CREATE TABLE contacts (
    id SERIAL PRIMARY KEY,
    full_name TEXT,
    first_name TEXT,
    last_name TEXT,
    phone_primary TEXT,
    phone_mobile TEXT,
    phone_work TEXT,
    email TEXT
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

## 7. Konfiguration

### Settings (`src/niles/config.py`)

Pydantic Settings laedt Werte aus `.env` und Environment-Variablen. `extra = "ignore"` verhindert Fehler bei unbekannten Variablen.

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
| `base_url` | `""` | `BASE_URL` | Nein* |
| `timezone` | `"Europe/Vienna"` | `TIMEZONE` | Nein |
| `feature_whatsapp_auto_reply` | `false` | `FEATURE_WHATSAPP_AUTO_REPLY` | Nein |
| `feature_tool_send_whatsapp` | `true` | `FEATURE_TOOL_SEND_WHATSAPP` | Nein |
| `feature_carddav_sync` | `false` | `FEATURE_CARDDAV_SYNC` | Nein |
| `feature_caldav_sync` | `false` | `FEATURE_CALDAV_SYNC` | Nein |
| `carddav_url` | `"https://dav.example.com/carddav/32"` | `CARDDAV_URL` | Nein |
| `carddav_user` | `""` | `CARDDAV_USER` | Nein |
| `carddav_password` | `""` | `CARDDAV_PASSWORD` | Nein |
| `caldav_url` | `"https://dav.example.com/caldav/"` | `CALDAV_URL` | Nein* |
| `caldav_user` | `""` | `CALDAV_USER` | Nein* |
| `caldav_password` | `""` | `CALDAV_PASSWORD` | Nein* |
| `google_client_id` | `""` | `GOOGLE_CLIENT_ID` | Nein** |
| `google_client_secret` | `""` | `GOOGLE_CLIENT_SECRET` | Nein** |
| `google_allowed_emails` | `""` | `GOOGLE_ALLOWED_EMAILS` | Nein |

\* `base_url` wird empfohlen wenn Google OAuth hinter einem Reverse Proxy laeuft (verhindert Redirect-URI aus untrusted Headers).

\*\* Pflicht wenn Google OAuth gewuenscht. Ohne Google OAuth wird API-Key Login verwendet.

\* `caldav_url/user/password` sind Legacy-Felder. Beim ersten Start werden sie automatisch in die `calendar_sources`-Tabelle migriert. Neue Kalenderquellen werden ueber die Web-UI verwaltet (Settings > Kalenderquellen).

`postgres_password` verwendet `validation_alias="EVOLUTION_POSTGRES_PASSWORD"` -- die Env-Variable heisst anders als das Python-Feld, weil die bestehende PostgreSQL-Instanz bereits diese Variable erwartet.

### Runtime Settings Overrides

Feature-Flags und ausgewaehlte Text-Settings (siehe `EDITABLE_SETTINGS` in `settings_store.py`) koennen ueber die Web-UI geaendert werden. Aenderungen werden in der `settings_overrides` Tabelle persistiert und beim Start geladen via `apply_overrides()`.

### .env

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

# Optional
NILES_API_KEY=<api-key>
CARDDAV_USER=<user>
CARDDAV_PASSWORD=<passwort>
LOG_LEVEL=INFO
```

---

## 8. Docker

### Container

| Container | Image | Port | Zweck |
| --------- | ----- | ---- | ----- |
| `niles_core` | Build aus `docker/Dockerfile.niles` | 8000 | Niles Python Backend |
| `niles_evolution_postgres` | `postgres:15-alpine` | 5432 | PostgreSQL |
| `niles_evolution_api` | `evoapicloud/evolution-api:v2.3.7` | 8080 | WhatsApp Gateway |
| `niles_caddy` | `caddy:2-alpine` | 443/8443 | Reverse Proxy (HTTPS) |

### Netzwerk

Alle Container im Bridge-Netzwerk `niles_network`. Container-Namen dienen als Hostnamen fuer die interne Kommunikation:

- `niles_core` -> `evolution_postgres:5432`
- `niles_core` -> `evolution_api:8080` (nur fuer WhatsApp senden)
- `evolution_api` -> `niles_core:8000` (Webhook)
- `niles_core` -> `host.docker.internal:11434` (Ollama auf dem Host)

### Volumes

| Volume | Mount | Zweck |
| ------ | ----- | ----- |
| `evolution_postgres` | `/var/lib/postgresql/data` | PostgreSQL-Daten |
| `caddy_data` | `/data` | TLS-Zertifikate |
| `caddy_config` | `/config` | Caddy-Konfiguration |
| `~/.evolution/instances` | `/evolution/instances` | WhatsApp-Sessions |
| `../src` | `/app/src` | Live-Reload (Dev) |
| `../config` | `/app/config:ro` | Agent-Konfiguration |

### Dev-Modus

Im `docker-compose.yml` ueberschreibt der `command` das Dockerfile-CMD:

```yaml
command: uvicorn niles.main:app --host 0.0.0.0 --port 8000 --reload
```

Zusammen mit dem Volume-Mount `../src:/app/src` ermoeglicht das Live-Reload bei Code-Aenderungen.

---

## 9. Technologie-Stack

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
| Scheduling | APScheduler | >= 3.11.2 |
| Container | Docker Compose | -- |
| LLM Inference | Ollama (nativ auf Host) | lokal |
| WhatsApp Gateway | Evolution API | v2.3.7 |

---

## 10. Weitere Dokumentation

- [Technische Spezifikation](Niles-Core-Spec.md) -- Komponentenbeschreibung und Roadmap
- [API Reference](API.md) -- Endpoints, Payloads, Beispiele
- [Development Guide](Development.md) -- Setup, Testing, Konventionen
