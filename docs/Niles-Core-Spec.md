# Niles AI Core – Technische Spezifikation

> **Dokument für:** Claude Code (Entwickler)
> **Erstellt von:** System-Architekt & Produkt-Manager
> **Version:** 1.0
> **Datum:** 2026-02-17

---

## 1. Projektübersicht

### 1.1 Vision

Niles ist ein lokaler, privater AI-Butler der auf einem Mac Mini M4 läuft. Er empfängt Events aus verschiedenen Quellen (WhatsApp, Email, Kalender), verarbeitet sie intelligent mit einem lokalen LLM, und führt Aktionen aus.

### 1.2 Kernprinzipien

- **KISS** – Keep It Simple, Stupid
- **100% Lokal** – Keine Cloud-Abhängigkeiten für Core-Funktionen
- **Privacy First** – Alle Daten bleiben auf dem eigenen Server
- **Erweiterbar** – MCP-Protokoll für Community-Module

### 1.3 Bestehende Infrastruktur

Diese Komponenten existieren bereits und MÜSSEN wiederverwendet werden:

| Komponente | Port | Status |
|------------|------|--------|
| LM Studio (Qwen 2.5 Coder 7B MLX) | 1234 | ✅ Läuft |
| PostgreSQL | 5432 | ✅ Läuft |
| Evolution API (WhatsApp) | 8080 | ✅ Läuft |
| n8n (wird ersetzt) | 5678 | ⚠️ Legacy |

**PostgreSQL Datenbank:** `evolution_db`
**PostgreSQL User:** `evolution`
**PostgreSQL Password:** Via `$EVOLUTION_POSTGRES_PASSWORD` Environment Variable

**Bestehende Tabelle `contacts`:**
```sql
CREATE TABLE contacts (
    id SERIAL PRIMARY KEY,
    full_name TEXT NOT NULL,
    first_name TEXT,
    last_name TEXT,
    phone_primary TEXT,
    phone_mobile TEXT,
    phone_work TEXT,
    email TEXT,
    cardav_uid TEXT UNIQUE,
    cardav_url TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## 2. Architektur

### 2.1 High-Level Architektur

```
┌─────────────────────────────────────────────────────────────┐
│                      Event Sources                          │
├─────────────────────────────────────────────────────────────┤
│  WhatsApp ──────▶ Webhook POST /webhook/whatsapp            │
│  Email ─────────▶ IMAP Poll (alle 5 min)                    │
│  Calendar ──────▶ CalDAV Poll (alle 15 min)                 │
│  GUI (später) ──▶ REST/WebSocket                            │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│                    Niles Core (FastAPI)                     │
│                       Port 8000                             │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                    Agent Core                        │   │
│  │  1. Event empfangen                                  │   │
│  │  2. Memory laden (Kontext)                          │   │
│  │  3. MCP Tools sammeln                               │   │
│  │  4. LLM: Intent erkennen + Action bestimmen         │   │
│  │  5. Action(s) ausführen                             │   │
│  │  6. Memory updaten                                  │   │
│  │  7. Response senden                                 │   │
│  └─────────────────────────────────────────────────────┘   │
│                           │                                 │
│         ┌─────────────────┼─────────────────┐              │
│         ▼                 ▼                 ▼              │
│  ┌────────────┐   ┌─────────────┐   ┌─────────────┐       │
│  │ MCP Client │   │  Memory     │   │  Actions    │       │
│  │            │   │ (PostgreSQL)│   │ (eigene)    │       │
│  └────────────┘   └─────────────┘   └─────────────┘       │
│         │                                   │              │
└─────────┼───────────────────────────────────┼──────────────┘
          │                                   │
          ▼                                   ▼
┌─────────────────────┐             ┌─────────────────────┐
│    MCP Server       │             │   External APIs     │
│  (Community/Eigene) │             │  • Evolution API    │
│  • Home Assistant   │             │  • CalDAV           │
│  • Filesystem       │             │  • IMAP             │
│  • etc.             │             └─────────────────────┘
└─────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│                      LM Studio                              │
│              http://localhost:1234/v1                       │
│                  (OpenAI-kompatible API)                    │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 Ordnerstruktur

Erstelle diese Struktur im bestehenden `Niles/` Repository:

```
Niles/
├── docker/
│   └── docker-compose.yml      # AKTUALISIEREN: niles-core Service hinzufügen
│
├── niles/                       # NEU: Python Core
│   ├── __init__.py
│   ├── main.py                 # FastAPI Einstiegspunkt
│   ├── config.py               # Pydantic Settings
│   │
│   ├── mcp/
│   │   ├── __init__.py
│   │   └── client.py           # MCP Client Manager
│   │
│   ├── sources/
│   │   ├── __init__.py
│   │   ├── whatsapp.py         # Evolution API Webhook Handler
│   │   ├── email.py            # IMAP Poller (Phase 2)
│   │   └── calendar.py         # CalDAV Poller (Phase 2)
│   │
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── core.py             # Haupt-Agent-Logik
│   │   ├── memory.py           # PostgreSQL Memory Store
│   │   └── prompts.py          # System Prompts
│   │
│   ├── actions/
│   │   ├── __init__.py
│   │   ├── whatsapp.py         # WhatsApp senden via Evolution API
│   │   └── contacts.py         # Kontakt-Lookup
│   │
│   └── sync/
│       ├── __init__.py
│       └── carddav.py          # CardDAV Kontakt-Sync
│
├── config/
│   ├── mcp_servers.yaml        # MCP Server Konfiguration
│   └── soul.md                 # Agent Persönlichkeit & System Prompt
│
├── pyproject.toml              # Python Dependencies (uv/pip)
├── .env                        # EXISTIERT BEREITS – nicht überschreiben!
├── .env.example                # AKTUALISIEREN mit neuen Variablen
│
├── workflows/                   # Legacy n8n – NICHT LÖSCHEN (vorerst)
├── scripts/                     # EXISTIERT – ggf. erweitern
└── docs/                        # EXISTIERT – ggf. erweitern
```

---

## 3. Komponenten-Spezifikationen

### 3.1 FastAPI Main (`niles/main.py`)

```python
"""
Niles AI Core – FastAPI Einstiegspunkt

Verantwortlich für:
- HTTP Server starten
- Webhook Endpoints bereitstellen
- Background Tasks (Scheduler) starten
- Graceful Shutdown
"""

from fastapi import FastAPI
from contextlib import asynccontextmanager

# Lifecycle: MCP Server starten, DB Connection, etc.
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await mcp_manager.connect_all()
    await memory.initialize()
    scheduler.start()
    yield
    # Shutdown
    await mcp_manager.close()
    scheduler.shutdown()

app = FastAPI(title="Niles AI Core", lifespan=lifespan)

# Endpoints:
# POST /webhook/whatsapp – Evolution API Webhook
# POST /chat – Direkte Chat-API (für GUI später)
# GET /health – Health Check
```

**Port:** 8000
**Host:** 0.0.0.0 (für Docker-Netzwerk)

### 3.2 Config (`niles/config.py`)

Verwende Pydantic Settings für typsichere Konfiguration:

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # LM Studio
    llm_base_url: str = "http://host.docker.internal:1234/v1"
    llm_model: str = "qwen2.5-coder-7b-instruct-mlx"
    
    # PostgreSQL (bestehende Verbindung)
    postgres_host: str = "evolution_postgres"
    postgres_port: int = 5432
    postgres_db: str = "evolution_db"
    postgres_user: str = "evolution"
    postgres_password: str  # Via EVOLUTION_POSTGRES_PASSWORD
    
    # Evolution API (WhatsApp)
    evolution_api_url: str = "http://evolution_api:8080"
    evolution_api_key: str  # Via EVOLUTION_API_KEY
    evolution_instance: str = "niles-whatsapp"
    
    # CardDAV (mailbox.org)
    carddav_url: str = "https://dav.mailbox.org/carddav/32"
    carddav_user: str  # Via CARDDAV_USER
    carddav_password: str  # Via CARDDAV_PASSWORD
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
```

### 3.3 MCP Client (`niles/mcp/client.py`)

```python
"""
MCP Client Manager

Verwaltet Verbindungen zu mehreren MCP Servern.
Startet Server als Subprocesses und kommuniziert via stdio.

Referenz: https://github.com/modelcontextprotocol/python-sdk
"""

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from contextlib import AsyncExitStack
import yaml

class MCPManager:
    """
    Lifecycle:
    1. connect_all() – Alle Server aus config starten
    2. list_all_tools() – Tools für LLM sammeln
    3. call_tool(server, name, args) – Tool ausführen
    4. close() – Cleanup
    """
    
    def __init__(self, config_path: str = "config/mcp_servers.yaml"):
        self.config_path = config_path
        self.sessions: dict[str, ClientSession] = {}
        self.exit_stack = AsyncExitStack()
    
    async def connect_all(self) -> None:
        """Startet alle konfigurierten MCP Server"""
        pass  # Implementieren
    
    async def list_all_tools(self) -> list[dict]:
        """
        Sammelt alle Tools von allen Servern.
        Rückgabe-Format muss kompatibel mit OpenAI Tool-Format sein.
        """
        pass  # Implementieren
    
    async def call_tool(self, server: str, tool_name: str, arguments: dict) -> any:
        """Ruft ein Tool auf einem spezifischen Server auf"""
        pass  # Implementieren
    
    async def close(self) -> None:
        """Cleanup aller Connections"""
        await self.exit_stack.aclose()
```

**MCP Server Config (`config/mcp_servers.yaml`):**

```yaml
# Phase 1: Keine MCP Server (erstmal eigene Actions)
# Phase 2: Home Assistant, Filesystem, etc.

servers: {}

# Beispiel für später:
# servers:
#   home-assistant:
#     command: npx
#     args: ["-y", "@anthropic/mcp-server-home-assistant"]
#     env:
#       HA_URL: "${HA_URL}"
#       HA_TOKEN: "${HA_TOKEN}"
```

### 3.4 Memory Store (`niles/agent/memory.py`)

```python
"""
Persistentes Memory für den Agent.

Verwendet PostgreSQL (bestehende Instanz).
Neue Tabelle: `memory`
"""

import asyncpg
from datetime import datetime

# SQL für Tabellen-Erstellung
INIT_SQL = """
CREATE TABLE IF NOT EXISTS memory (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_memory_updated ON memory(updated_at);
"""

class MemoryStore:
    """
    Simple Key-Value Store mit JSON-Werten.
    
    Beispiel-Keys:
    - "user.preferences" → {"wake_time": "07:00", "language": "de"}
    - "context.current_project" → {"name": "Niles", "status": "active"}
    - "contacts.important" → ["chef@firma.at", "partner@email.com"]
    """
    
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
    
    async def get(self, key: str) -> dict | None:
        """Wert abrufen"""
        pass  # Implementieren
    
    async def set(self, key: str, value: dict) -> None:
        """Wert setzen (UPSERT)"""
        pass  # Implementieren
    
    async def delete(self, key: str) -> None:
        """Wert löschen"""
        pass  # Implementieren
    
    async def search(self, key_prefix: str) -> list[tuple[str, dict]]:
        """Alle Keys mit Prefix suchen"""
        pass  # Implementieren
```

### 3.5 Agent Core (`niles/agent/core.py`)

```python
"""
Haupt-Agent-Logik.

Verarbeitet Events und entscheidet über Aktionen.
"""

from openai import AsyncOpenAI
from .memory import MemoryStore
from ..mcp.client import MCPManager

class NilesAgent:
    """
    Event-Processing Pipeline:
    
    1. Event empfangen (WhatsApp, Email, etc.)
    2. Relevantes Memory laden
    3. Verfügbare Tools sammeln (MCP + eigene Actions)
    4. LLM aufrufen mit Kontext + Tools
    5. Tool Calls ausführen
    6. Memory updaten
    7. Response generieren
    """
    
    def __init__(
        self,
        llm_client: AsyncOpenAI,
        memory: MemoryStore,
        mcp: MCPManager,
        config: Settings
    ):
        self.llm = llm_client
        self.memory = memory
        self.mcp = mcp
        self.config = config
    
    async def process_event(self, event: dict) -> str:
        """
        Haupteingang für alle Events.
        
        Event-Format:
        {
            "type": "whatsapp" | "email" | "calendar" | "chat",
            "from": str,  # Absender (Telefon, Email, etc.)
            "content": str,  # Nachrichteninhalt
            "metadata": dict  # Zusätzliche Daten
        }
        
        Rückgabe: Response-Text für den User
        """
        pass  # Implementieren
    
    async def _build_context(self, event: dict) -> str:
        """Baut Kontext aus Memory für das LLM"""
        pass  # Implementieren
    
    async def _get_tools(self) -> list[dict]:
        """Sammelt alle verfügbaren Tools (MCP + eigene)"""
        pass  # Implementieren
    
    async def _execute_tool_call(self, tool_call: dict) -> any:
        """Führt einen Tool-Call aus"""
        pass  # Implementieren
```

### 3.6 WhatsApp Source (`niles/sources/whatsapp.py`)

```python
"""
WhatsApp Event Handler.

Empfängt Webhooks von Evolution API und wandelt sie in Events um.
"""

from fastapi import APIRouter, Request

router = APIRouter(prefix="/webhook", tags=["webhooks"])

@router.post("/whatsapp")
async def whatsapp_webhook(request: Request):
    """
    Evolution API Webhook Handler.
    
    Evolution API sendet verschiedene Event-Typen:
    - MESSAGES_UPSERT: Neue Nachricht empfangen
    - MESSAGES_UPDATE: Nachricht aktualisiert (gelesen, etc.)
    - CONNECTION_UPDATE: Verbindungsstatus
    
    Wir interessieren uns primär für MESSAGES_UPSERT.
    
    Payload-Struktur (MESSAGES_UPSERT):
    {
        "event": "messages.upsert",
        "instance": "niles-whatsapp",
        "data": {
            "key": {
                "remoteJid": "4366012345678@s.whatsapp.net",
                "fromMe": false,
                "id": "..."
            },
            "message": {
                "conversation": "Nachrichtentext"
            }
        }
    }
    """
    pass  # Implementieren
```

### 3.7 WhatsApp Action (`niles/actions/whatsapp.py`)

```python
"""
WhatsApp Senden via Evolution API.
"""

import httpx
from ..config import Settings

class WhatsAppAction:
    """
    Sendet Nachrichten via Evolution API.
    
    API Endpoint: POST /message/sendText/{instance}
    """
    
    def __init__(self, config: Settings):
        self.base_url = config.evolution_api_url
        self.api_key = config.evolution_api_key
        self.instance = config.evolution_instance
    
    async def send_message(self, to: str, text: str) -> dict:
        """
        Sendet eine WhatsApp-Nachricht.
        
        Args:
            to: Telefonnummer (Format: 4366012345678) oder Gruppen-JID
            text: Nachrichtentext
        
        Returns:
            API Response
        """
        pass  # Implementieren
    
    async def send_to_contact(self, contact_name: str, text: str) -> dict:
        """
        Sendet an einen Kontakt (Name wird in Nummer aufgelöst).
        
        Verwendet die bestehende `contacts`-Tabelle.
        """
        pass  # Implementieren
```

### 3.8 Kontakt-Lookup (`niles/actions/contacts.py`)

```python
"""
Kontakt-Suche in PostgreSQL.

Verwendet die bestehende `contacts`-Tabelle.
"""

import asyncpg

class ContactsAction:
    """
    Sucht Kontakte nach Name und gibt Telefonnummer zurück.
    """
    
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
    
    async def find_by_name(self, name: str) -> dict | None:
        """
        Sucht Kontakt nach Name (case-insensitive, partial match).
        
        Priorisierung:
        1. Exakter Match auf full_name
        2. Prefix-Match auf full_name
        3. Partial Match auf full_name
        4. Match auf first_name oder last_name
        
        Returns:
            {
                "full_name": "Max Mustermann",
                "phone": "4366012345678",  # Normalisiert
                "email": "max@example.com"
            }
            oder None wenn nicht gefunden
        """
        pass  # Implementieren
    
    async def normalize_phone(self, phone: str) -> str:
        """
        Normalisiert Telefonnummer für WhatsApp.
        
        - Entfernt +, Leerzeichen, Bindestriche
        - Entfernt führende 00
        - Konvertiert 0... zu 43... (Österreich)
        """
        pass  # Implementieren
```

### 3.9 CardDAV Sync (`niles/sync/carddav.py`)

```python
"""
CardDAV Kontakt-Synchronisation.

Ersetzt den n8n Workflow `sync-contacts.json`.
Synchronisiert Kontakte von mailbox.org nach PostgreSQL.
"""

import httpx
import asyncpg
from xml.etree import ElementTree

class CardDAVSync:
    """
    Sync-Prozess:
    1. PROPFIND auf CardDAV URL → Liste aller vCard URLs
    2. Für jede URL: GET vCard
    3. vCard parsen → Kontakt-Dict
    4. UPSERT in PostgreSQL
    
    Sollte täglich laufen (via Scheduler).
    """
    
    def __init__(self, config: Settings, pool: asyncpg.Pool):
        self.config = config
        self.pool = pool
    
    async def sync_all(self) -> int:
        """
        Führt vollständige Synchronisation durch.
        
        Returns:
            Anzahl synchronisierter Kontakte
        """
        pass  # Implementieren
    
    async def _fetch_vcard_urls(self) -> list[str]:
        """PROPFIND → Liste aller vCard URLs"""
        pass  # Implementieren
    
    async def _fetch_vcard(self, url: str) -> str:
        """GET einzelne vCard"""
        pass  # Implementieren
    
    def _parse_vcard(self, vcard_text: str) -> dict:
        """
        Parst vCard-Text in Kontakt-Dict.
        
        Wichtige Felder:
        - FN: Full Name
        - N: Name (Nachname;Vorname;...)
        - TEL: Telefon (mit TYPE=CELL, TYPE=WORK, etc.)
        - EMAIL: Email
        - UID: Unique ID
        """
        pass  # Implementieren
    
    async def _upsert_contact(self, contact: dict) -> None:
        """UPSERT Kontakt in PostgreSQL"""
        pass  # Implementieren
```

---

## 4. System Prompt (`config/soul.md`)

```markdown
# Niles – Persönlicher AI-Butler

Du bist Niles, ein persönlicher AI-Assistent. Du läufst lokal auf dem Mac Mini deines Besitzers und hast Zugriff auf verschiedene Tools.

## Persönlichkeit

- Freundlich aber effizient
- Antworte auf Deutsch (außer anders gewünscht)
- Halte Antworten kurz und prägnant
- Frage nach wenn etwas unklar ist

## Verfügbare Fähigkeiten

### WhatsApp
- Nachrichten senden an Kontakte oder Telefonnummern
- Nachrichten an Gruppen senden

### Kontakte
- Kontakte nach Name suchen
- Telefonnummern nachschlagen

### Memory (kommt noch)
- Dinge merken die der User dir sagt
- Kontext aus vergangenen Gesprächen nutzen

## Regeln

1. Wenn du eine Aktion ausführst, bestätige kurz was du getan hast
2. Wenn du einen Kontakt nicht findest, frage nach der Telefonnummer
3. Bei Grupennachrichten: Stelle sicher dass du den richtigen Gruppennamen hast
4. Führe NIEMALS Aktionen aus ohne explizite Aufforderung
```

---

## 5. Dependencies (`pyproject.toml`)

```toml
[project]
name = "niles-core"
version = "0.1.0"
description = "Local AI Butler"
requires-python = ">=3.11"

dependencies = [
    # Web Framework
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.32.0",
    
    # Async HTTP Client
    "httpx>=0.28.0",
    
    # Database
    "asyncpg>=0.30.0",
    
    # LLM Client (OpenAI-kompatibel für LM Studio)
    "openai>=1.60.0",
    
    # MCP SDK
    "mcp>=1.26.0",
    
    # Config
    "pydantic-settings>=2.7.0",
    "pyyaml>=6.0",
    
    # Scheduling
    "apscheduler>=3.11.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.24.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

---

## 6. Docker Integration

### 6.1 Dockerfile (`docker/Dockerfile.niles`)

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install uv for fast dependency management
RUN pip install uv

# Copy dependency files
COPY pyproject.toml .

# Install dependencies
RUN uv pip install --system -e .

# Copy application code
COPY niles/ ./niles/
COPY config/ ./config/

# Run
CMD ["uvicorn", "niles.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 6.2 Docker Compose Update (`docker/docker-compose.yml`)

Füge diesen Service hinzu (NICHT die bestehenden Services ändern):

```yaml
  # Niles AI Core (NEU)
  niles_core:
    container_name: niles_core
    build:
      context: ..
      dockerfile: docker/Dockerfile.niles
    restart: unless-stopped
    ports:
      - "8000:8000"
    environment:
      - EVOLUTION_API_KEY=${EVOLUTION_API_KEY}
      - EVOLUTION_POSTGRES_PASSWORD=${EVOLUTION_POSTGRES_PASSWORD}
      - CARDDAV_USER=${CARDDAV_USER}
      - CARDDAV_PASSWORD=${CARDDAV_PASSWORD}
    volumes:
      - ../config:/app/config:ro
    networks:
      - niles_network
    depends_on:
      - evolution_postgres
      - evolution_api
```

---

## 7. Implementierungs-Phasen

### Phase 1: Grundgerüst (JETZT)

- [ ] Ordnerstruktur anlegen
- [ ] `pyproject.toml` erstellen
- [ ] `niles/config.py` implementieren
- [ ] `niles/main.py` mit Health-Endpoint
- [ ] Docker Setup testen

### Phase 2: WhatsApp Loop

- [ ] `niles/sources/whatsapp.py` – Webhook empfangen
- [ ] `niles/actions/whatsapp.py` – Nachricht senden
- [ ] `niles/actions/contacts.py` – Kontakt-Lookup
- [ ] `niles/agent/core.py` – Basis-Agent (ohne Memory)
- [ ] Evolution API Webhook konfigurieren

**Test:** WhatsApp-Nachricht empfangen → Agent verarbeitet → Antwort senden

### Phase 3: Memory

- [ ] `niles/agent/memory.py` – PostgreSQL Memory Store
- [ ] Memory in Agent integrieren
- [ ] System Prompt mit Memory-Kontext

**Test:** "Merke dir dass ich morgen Urlaub habe" → Später: "Habe ich morgen was vor?"

### Phase 4: CardDAV Sync

- [ ] `niles/sync/carddav.py` – Sync-Logik
- [ ] APScheduler für täglichen Sync
- [ ] n8n Workflow `sync-contacts.json` deaktivieren

### Phase 5: MCP Integration

- [ ] `niles/mcp/client.py` vollständig implementieren
- [ ] Erster MCP Server (z.B. Filesystem)
- [ ] Tools in Agent integrieren

### Phase 6: Weitere Sources

- [ ] `niles/sources/email.py` – IMAP Polling
- [ ] `niles/sources/calendar.py` – CalDAV Polling

---

## 8. API Referenzen

### 8.1 LM Studio API

**Base URL:** `http://localhost:1234/v1`

**Chat Completion:**
```bash
POST /chat/completions
{
    "model": "qwen2.5-coder-7b-instruct-mlx",
    "messages": [
        {"role": "system", "content": "..."},
        {"role": "user", "content": "..."}
    ],
    "tools": [...],  # Optional
    "temperature": 0.7
}
```

### 8.2 Evolution API

**Base URL:** `http://evolution_api:8080`
**Auth Header:** `apikey: ${EVOLUTION_API_KEY}`

**Nachricht senden:**
```bash
POST /message/sendText/niles-whatsapp
{
    "number": "4366012345678",
    "text": "Nachricht"
}
```

**Gruppen abrufen:**
```bash
GET /group/fetchAllGroups/niles-whatsapp?getParticipants=false
```

**Webhook setzen:**
```bash
POST /webhook/set/niles-whatsapp
{
    "url": "http://niles_core:8000/webhook/whatsapp",
    "webhook_by_events": true,
    "events": ["MESSAGES_UPSERT"]
}
```

### 8.3 PostgreSQL

**Connection String:**
```
postgresql://evolution:${EVOLUTION_POSTGRES_PASSWORD}@evolution_postgres:5432/evolution_db
```

---

## 9. Wichtige Hinweise

### 9.1 Docker Networking

Alle Container sind im `niles_network`. Verwende Container-Namen als Hostnamen:
- `evolution_postgres` (nicht `localhost`)
- `evolution_api` (nicht `localhost`)
- `niles_core` (für Webhooks von Evolution)

Für LM Studio (läuft auf Host, nicht in Docker):
- `host.docker.internal:1234`

### 9.2 Bestehende `.env` Variablen

Diese existieren bereits – NICHT ändern:
- `EVOLUTION_API_KEY`
- `EVOLUTION_POSTGRES_PASSWORD`

Diese hinzufügen:
- `CARDDAV_USER`
- `CARDDAV_PASSWORD`

### 9.3 Error Handling

- Alle externen Calls (LM Studio, Evolution, PostgreSQL) mit try/except
- Logging mit Python `logging` Modul
- Bei Webhook-Fehlern: HTTP 200 zurückgeben (sonst Retry-Spam von Evolution)

### 9.4 Testing

- Starte mit manuellen Tests via `curl` oder Postman
- Unit Tests später (Phase 2+)
- n8n bleibt als Fallback bis alles funktioniert

---

## 10. Offene Fragen (für später)

- Voice Input/Output: Whisper + TTS?
- GUI: React? Svelte? Native macOS?
- Proaktive Benachrichtigungen: Wie triggern?
- Rate Limiting für LM Studio?

---

**Ende der Spezifikation**

Bei Fragen zur Implementierung: Frag nach!