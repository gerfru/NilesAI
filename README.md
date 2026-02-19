# Niles AI Core

Lokaler AI-Butler auf Mac Mini M4. Empfaengt Events aus verschiedenen Quellen (WhatsApp, Web-UI, API), verarbeitet sie mit einem lokalen LLM und fuehrt Aktionen aus.

## Status

| Stage | Status | Beschreibung |
|-------|--------|-------------|
| 1 | Abgeschlossen | FastAPI Scaffold, Docker, pytest, /health |
| 2 | Abgeschlossen | WhatsApp empfangen, LLM-Verarbeitung, antworten |
| 3 | Abgeschlossen | Key-Value Memory, Konversations-Historie |
| 4 | Abgeschlossen | CardDAV Kontakt-Sync |
| 5 | Abgeschlossen | Security Hardening (Auth, Rate Limiting, HTTPS) |
| 6 | Abgeschlossen | MCP Integration |
| 7 | Abgeschlossen | CalDAV Kalender-Sync |
| 8 | Geplant | Email als Event-Quelle |
| 9 | Abgeschlossen | Web GUI (Chat, Settings, htmx) |
| 10 | In Arbeit | Google OAuth, Multi-User, GUI v2 |

## Architektur

```
Browser / curl / WhatsApp
    |
    v  HTTPS (Caddy, self-signed)
+--------------------------------------------------+
|  Niles Core (FastAPI :8000)                      |
|                                                  |
|  /ui/*  ---- sources/web.py (htmx + Jinja2)     |
|                 |  Google OAuth / API-Key Auth   |
|                 |  Signed Session Cookies         |
|                 v                                |
|  /chat  ---> agent/core.py (NilesAgent) -------> LM Studio :1234
|                 |  Tool-Call Loop (max 5)        |
|                 |                                |
|                 +-- memory/store.py     --------> PostgreSQL :5432
|                 +-- memory/history.py  --------> PostgreSQL :5432
|                 +-- actions/contacts.py --------> PostgreSQL :5432
|                 +-- actions/whatsapp.py --------> Evolution API :8080
|                 +-- actions/calendar.py --------> PostgreSQL :5432
|                                                  |
|  /webhook/whatsapp --- sources/whatsapp.py       |
+--------------------------------------------------+
```

## Projektstruktur

```
Niles/
├── src/niles/                  # Python Backend
│   ├── main.py                 # FastAPI + Lifespan + Middleware
│   ├── config.py               # Pydantic Settings
│   ├── user_store.py           # User-Verwaltung (Google OAuth)
│   ├── settings_store.py       # Runtime Settings (PostgreSQL)
│   ├── agent/                  # LLM Agent, Tool-Call-Pipeline
│   ├── memory/                 # Key-Value Store, Chat-History
│   ├── actions/                # WhatsApp, Kontakte, Kalender
│   ├── sources/                # Webhook-Handler, Web-UI
│   ├── sync/                   # CardDAV, CalDAV Sync
│   ├── mcp/                    # MCP Client
│   ├── templates/              # Jinja2 HTML Templates
│   └── static/                 # CSS, JavaScript
├── tests/                      # pytest Tests
├── config/                     # soul.md (Agent-Persoenlichkeit)
├── docker/                     # Dockerfile, docker-compose.yml, Caddyfile
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
# Optional: GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET fuer Web-UI Login
```

### 2. Services starten

```bash
./scripts/start.sh
```

### 3. Status pruefen

```bash
./scripts/status.sh
```

### 4. Web-UI oeffnen

```bash
# Browser oeffnen:
# https://localhost/ui/login
```

Login via Google OAuth (wenn konfiguriert) oder API-Key.

### 5. API testen

```bash
curl -k -X POST https://localhost/chat \
  -H "X-API-Key: <NILES_API_KEY>" \
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
| Web UI | Jinja2 + htmx + Pico CSS | via /ui/* |
| LLM Inference | LM Studio (MLX) | 1234 |
| Datenbank | PostgreSQL 15 | 5432 |
| WhatsApp Gateway | Evolution API v2.3.7 | 8080 |
| Reverse Proxy | Caddy 2 | 443/8443 |
