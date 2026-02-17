# Niles AI Core -- Technische Spezifikation

> **Version:** 2.0
> **Stand:** 2026-02-17
> **Status:** Stage 1-3 implementiert, Stage 4-6 geplant

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

| Komponente | Port | Zweck |
|------------|------|-------|
| LM Studio (Qwen 2.5 Coder 7B MLX) | 1234 | LLM Inference (OpenAI-kompatibel) |
| PostgreSQL | 5432 | Datenbank (evolution_db) |
| Evolution API v2.3.7 | 8080 | WhatsApp Gateway |
| Niles Core (FastAPI) | 8000 | Python Backend |
| n8n | 5678 | Legacy Workflows (wird schrittweise ersetzt) |

**Datenbank:** `evolution_db`, User `evolution`, Passwort via `EVOLUTION_POSTGRES_PASSWORD`.

---

## 2. Architektur

### 2.1 Systemuebersicht

```
Event Sources                Niles Core (FastAPI :8000)              External
                         ┌────────────────────────────────┐
WhatsApp ─── Webhook ──> │  sources/whatsapp.py           │
                         │         │                      │
                         │         v                      │
                         │  agent/core.py (NilesAgent)    │──> LM Studio :1234
                         │    │  Tool-Call Loop (max 5)   │
                         │    │                           │
                         │    ├─ memory/store.py          │──> PostgreSQL :5432
                         │    ├─ memory/history.py        │──> PostgreSQL :5432
                         │    ├─ actions/contacts.py      │──> PostgreSQL :5432
                         │    └─ actions/whatsapp.py      │──> Evolution API :8080
                         │                                │
                         │  GET  /health                  │
                         │  POST /chat                    │
                         │  POST /webhook/whatsapp        │
                         └────────────────────────────────┘
```

### 2.2 Ordnerstruktur

```
Niles/
├── src/
│   ├── niles/                      # Python Backend
│   │   ├── __init__.py
│   │   ├── main.py                 # FastAPI + Lifespan
│   │   ├── config.py               # Pydantic Settings
│   │   ├── agent/
│   │   │   ├── core.py             # NilesAgent, Tool-Definitionen
│   │   │   └── prompts.py          # System Prompt laden/bauen
│   │   ├── memory/
│   │   │   ├── store.py            # Key-Value Memory (PostgreSQL)
│   │   │   └── history.py          # Konversations-Historie
│   │   ├── actions/
│   │   │   ├── whatsapp.py         # WhatsApp senden (Evolution API)
│   │   │   └── contacts.py         # Kontakt-Lookup + normalize_phone
│   │   └── sources/
│   │       └── whatsapp.py         # Webhook-Handler
│   └── frontend/                   # Platzhalter
├── tests/
│   ├── conftest.py
│   ├── test_config.py
│   ├── test_contacts.py
│   ├── test_health.py
│   └── test_memory.py
├── config/
│   ├── soul.md                     # Agent-Persoenlichkeit
│   └── mcp_servers.yaml            # MCP-Konfiguration (leer)
├── docker/
│   ├── docker-compose.yml
│   └── Dockerfile.niles
├── scripts/
│   ├── dev.sh                      # Lokaler Dev-Server
│   ├── test.sh                     # pytest Runner
│   ├── start.sh                    # Docker starten
│   ├── stop.sh                     # Docker stoppen
│   └── status.sh                   # Service-Status pruefen
├── docs/
├── pyproject.toml
└── .env
```

---

## 3. Komponenten

### 3.1 FastAPI Main (`src/niles/main.py`)

Einstiegspunkt. Verwaltet den Application Lifecycle via `lifespan()`:

1. Settings laden (ValidationError bei fehlenden Secrets -> `sys.exit(1)`)
2. Logging konfigurieren (Level via `LOG_LEVEL` Env-Variable)
3. asyncpg Connection Pool erstellen
4. MemoryStore + ConversationHistory initialisieren (CREATE TABLE IF NOT EXISTS)
5. Actions und Agent instanziieren
6. Alles auf `app.state` speichern

Endpoints: siehe `docs/API.md`.

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
    carddav_url: str = "https://dav.example.com/carddav/32"
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

- Filtert auf `event == "messages.upsert"`
- Ignoriert eigene Nachrichten (`fromMe: true`)
- Extrahiert Text aus `message.conversation` oder `extendedTextMessage.text`
- Gibt immer HTTP 200 zurueck (verhindert Retry-Spam)
- Fehler werden geloggt, nicht propagiert

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

---

## 4. Dependencies

```toml
fastapi>=0.129.0          # Web Framework
uvicorn[standard]>=0.41.0 # ASGI Server
httpx>=0.28.1             # Async HTTP Client
asyncpg>=0.31.0           # PostgreSQL
openai>=2.21.0            # LLM Client (OpenAI-kompatibel)
mcp>=1.26.0               # MCP SDK (vorbereitet)
pydantic-settings>=2.13.0 # Config Management
pyyaml>=6.0.3             # YAML Parsing
apscheduler>=3.11.2       # Scheduling (vorbereitet)
```

Dev: `pytest>=9.0.0`, `pytest-asyncio>=1.3.0`, `httpx` (TestClient).

---

## 5. Docker

### 5.1 Dockerfile (`docker/Dockerfile.niles`)

```dockerfile
FROM python:3.12-slim
WORKDIR /app
RUN pip install uv
COPY pyproject.toml .
COPY src/ ./src/
RUN uv pip install --system .
COPY config/ ./config/
ENV PYTHONPATH=/app/src
CMD ["uvicorn", "niles.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 5.2 Docker Compose (niles_core Service)

```yaml
niles_core:
  build:
    context: ..
    dockerfile: docker/Dockerfile.niles
  ports: ["8000:8000"]
  environment:
    - PYTHONPATH=/app/src
    - EVOLUTION_API_KEY=${EVOLUTION_API_KEY}
    - EVOLUTION_POSTGRES_PASSWORD=${EVOLUTION_POSTGRES_PASSWORD}
    - CARDDAV_USER=${CARDDAV_USER:-}
    - CARDDAV_PASSWORD=${CARDDAV_PASSWORD:-}
  volumes:
    - ../src:/app/src          # Live-Reload
    - ../config:/app/config:ro
  command: uvicorn niles.main:app --host 0.0.0.0 --port 8000 --reload
  depends_on: [evolution_postgres, evolution_api]
```

---

## 6. Implementierungsstatus

| Stage | Branch | Status | Beschreibung |
|-------|--------|--------|-------------|
| 1 | `stage/1-scaffold` | Abgeschlossen | FastAPI, Docker, pytest, /health |
| 2 | `stage/2-whatsapp-loop` | Abgeschlossen | WhatsApp empfangen, LLM, antworten |
| 3 | `stage/3-memory` | Abgeschlossen | Key-Value Memory, Chat-History |
| 4 | `stage/4-carddav-sync` | Geplant | CardDAV Kontakt-Sync (ersetzt n8n) |
| 5 | `stage/5-mcp-integration` | Geplant | MCP Client, externe Tools |
| 6 | `stage/6-email-calendar` | Geplant | IMAP + CalDAV als Event-Quellen |

### Roadmap (Stage 4-6)

**Stage 4 -- CardDAV Sync:**
- `src/niles/sync/carddav.py` -- PROPFIND, vCard-Parsing, UPSERT
- APScheduler fuer taeglichen Sync (03:00)
- Ersetzt n8n Workflow `sync-contacts.json`

**Stage 5 -- MCP Integration:**
- `src/niles/mcp/client.py` -- MCPManager
- MCP-Server als Subprocesses starten
- Tools dynamisch in Agent registrieren

**Stage 6 -- Email & Kalender:**
- `src/niles/sources/email.py` -- IMAP Poller (alle 5 min)
- `src/niles/sources/calendar.py` -- CalDAV Poller (alle 15 min)

---

## 7. Hinweise

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
    "url": "http://niles_core:8000/webhook/whatsapp",
    "events": ["MESSAGES_UPSERT"]
  }
}
```

### Environment-Variablen

Pflicht: `EVOLUTION_POSTGRES_PASSWORD`, `EVOLUTION_API_KEY`.
Optional: `CARDDAV_USER`, `CARDDAV_PASSWORD`, `LOG_LEVEL`, `LLM_BASE_URL`, `LLM_MODEL`.

---

## 8. Weitere Dokumentation

- [Architecture](Architecture.md) -- Detaillierte Systemarchitektur
- [API Reference](API.md) -- Endpoints, Payloads, Beispiele
- [Development Guide](Development.md) -- Setup, Testing, Konventionen
