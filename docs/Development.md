# Niles AI Core -- Development Guide

> **Stand:** 2026-02-18

---

## 1. Voraussetzungen

| Software | Version | Zweck |
|----------|---------|-------|
| Python | >= 3.11 | Runtime |
| Docker Desktop | aktuell | Container (PostgreSQL, Evolution API, Caddy) |
| LM Studio | aktuell | Lokale LLM Inference |
| Git | aktuell | Versionskontrolle |

---

## 2. Lokaler Setup

### Repository klonen

```bash
git clone <repo-url> Niles
cd Niles
```

### Python-Umgebung

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Environment konfigurieren

```bash
cp .env.example .env
```

Pflichtfelder in `.env`:

```bash
EVOLUTION_POSTGRES_PASSWORD=<passwort>
EVOLUTION_API_KEY=<api-key>
```

Siehe [Architecture.md](Architecture.md#5-konfiguration) fuer alle Konfigurationsoptionen.

### LM Studio

1. LM Studio starten
2. Modell laden: `qwen2.5-coder-7b-instruct-mlx` (oder anderes MLX-optimiertes Modell)
3. Server starten auf Port 1234

---

## 3. Entwicklung starten

### Variante A: Lokal (ohne Docker)

```bash
./scripts/dev.sh
```

Startet uvicorn mit Auto-Reload auf `http://127.0.0.1:8000`. Setzt voraus, dass PostgreSQL und Evolution API extern laufen (z.B. via Docker).

### Variante B: Docker (komplett)

```bash
./scripts/start.sh
```

Startet alle Container (PostgreSQL, Evolution API, Niles Core, Caddy). Niles Core laeuft mit Volume-Mount und `--reload` fuer Live-Reload bei Code-Aenderungen.

**HTTPS:** Caddy terminiert TLS mit self-signed Zertifikaten. Fuer lokales Testen `--insecure` bei curl verwenden:

```bash
curl -k https://localhost/health
curl -k -X POST https://localhost/chat \
  -H "X-API-Key: <KEY>" \
  -H "Content-Type: application/json" \
  -d '{"message": "Test"}'
```

Alternativ direkt ueber den Docker-internen Port (ohne TLS): `docker exec niles_core curl http://localhost:8000/health`

### Status pruefen

```bash
./scripts/status.sh
```

### Stoppen

```bash
./scripts/stop.sh
```

---

## 4. Tests

### Ausfuehren

```bash
./scripts/test.sh
```

Oder direkt:

```bash
source .venv/bin/activate
python -m pytest tests/ -v
```

### Teststruktur

```
tests/
├── conftest.py          # Shared Fixtures (Environment-Variablen)
├── test_config.py       # Settings-Validierung
├── test_contacts.py     # ContactsAction, normalize_phone
├── test_health.py       # GET /health Endpoint
└── test_memory.py       # MemoryStore, ConversationHistory
```

### Konventionen

- Framework: pytest mit `pytest-asyncio`
- `asyncio_mode = "auto"` in `pyproject.toml` (kein `@pytest.mark.asyncio` noetig)
- Externe Dependencies (PostgreSQL, LLM) werden mit `unittest.mock.AsyncMock` gemockt
- `conftest.py` setzt Pflicht-Environment-Variablen via `monkeypatch`
- Testdateien: `tests/test_<modul>.py`
- Testklassen: `class Test<Klasse>:`

---

## 5. Docker-Workflow

### Build

```bash
docker compose -f docker/docker-compose.yml --env-file .env build niles_core
```

### Logs

```bash
# Alle Container
docker compose -f docker/docker-compose.yml logs -f

# Nur Niles Core
docker compose -f docker/docker-compose.yml logs -f niles_core
```

### Neustart nach Aenderungen

Bei Aenderungen an `src/` ist kein Neustart noetig (Volume-Mount + `--reload`). Bei Aenderungen an `pyproject.toml` (neue Dependencies) muss der Container neu gebaut werden:

```bash
docker compose -f docker/docker-compose.yml --env-file .env up -d --build niles_core
```

---

## 6. Neue Komponente hinzufuegen

### Neues Tool (Agent-Faehigkeit)

1. Tool-Definition in `src/niles/agent/core.py` zur `TOOLS`-Liste hinzufuegen (OpenAI Function-Calling Format)
2. Handler in `NilesAgent._execute_tool_call()` ergaenzen
3. Tests in `tests/test_agent.py` (oder neue Testdatei)

### Neue Action (externe Integration)

1. Datei `src/niles/actions/<name>.py` erstellen
2. Klasse mit async Methoden implementieren
3. In `main.py` Lifespan instanziieren und an Agent uebergeben
4. Tests mit gemockten externen Aufrufen

### Neue Event-Source

1. Datei `src/niles/sources/<name>.py` erstellen
2. FastAPI-Router mit Webhook-Endpoint
3. Event-Dict erstellen und an `agent.process_event()` uebergeben
4. Router in `main.py` einbinden: `app.include_router(router)`

---

## 7. Konventionen

### Sprache

- **Code:** Englisch (Variablen, Funktionen, Kommentare, Docstrings)
- **Agent-Prompts:** Deutsch (soul.md, Tool-Beschreibungen)
- **Dokumentation:** Deutsch

### Async

- Alle I/O-Operationen sind `async`
- PostgreSQL via `asyncpg` (Connection Pool)
- HTTP via `httpx.AsyncClient`
- LLM via `openai.AsyncOpenAI`

### Fehlerbehandlung

- Webhook-Handler: Exceptions fangen und loggen, immer HTTP 200 zurueckgeben
- LLM-Fehler: Fehlermeldung an User, kein Exception-Propagation
- Tool-Call-Fehler: `{"error": "..."}` als Tool-Result zurueck an LLM
- Startup: `ValidationError` bei fehlenden Pflicht-Variablen -> `sys.exit(1)`

### Logging

- `logging.getLogger(__name__)` in jedem Modul
- Level konfigurierbar via `LOG_LEVEL` Environment-Variable
- Format: `%(asctime)s %(levelname)s %(name)s: %(message)s`

---

## 8. Weitere Dokumentation

- [Technische Spezifikation](Niles-Core-Spec.md) -- Komponentenbeschreibung und Roadmap
- [Architektur](Architecture.md) -- Systemuebersicht, Module, Datenfluss
- [API Reference](API.md) -- Endpoints, Payloads, Beispiele
