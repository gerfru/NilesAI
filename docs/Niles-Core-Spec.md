# Niles AI Core -- Technische Spezifikation

> **Version:** 3.0
> **Stand:** 2026-02-18
> **Status:** Stage 1-5 implementiert, Stage 6-8 geplant

---

## 1. Projektuebersicht

### 1.1 Vision

Niles ist ein lokaler, privater AI-Butler auf einem Mac Mini M4. Er empfaengt Events aus verschiedenen Quellen (WhatsApp, Email, Kalender), verarbeitet sie mit einem lokalen LLM und fuehrt Aktionen aus.

### 1.2 Kernprinzipien

- **KISS** -- Keep It Simple, Stupid
- **100% Lokal** -- Keine Cloud-Abhaengigkeiten fuer Core-Funktionen
- **Privacy First** -- Alle Daten bleiben auf dem eigenen Server
- **Erweiterbar** -- MCP-Protokoll fuer Community-Module

### 1.3 Infrastruktur

| Komponente | Interner Port | Externer Zugang | Zweck |
|------------|--------------|-----------------|-------|
| LM Studio (Qwen 2.5 Coder 7B MLX) | 1234 (Host) | http://localhost:1234 | LLM Inference (OpenAI-kompatibel) |
| PostgreSQL | 5432 | Nicht exponiert | Datenbank (evolution_db) |
| Evolution API v2.3.7 | 8080 | https://localhost:8443 | WhatsApp Gateway |
| Niles Core (FastAPI) | 8000 | https://localhost | Python Backend |
| Caddy | -- | :443, :8443, :5678 | HTTPS Reverse Proxy |
| n8n | 5678 | https://localhost:5678 | Legacy Workflows (wird schrittweise ersetzt) |

**Netzwerk-Architektur:** Alle Docker-Services kommunizieren intern via HTTP. Externer Zugriff ausschliesslich ueber Caddy (HTTPS, self-signed). PostgreSQL und Service-Ports sind nicht exponiert.

**Datenbank:** `evolution_db`, User `evolution`, Passwort via `EVOLUTION_POSTGRES_PASSWORD`.

---

## 2. Architektur

### 2.1 Systemuebersicht

```
Externe Clients (Browser, curl, Tailscale)
    |
    v HTTPS (self-signed)
┌─────────────────────────────────────────┐
│  Caddy Reverse Proxy                    │
│  :443 -> niles_core:8000                │
│  :8443 -> evolution_api:8080            │
│  :5678 -> n8n:5678                      │
│  Security Headers, Access Logs          │
└──────────────┬──────────────────────────┘
               | HTTP (intern)
               v
Event Sources                Niles Core (FastAPI :8000)              External
                         ┌────────────────────────────────┐
WhatsApp ─── Webhook ──> │  sources/whatsapp.py           │
                         │         │                      │
                         │         v                      │
POST /chat  ──────────> │  agent/core.py (NilesAgent)    │──> LM Studio :1234
                         │    │  Tool-Call Loop (max 5)   │
                         │    │                           │
                         │    ├─ memory/store.py          │──> PostgreSQL :5432
                         │    ├─ memory/history.py        │──> PostgreSQL :5432
                         │    ├─ actions/contacts.py      │──> PostgreSQL :5432
                         │    └─ actions/whatsapp.py      │──> Evolution API :8080
                         │                                │
                         │  Middleware:                    │
                         │    RateLimitMiddleware (60/min) │
                         │    API Key Auth (X-API-Key)     │
                         │                                │
                         │  GET  /health (unauthenticated) │
                         │  POST /chat (authenticated)    │
                         │  POST /webhook/whatsapp (token) │
                         └────────────────────────────────┘
```

### 2.2 Ordnerstruktur

```
Niles/
├── src/
│   ├── niles/                      # Python Backend
│   │   ├── __init__.py
│   │   ├── main.py                 # FastAPI + Lifespan + RateLimitMiddleware
│   │   ├── config.py               # Pydantic Settings + Feature Flags
│   │   ├── agent/
│   │   │   ├── core.py             # NilesAgent, Tool-Definitionen
│   │   │   └── prompts.py          # System Prompt laden/bauen
│   │   ├── memory/
│   │   │   ├── store.py            # Key-Value Memory (PostgreSQL)
│   │   │   └── history.py          # Konversations-Historie
│   │   ├── actions/
│   │   │   ├── whatsapp.py         # WhatsApp senden (Evolution API)
│   │   │   └── contacts.py         # Kontakt-Lookup + normalize_phone
│   │   ├── sources/
│   │   │   └── whatsapp.py         # Webhook-Handler (Token-Auth)
│   │   └── sync/
│   │       └── carddav.py          # CardDAV Kontakt-Sync
│   └── frontend/                   # Platzhalter
├── tests/
│   ├── conftest.py                 # Shared Fixtures (Env-Variablen)
│   ├── test_config.py
│   ├── test_contacts.py
│   ├── test_health.py
│   ├── test_memory.py
│   ├── test_features.py            # Feature Flags + Webhook Auth
│   ├── test_carddav.py             # CardDAV Sync
│   └── test_security.py            # API Auth, Rate Limiting, Integration Tests
├── config/
│   ├── soul.md                     # Agent-Persoenlichkeit
│   └── mcp_servers.yaml            # MCP-Konfiguration (leer)
├── docker/
│   ├── docker-compose.yml
│   ├── Dockerfile.niles            # Non-root User (UID 1000)
│   └── Caddyfile                   # HTTPS, Security Headers, Access Logs
├── scripts/
│   ├── dev.sh                      # Lokaler Dev-Server
│   ├── test.sh                     # pytest Runner
│   ├── build.sh                    # Docker Images bauen (--clean optional)
│   ├── start.sh                    # Docker starten (mit --build)
│   ├── stop.sh                     # Docker stoppen
│   └── status.sh                   # Service-Status pruefen
├── docs/
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
6. CardDAV Sync initialisieren (+ Scheduler wenn Feature aktiv)
7. Actions und Agent instanziieren
8. Alles auf `app.state` speichern

**Middleware:**
- `RateLimitMiddleware` (60 req/min pro IP, /health exempt, max 10.000 IPs tracked)

**Endpoints:** siehe `docs/API.md`.

### 3.2 Config (`src/niles/config.py`)

```python
class Settings(BaseSettings):
    log_level: str = "INFO"
    llm_base_url: str = "http://host.docker.internal:1234/v1"
    llm_model: str = "qwen2.5-coder-7b-instruct-mlx"
    postgres_host: str = "evolution_postgres"
    postgres_port: int = 5432
    postgres_db: str = "evolution_db"
    postgres_user: str = "evolution"
    postgres_password: str  # validation_alias="EVOLUTION_POSTGRES_PASSWORD"
    evolution_api_url: str = "http://evolution_api:8080"
    evolution_api_key: str  # Required
    evolution_instance: str = "niles-whatsapp"
    niles_api_key: str      # Auto-generated via secrets.token_urlsafe(32)
    feature_whatsapp_auto_reply: bool = False
    feature_tool_send_whatsapp: bool = True
    feature_carddav_sync: bool = False
    carddav_url: str = "https://dav.mailbox.org/carddav/32"
    carddav_user: str = ""
    carddav_password: str = ""
```

Laedt aus `.env` und Environment-Variablen. `extra = "ignore"`.

### 3.3 Agent Core (`src/niles/agent/core.py`)

`NilesAgent` verarbeitet Events ueber eine Tool-Call-Pipeline:

```python
class NilesAgent:
    def __init__(self, config, contacts, whatsapp, memory, history): ...
    async def process_event(self, event: dict) -> str: ...
    async def _execute_tool_call(self, tool_call) -> dict: ...
```

**Event-Format:**
```json
{"type": "whatsapp|chat", "from": "436601234...", "content": "...", "metadata": {}}
```

**Registrierte Tools:**

| Tool | Parameter | Beschreibung |
|------|-----------|-------------|
| `find_contact` | `name: str` | Kontaktsuche in PostgreSQL |
| `send_whatsapp` | `to: str, text: str` | Nachricht senden (Nummer oder Name) |
| `remember` | `key: str, value: str` | Fakt im Memory speichern |
| `recall` | `key: str` | Fakt aus Memory abrufen |

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

`chat_id` entspricht `event["from"]` (Telefonnummer bei WhatsApp, `"api"` bei /chat).

### 3.6 System Prompts (`src/niles/agent/prompts.py`)

```python
def load_system_prompt(path: str | None = None) -> str
def build_system_prompt(base_prompt: str, memories: list[dict]) -> str
```

`load_system_prompt` laedt `config/soul.md`. `build_system_prompt` haengt einen "Dein Gedaechtnis"-Abschnitt mit allen Memory-Eintraegen an.

### 3.7 WhatsApp Source (`src/niles/sources/whatsapp.py`)

Webhook-Handler fuer Evolution API v2.3.7:

- Token-Authentifizierung via Query-Parameter (`?token=...`, hmac.compare_digest)
- Filtert auf `event == "messages.upsert"`
- Ignoriert eigene Nachrichten (`fromMe: true`)
- Extrahiert Text aus `message.conversation` oder `extendedTextMessage.text`
- Gibt 401 fuer Auth-Fehler zurueck, 200 fuer alle anderen Faelle (verhindert Retry-Spam)
- Fehler werden geloggt, nicht propagiert

**Hinweis:** Webhook-Token wird als Query-Parameter uebergeben, da Evolution API v2.3.x keine Custom-Header unterstuetzt (siehe [Issue #1933](https://github.com/EvolutionAPI/evolution-api/issues/1933)).

### 3.8 WhatsApp Action (`src/niles/actions/whatsapp.py`)

```python
class WhatsAppAction:
    async def send_message(self, to: str, text: str) -> dict
```

Sendet via `POST /message/sendText/{instance}` an Evolution API. Timeout 30s.

### 3.9 Kontakt-Lookup (`src/niles/actions/contacts.py`)

```python
def normalize_phone(phone: str) -> str        # +43/00/0 -> 43...
class ContactsAction:
    async def find_by_name(self, name: str) -> dict | None
```

Suche mit Prioritaet: exakt > prefix > partial > first/last name.
Telefon-Normalisierung: Oesterreich-spezifisch (fuehrende 0 -> 43).

### 3.10 CardDAV Sync (`src/niles/sync/carddav.py`)

```python
class CardDAVSync:
    async def initialize(self) -> None       # CREATE TABLE contacts_carddav
    async def sync_contacts(self) -> int     # Full sync, returns count
```

PROPFIND fuer vCard-URLs, vCard-Parsing (TEL, EMAIL, FN, N), UPSERT via UID.
APScheduler fuer taeglichen Sync (03:00). Feature Flag: `FEATURE_CARDDAV_SYNC`.

---

## 4. Security

### 4.1 Netzwerk

- **HTTPS via Caddy:** Alle externen Zugriffe ueber self-signed TLS-Zertifikate (`tls internal`)
- **Keine exponierten Ports:** PostgreSQL, Niles Core, Evolution API und n8n sind nur via Docker-Netzwerk erreichbar
- **Security Headers:** `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`, Server-Header entfernt

### 4.2 Authentifizierung

- **API Key:** `/chat` erfordert `X-API-Key` Header (hmac.compare_digest, max 256 Zeichen)
- **Webhook Token:** `/webhook/whatsapp` erfordert `?token=` Query-Parameter
- **Auto-generierter Key:** `NILES_API_KEY` wird per `secrets.token_urlsafe(32)` generiert wenn nicht gesetzt
- **Key wird nicht geloggt:** Nur Hinweis auf `docker exec niles_core printenv NILES_API_KEY`

### 4.3 Rate Limiting

- In-Memory Rate Limiter: 60 Requests/Minute pro Client-IP
- `/health` ist exempt
- Memory Safeguard: Max 10.000 IPs tracked, aelteste werden evicted
- HTTP 429 bei Ueberschreitung

### 4.4 Docker

- Niles Core laeuft als Non-Root User (UID/GID 1000)
- PostgreSQL-Port nicht exponiert

### 4.5 Access Logs

- Caddy schreibt JSON-formatierte Access Logs pro Service
- Log-Rotation: 10 MB pro Datei, 3 Dateien behalten
- Dateien: `access-niles.log`, `access-evolution.log`, `access-n8n.log`

---

## 5. Dependencies

```toml
fastapi>=0.129.0          # Web Framework
uvicorn[standard]>=0.41.0 # ASGI Server
httpx>=0.28.1             # Async HTTP Client
asyncpg>=0.31.0           # PostgreSQL
openai>=2.21.0            # LLM Client (OpenAI-kompatibel)
mcp>=1.26.0               # MCP SDK (vorbereitet)
pydantic-settings>=2.13.0 # Config Management
pyyaml>=6.0.3             # YAML Parsing
apscheduler>=3.11.2       # Scheduling (CardDAV Sync)
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
RUN uv pip install --system .
COPY config/ ./config/
RUN groupadd --gid 1000 niles && \
    useradd --uid 1000 --gid niles --no-create-home niles && \
    chown -R niles:niles /app
USER niles
ENV PYTHONPATH=/app/src
CMD ["uvicorn", "niles.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 6.2 Docker Compose Services

| Container | Image | Exponierter Port | Zweck |
|-----------|-------|-----------------|-------|
| `niles_caddy` | `caddy:2-alpine` | 443, 8443, 5678 | HTTPS Reverse Proxy |
| `niles_core` | Build (Dockerfile.niles) | -- (via Caddy) | Python Backend |
| `niles_evolution_postgres` | `postgres:15-alpine` | -- | PostgreSQL |
| `niles_evolution_api` | `evoapicloud/evolution-api:v2.3.7` | -- (via Caddy) | WhatsApp Gateway |
| `niles_n8n` | `n8nio/n8n:latest` | -- (via Caddy) | Legacy Workflows |

### 6.3 Volumes

| Volume | Zweck |
|--------|-------|
| `evolution_postgres` | PostgreSQL-Daten |
| `caddy_data` | TLS-Zertifikate |
| `caddy_config` | Caddy-Konfiguration |
| `~/.evolution/instances` | WhatsApp-Sessions |
| `~/.n8n` | n8n-Daten |

---

## 7. Implementierungsstatus

| Stage | Branch | PR | Status | Beschreibung |
|-------|--------|----|--------|-------------|
| 1 | `stage/1-scaffold` | #1 | Abgeschlossen | FastAPI, Docker, pytest, /health |
| 2 | `stage/2-whatsapp-loop` | #4 | Abgeschlossen | WhatsApp empfangen, LLM, antworten |
| 3 | `stage/3-memory` | #6 | Abgeschlossen | Key-Value Memory, Chat-History, Feature Flags |
| 4 | `stage/4-carddav-sync` | #8 | Abgeschlossen | CardDAV Kontakt-Sync (ersetzt n8n) |
| 5 | `stage/5-security-hardening` | #9, #10 | Abgeschlossen | Auth, Rate Limiting, HTTPS, Security Headers |
| 6 | -- | -- | Geplant | MCP Integration |
| 7 | -- | -- | Geplant | Email & Kalender |
| 8 | -- | -- | Geplant | n8n Abloesung |

### Roadmap (Stage 6-8)

**Stage 6 -- MCP Integration:**
- `src/niles/mcp/client.py` -- MCPManager
- MCP-Server als Subprocesses starten
- Tools dynamisch in Agent registrieren
- `config/mcp_servers.yaml` befuellen

**Stage 7 -- Email & Kalender:**
- `src/niles/sources/email.py` -- IMAP Poller (alle 5 min)
- `src/niles/sources/calendar.py` -- CalDAV Poller (alle 15 min)
- Neue Agent-Tools: `create_event`, `draft_email`

**Stage 8 -- n8n Abloesung:**
- Alle verbleibenden n8n-Workflows in Niles Core migrieren
- n8n-Service und Caddy-Route entfernen
- Port 5678 freigeben

---

## 8. Hinweise

### Docker Networking

Alle Container im `niles_network`. Container-Namen als Hostnamen:
- `evolution_postgres` (PostgreSQL)
- `evolution_api` (Evolution API)
- `niles_core` (Niles, auch fuer Webhooks)
- `host.docker.internal:1234` (LM Studio auf dem Host)

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
Optional: `NILES_API_KEY`, `CARDDAV_USER`, `CARDDAV_PASSWORD`, `FEATURE_CARDDAV_SYNC`, `LOG_LEVEL`, `LLM_BASE_URL`, `LLM_MODEL`.

Siehe `.env.example` fuer vollstaendige Dokumentation.

---

## 9. Weitere Dokumentation

- [Architecture](Architecture.md) -- Detaillierte Systemarchitektur
- [API Reference](API.md) -- Endpoints, Payloads, Beispiele
- [Development Guide](Development.md) -- Setup, Testing, Konventionen
