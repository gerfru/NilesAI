# Niles AI Core -- Architektur

> **Stand:** 2026-02-17

---

## 1. Systemuebersicht

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
                         |                                |
                         |  GET  /health                  |
                         |  POST /chat                    |
                         |  POST /webhook/whatsapp        |
                         +--------------------------------+
```

Alle Komponenten laufen in Docker-Containern im selben Netzwerk (`niles_network`). LM Studio laeuft nativ auf dem Host und ist ueber `host.docker.internal:1234` erreichbar.

---

## 2. Modulstruktur

```
src/niles/
├── main.py              # FastAPI App, Lifespan, Endpoints
├── config.py            # Pydantic Settings
├── agent/
│   ├── core.py          # NilesAgent, Tool-Call-Pipeline
│   └── prompts.py       # System Prompt laden/bauen
├── memory/
│   ├── store.py         # Key-Value Memory (PostgreSQL)
│   └── history.py       # Konversations-Historie (PostgreSQL)
├── actions/
│   ├── whatsapp.py      # WhatsApp senden (Evolution API)
│   └── contacts.py      # Kontakt-Lookup (PostgreSQL)
└── sources/
    └── whatsapp.py      # Webhook-Handler (Evolution API)
```

### agent/

Zentrale Event-Verarbeitung. `NilesAgent` empfaengt Events, baut den LLM-Kontext (System Prompt + Memory + History + User-Nachricht), ruft das LLM auf und fuehrt Tool-Calls aus. `prompts.py` laedt die Agent-Persoenlichkeit aus `config/soul.md` und injiziert Memory-Eintraege in den System Prompt.

### memory/

Persistente Datenhaltung fuer den Agent. `MemoryStore` ist ein Key-Value Store (JSONB) fuer Fakten und Wissen. `ConversationHistory` speichert den Nachrichtenverlauf pro Chat-ID fuer LLM-Kontext.

### actions/

Ausfuehrbare Aktionen, die der Agent ueber Tool-Calls triggern kann. `WhatsAppAction` sendet Nachrichten ueber die Evolution API. `ContactsAction` sucht Kontakte in PostgreSQL.

### sources/

Event-Quellen, die eingehende Nachrichten empfangen und an den Agent weiterleiten. `whatsapp.py` ist ein FastAPI-Router fuer Evolution API Webhooks.

---

## 3. Datenfluss: WhatsApp-Nachricht

Schritt-fuer-Schritt-Verarbeitung einer eingehenden WhatsApp-Nachricht:

```
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

---

## 4. Datenbankschema

Alle Tabellen liegen in der Datenbank `evolution_db` (User `evolution`). Die Tabellen `memory`, `conversations` und `contacts` werden beim Start automatisch erstellt (`CREATE TABLE IF NOT EXISTS`). Die Tabelle `contacts` wird durch den nativen CardDAV-Sync befuellt.

### contacts

```sql
-- Erstellt/befuellt durch nativen CardDAV-Sync
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

---

## 5. Konfiguration

### Settings (`src/niles/config.py`)

Pydantic Settings laedt Werte aus `.env` und Environment-Variablen. `extra = "ignore"` verhindert Fehler bei unbekannten Variablen.

| Feld | Default | Env-Variable | Pflicht |
|------|---------|-------------|---------|
| `log_level` | `"INFO"` | `LOG_LEVEL` | Nein |
| `llm_base_url` | `"http://host.docker.internal:1234/v1"` | `LLM_BASE_URL` | Nein |
| `llm_model` | `"qwen2.5-coder-7b-instruct-mlx"` | `LLM_MODEL` | Nein |
| `postgres_host` | `"evolution_postgres"` | `POSTGRES_HOST` | Nein |
| `postgres_port` | `5432` | `POSTGRES_PORT` | Nein |
| `postgres_db` | `"evolution_db"` | `POSTGRES_DB` | Nein |
| `postgres_user` | `"evolution"` | `POSTGRES_USER` | Nein |
| `postgres_password` | -- | `EVOLUTION_POSTGRES_PASSWORD` | Ja |
| `evolution_api_url` | `"http://evolution_api:8080"` | `EVOLUTION_API_URL` | Nein |
| `evolution_api_key` | -- | `EVOLUTION_API_KEY` | Ja |
| `evolution_instance` | `"niles-whatsapp"` | `EVOLUTION_INSTANCE` | Nein |
| `carddav_url` | `"https://dav.example.com/carddav/32"` | `CARDDAV_URL` | Nein |
| `carddav_user` | `""` | `CARDDAV_USER` | Nein |
| `carddav_password` | `""` | `CARDDAV_PASSWORD` | Nein |

`postgres_password` verwendet `validation_alias="EVOLUTION_POSTGRES_PASSWORD"` -- die Env-Variable heisst anders als das Python-Feld, weil die bestehende PostgreSQL-Instanz bereits diese Variable erwartet.

### .env

```bash
# Pflicht
EVOLUTION_POSTGRES_PASSWORD=<passwort>
EVOLUTION_API_KEY=<api-key>

# Optional
CARDDAV_USER=<user>
CARDDAV_PASSWORD=<passwort>
LOG_LEVEL=INFO
LLM_BASE_URL=http://host.docker.internal:1234/v1
LLM_MODEL=qwen2.5-coder-7b-instruct-mlx
```

---

## 6. Docker

### Container

| Container | Image | Port | Zweck |
|-----------|-------|------|-------|
| `niles_core` | Build aus `docker/Dockerfile.niles` | 8000 | Niles Python Backend |
| `niles_evolution_postgres` | `postgres:15-alpine` | 5432 | PostgreSQL |
| `niles_evolution_api` | `evoapicloud/evolution-api:v2.3.7` | 8080 | WhatsApp Gateway |
| `niles_caddy` | `caddy:2-alpine` | 443/8443 | Reverse Proxy (HTTPS) |

### Netzwerk

Alle Container im Bridge-Netzwerk `niles_network`. Container-Namen dienen als Hostnamen fuer die interne Kommunikation:

- `niles_core` -> `evolution_postgres:5432`
- `niles_core` -> `evolution_api:8080` (nur fuer WhatsApp senden)
- `evolution_api` -> `niles_core:8000` (Webhook)
- `niles_core` -> `host.docker.internal:1234` (LM Studio auf dem Host)

### Volumes

| Volume | Mount | Zweck |
|--------|-------|-------|
| `evolution_postgres` | `/var/lib/postgresql/data` | PostgreSQL-Daten |
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

## 7. Technologie-Stack

| Komponente | Technologie | Version |
|------------|-------------|---------|
| Runtime | Python | >= 3.11 |
| Web Framework | FastAPI | >= 0.129.0 |
| ASGI Server | uvicorn | >= 0.41.0 |
| HTTP Client | httpx | >= 0.28.1 |
| PostgreSQL Driver | asyncpg | >= 0.31.0 |
| LLM Client | openai (Python SDK) | >= 2.21.0 |
| Config | pydantic-settings | >= 2.13.0 |
| Container | Docker Compose | -- |
| LLM Inference | LM Studio (MLX) | lokal |
| WhatsApp Gateway | Evolution API | v2.3.7 |

---

## 8. Weitere Dokumentation

- [Technische Spezifikation](Niles-Core-Spec.md) -- Komponentenbeschreibung und Roadmap
- [API Reference](API.md) -- Endpoints, Payloads, Beispiele
- [Development Guide](Development.md) -- Setup, Testing, Konventionen
