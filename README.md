# Niles AI Core

Lokaler AI-Butler auf Mac Mini M4. Empfaengt Events aus verschiedenen Quellen (WhatsApp, Email, Kalender), verarbeitet sie mit einem lokalen LLM und fuehrt Aktionen aus.

## Status

Stage 1-3 implementiert. Stage 4-6 geplant.

| Stage | Status | Beschreibung |
|-------|--------|-------------|
| 1 | Abgeschlossen | FastAPI Scaffold, Docker, pytest, /health |
| 2 | Abgeschlossen | WhatsApp empfangen, LLM-Verarbeitung, antworten |
| 3 | Abgeschlossen | Key-Value Memory, Konversations-Historie |
| 4 | Geplant | CardDAV Kontakt-Sync (ersetzt n8n) |
| 5 | Geplant | MCP Client, externe Tools |
| 6 | Geplant | IMAP + CalDAV als Event-Quellen |

## Architektur

```
Event Sources                Niles Core (FastAPI :8000)              External
                         +--------------------------------+
WhatsApp --- Webhook --> |  sources/whatsapp.py           |
                         |         |                      |
                         |         v                      |
POST /chat  ----------> |  agent/core.py (NilesAgent)    |--> LM Studio :1234
                         |    |  Tool-Call Loop (max 5)   |
                         |    |                           |
                         |    +- memory/store.py          |--> PostgreSQL :5432
                         |    +- memory/history.py        |--> PostgreSQL :5432
                         |    +- actions/contacts.py      |--> PostgreSQL :5432
                         |    +- actions/whatsapp.py      |--> Evolution API :8080
                         +--------------------------------+
```

## Projektstruktur

```
Niles/
├── src/niles/                  # Python Backend
│   ├── main.py                 # FastAPI + Lifespan
│   ├── config.py               # Pydantic Settings
│   ├── agent/                  # LLM Agent, Tool-Call-Pipeline
│   ├── memory/                 # Key-Value Store, Chat-History
│   ├── actions/                # WhatsApp senden, Kontakt-Lookup
│   └── sources/                # Webhook-Handler
├── tests/                      # pytest Tests
├── config/                     # soul.md (Agent-Persoenlichkeit)
├── docker/                     # Dockerfile, docker-compose.yml
├── scripts/                    # dev.sh, test.sh, start.sh, stop.sh, status.sh
├── docs/                       # Technische Dokumentation
├── pyproject.toml
└── .env                        # Secrets (nicht in Git)
```

## Quick Start

### Voraussetzungen

- Python >= 3.11
- Docker Desktop
- LM Studio (mit geladenem MLX-Modell auf Port 1234)

### 1. Environment konfigurieren

```bash
cp .env.example .env
# Pflichtfelder setzen: EVOLUTION_POSTGRES_PASSWORD, EVOLUTION_API_KEY
```

### 2. Services starten

```bash
./scripts/start.sh
```

### 3. Status pruefen

```bash
./scripts/status.sh
```

### 4. Testen

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Hallo Niles!"}'
```

## Dokumentation

- [Technische Spezifikation](docs/Niles-Core-Spec.md) -- Komponentenbeschreibung und Roadmap
- [Architektur](docs/Architecture.md) -- Systemuebersicht, Module, Datenfluss, DB-Schema
- [API Reference](docs/API.md) -- Endpoints, Payloads, Agent-Tools
- [Development Guide](docs/Development.md) -- Setup, Testing, Konventionen

## Stack

| Komponente | Technologie | Port |
|------------|-------------|------|
| Niles Core | FastAPI (Python) | 8000 |
| LLM Inference | LM Studio (MLX) | 1234 |
| Datenbank | PostgreSQL 15 | 5432 |
| WhatsApp Gateway | Evolution API v2.3.7 | 8080 |
| Legacy Workflows | n8n | 5678 |
