# Niles AI Core -- Development Guide

> **Updated:** 2026-03-02

---

## 1. Prerequisites

Runtime prerequisites (Docker, Ollama, etc.) see [Deployment Guide #1](Deployment.md#1-prerequisites).

Additionally for development:

| Software | Version | Purpose |
| -------- | ------- | ------- |
| Python | >= 3.11 | Runtime + Tests |
| Tailwind CSS CLI | v3.4.17 | CSS Build (standalone binary, no Node.js) |
| TruffleHog | >= 3.88 | Secret scanning (pre-commit hook, `brew install trufflehog`) |

---

## 2. Local Setup

### Clone Repository

```bash
git clone <repo-url> Niles
cd Niles
```

### Python Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Configure Environment

```bash
cp .env.example .env
```

All environment variables, Ollama setup, and service configuration (Google OAuth, WhatsApp, Vikunja, etc.) are documented in the [Deployment Guide](Deployment.md):

- [Quick Start](Deployment.md#2-quick-start) -- Required variables
- [Environment Reference](Deployment.md#environment-variables) -- Complete variable table
- [Ollama](Deployment.md#3-ollama-llm-backend) -- LLM setup
- [Vikunja](Deployment.md#8-tasks-vikunja) -- Task setup

Complete settings table with defaults: [Niles-Core-Spec.md #6.1](Niles-Core-Spec.md#61-settings).

---

## 3. Tailwind CSS (Frontend Styling)

Templates use Tailwind CSS utility classes. The generated `style.css` is served by FastAPI as a static file.

### Tailwind CLI (Standalone, no Node.js)

```bash
# macOS ARM64:
curl -sLO https://github.com/tailwindlabs/tailwindcss/releases/download/v3.4.17/tailwindcss-macos-arm64
chmod +x tailwindcss-macos-arm64
mv tailwindcss-macos-arm64 tailwindcss
```

### Build CSS

```bash
# One-time build:
./tailwindcss --minify -i src/niles/static/css/input.css -o src/niles/static/css/style.css

# Watch mode (on template changes):
./tailwindcss --watch -i src/niles/static/css/input.css -o src/niles/static/css/style.css
```

### Docker Build

The Dockerfile automatically downloads Tailwind CLI and builds CSS (`python urllib.request.urlretrieve`). When changing templates or `input.css`, the Docker image must be rebuilt -- or `style.css` built locally and provided via volume mount.

**Configuration:** `tailwind.config.js` in the project root defines content paths and dark mode (`class`).

---

## 4. Starting Development

### Option A: Local (without Docker)

```bash
./scripts/dev.sh
```

Starts uvicorn with auto-reload on `http://127.0.0.1:8000`. Requires PostgreSQL and Evolution API to be running externally (e.g., via Docker).

### Option B: Docker (complete)

```bash
./scripts/start.sh
```

Starts all containers (PostgreSQL, Evolution API, Niles Core, Caddy). For live code reload during development, use `./scripts/dev.sh` (Option A) instead -- the Docker setup runs without `--reload` and requires a rebuild for code changes.

**HTTPS:** Caddy terminates TLS with self-signed certificates. For local testing, use `--insecure` with curl:

```bash
curl -k https://localhost/health
curl -k -X POST https://localhost/chat \
  -H "X-API-Key: <KEY>" \
  -H "Content-Type: application/json" \
  -d '{"message": "Test"}'
```

**Web UI:** Open `https://localhost/ui/login` in the browser.

Alternatively via the Docker-internal port (without TLS): `docker exec niles_core curl http://localhost:8000/health`

**Postgres Debugging:** The Postgres port is not exposed by default. To access the database directly (e.g., via `psql`), set in `.env`:

```bash
POSTGRES_HOST_PORT=5432
```

Then: `psql -h 127.0.0.1 -U evolution -d evolution_db`

### Check Status

```bash
./scripts/status.sh
```

### Stop

```bash
./scripts/stop.sh
```

---

## 5. Tests

### Run

```bash
./scripts/test.sh
```

Or directly:

```bash
source .venv/bin/activate
python -m pytest tests/ -v
```

### Test Structure

```text
tests/
├── conftest.py                   # Shared Fixtures (environment variables)
├── test_config.py                # Settings validation
├── test_contacts.py              # ContactsAction, normalize_phone, multi-phone
├── test_core.py                  # NilesAgent, tool-call pipeline, text-tool-call fallback
├── test_health.py                # GET /health endpoint
├── test_memory.py                # MemoryStore, ConversationHistory
├── test_features.py              # Feature flags (send_others, self-check) + webhook auth
├── test_self_chat.py             # WhatsApp self-chat (trigger, strip, webhook integration)
├── test_signal.py                # Signal action, listener, echo guard, triggers
├── test_carddav.py               # CardDAV sync
├── test_caldav.py                # CalDAV sync
├── test_ical_parser.py           # iCalendar parser
├── test_rrule_expansion.py       # RRULE expansion (recurring events)
├── test_calendar_manager.py      # CalendarSourceManager (CRUD, sync, migration)
├── test_calendar_improvements.py # Calendar query improvements
├── test_google_auth.py           # Google Calendar OAuth (token refresh)
├── test_mcp.py                   # MCP integration
├── test_migrations.py            # Alembic migration chain validation
├── test_security.py              # API auth, rate limiting
├── test_settings_store.py        # Runtime settings store
├── test_web.py                   # Web UI, Google OAuth, sessions, CSRF
├── test_weather_mcp.py           # Weather MCP server integration
├── test_whatsapp_sessions.py     # Per-user WhatsApp sessions
├── test_tasks.py                 # Vikunja task management
├── test_vikunja_store.py         # Per-user Vikunja credentials + agent resolution
├── test_vikunja_provisioning.py  # Vikunja auto-provisioning (register, login, token)
├── test_briefing.py              # BriefingGenerator + time parsing + channel routing
├── test_logging.py               # Structured logging + Prometheus metrics
├── test_fetch_mcp.py             # Web Fetch MCP server (SSRF, extraction, truncation)
├── test_notion_sync.py           # Notion API sync (block-to-text, pagination, MD5)
├── test_notion_embeddings.py     # Notion embedding pipeline (chunking, Ollama calls)
├── test_notion_retriever.py      # NotionRetriever (pgvector search, threshold)
├── test_notion_tool.py           # search_notion tool handler
└── test_notion_web.py            # Notion web routes (status/connect/disconnect/sync/search)
```

### Conventions

- Framework: pytest with `pytest-asyncio`
- `asyncio_mode = "auto"` in `pyproject.toml` (no `@pytest.mark.asyncio` needed)
- External dependencies (PostgreSQL, LLM) are mocked with `unittest.mock.AsyncMock`
- `conftest.py` sets required environment variables via `monkeypatch`
- Test files: `tests/test_<module>.py`
- Test classes: `class Test<Class>:`
- Web UI tests use signed session tokens via `itsdangerous.URLSafeTimedSerializer` with a separate `_TEST_SESSION_SECRET`

---

## 6. Docker Workflow

### Build

```bash
docker compose -f docker/docker-compose.yml --env-file .env build niles_core
```

### Logs

```bash
# All containers
docker compose -f docker/docker-compose.yml logs -f

# Niles Core only
docker compose -f docker/docker-compose.yml logs -f niles_core
```

### Restart After Changes

All code changes require rebuilding the container:

```bash
docker compose -f docker/docker-compose.yml --env-file .env up -d --build niles_core
```

For faster iteration, use `./scripts/dev.sh` (local uvicorn with `--reload`).

---

## 7. Database Migrations (Alembic)

Schema changes are managed by [Alembic](https://alembic.sqlalchemy.org/) with raw SQL migrations (`op.execute()`). No SQLAlchemy ORM -- Niles uses `asyncpg` directly.

### Architecture

- Alembic runs as a standalone CLI tool with a sync connection (via `psycopg2`)
- Niles Core runs async (via `asyncpg`) -- the two never share a connection
- Schema version is tracked in the `alembic_version` table
- Store `initialize()` methods contain only business logic, no `CREATE TABLE`

### Creating a New Migration

```bash
# 1. Create migration file
DATABASE_URL="postgresql://evolution:password@localhost:5432/evolution_db" \
    alembic revision -m "add_email_integration"

# 2. Edit the generated file in alembic/versions/
#    - Write upgrade() with raw SQL via op.execute()
#    - Write downgrade() with reverse SQL

# 3. Test locally
DATABASE_URL="..." alembic upgrade head
DATABASE_URL="..." alembic downgrade -1
DATABASE_URL="..." alembic upgrade head

# 4. Commit migration file
```

### Migration File Convention

All migrations use `op.execute()` with raw SQL. No SQLAlchemy Table objects.

```python
"""Short description of the change."""
from alembic import op

revision = "003"
down_revision = "002"

def upgrade():
    op.execute("""
        ALTER TABLE users ADD COLUMN IF NOT EXISTS phone TEXT
    """)

def downgrade():
    op.execute("""
        ALTER TABLE users DROP COLUMN IF EXISTS phone
    """)
```

### Rollback

```bash
# Roll back one migration
DATABASE_URL="..." alembic downgrade -1

# Show current version
DATABASE_URL="..." alembic current

# Show migration history
DATABASE_URL="..." alembic history
```

### Existing Migrations

| File                             | Description                                                |
|----------------------------------|------------------------------------------------------------|
| `001_baseline.py`                | Initial schema (all 11 tables + indexes)                   |
| `002_migrate_contact_phones.py`  | Data migration: legacy phone columns → contact_phones      |
| `003_add_notion_rag.py`          | pgvector extension, `notion_pages` + `notion_embeddings` tables |

---

## 8. Adding New Components

### New Tool (Agent Capability)

1. Add tool definition to the `TOOLS` list in `src/niles/agent/core.py` (OpenAI function calling format)
2. Create a handler module in `src/niles/agent/tools/<name>.py` with a `@register_tool("tool_name")` decorated async function
3. Add the side-effect import in `src/niles/agent/tools/__init__.py`
4. Add tests in `tests/test_core.py` (or new test file)

Handler signature: `async def handle_<name>(args: dict, chat_id: str, ctx: ToolContext) -> dict`

Example:

```python
from . import ToolContext, register_tool

@register_tool("my_tool")
async def handle_my_tool(args: dict, chat_id: str, ctx: ToolContext) -> dict:
    result = await ctx.some_action.do_thing(args["param"])
    return {"status": "ok", "data": result}
```

### New Action (External Integration)

1. Create file `src/niles/actions/<name>.py`
2. Implement class with async methods
3. Instantiate in `main.py` lifespan and pass to agent
4. Write tests with mocked external calls

### New Event Source

1. Create file `src/niles/sources/<name>.py`
2. FastAPI router with webhook endpoint
3. Create event dict and pass to `agent.process_event()`
4. Include router in `main.py`: `app.include_router(router)`

**Alternative: WebSocket listener pattern.** Signal uses a background `asyncio.Task` that maintains a persistent WebSocket connection to `signal-cli-rest-api` instead of receiving webhook callbacks. The listener task is started during `lifespan()` and cancelled on shutdown. Use this pattern when the external service provides a push-based WebSocket stream rather than calling back to a webhook endpoint.

---

## 9. Conventions

### Language

- **Code:** English (variables, functions, comments, docstrings)
- **Agent prompts:** German (soul.md, tool descriptions)
- **Documentation:** English
- **Web UI labels:** German (target language of the end user)

### Async

- All I/O operations are `async`
- PostgreSQL via `asyncpg` (connection pool)
- HTTP via `httpx.AsyncClient`
- LLM via `openai.AsyncOpenAI`

### Error Handling

- Webhook handlers: Catch and log exceptions, always return HTTP 200
- Web UI: Catch agent errors, display error message in chat
- LLM errors: Error message to user, no exception propagation
- Tool call errors: `{"error": "..."}` as tool result back to LLM
- Startup: `ValidationError` on missing required variables -> `sys.exit(1)`

### Text-Based Tool Call Fallback

Smaller local LLMs (e.g., `llama3.1:8b` via Ollama) sometimes don't use the function calling API but output the tool call as JSON text:

```json
{"name": "create_task", "parameters": {"title": "Shopping", "due_date": "2026-02-24"}}
```

`NilesAgent._try_parse_text_tool_call()` detects such responses and executes the tool call anyway. In streaming mode, JSON-like responses are buffered (not immediately streamed to the user) so that no raw JSON appears in the chat bubble.

Note: LLM parameters are sometimes delivered as strings instead of the correct type (e.g., `"priority": "0"` instead of `"priority": 0`). Actions must handle such types robustly (`int()` with fallback).

### Logging

- `logging.getLogger(__name__)` in every module (stdlib loggers are routed through structlog)
- Structured JSON output to stdout via `structlog` (`src/niles/logging_config.py`)
- Level configurable via `LOG_LEVEL` environment variable
- Request tracing: `request_id` is automatically bound to all log entries via `structlog.contextvars`
- Noisy loggers (`httpx`, `httpcore`) are set to WARNING

### Security: No Deletions

Niles must never delete user data. This principle is enforced on three levels:

1. **No delete tools:** The TOOLS list contains no delete operations. `complete_task` only marks as done.
2. **MCP destructive tool blocking:** MCP tools with destructive name prefixes (`delete_`, `remove_`, `drop_`, etc.) are automatically blocked during tool discovery (`src/niles/mcp/client.py`, `_DESTRUCTIVE_PREFIXES`). **Limitation:** Prefix-based only -- tools like `bulk_remove` or `data_wipe_all` are not detected. For stricter control: use per-server allowlists in `mcp_servers.yaml`.
3. **soul.md Rule 7:** The LLM is instructed to refer users to the respective app for deletion requests.

When adding new tools or integrations: do not expose `delete_*` methods to the LLM. Deletions only via web UI with explicit user interaction.

### Scheduled Jobs (APScheduler)

Niles uses APScheduler for automatic background jobs. All jobs are registered in `main.py` during `lifespan()`:

| Job ID | Schedule | Condition | Module |
| ------ | -------- | --------- | ------ |
| `carddav_daily_sync` | Daily 03:00 | `carddav_url` configured | `sync/carddav.py` |
| `calendar_sources_sync` | Daily 03:20 | Calendar sources exist | `sync/manager.py` |
| `briefing_daily` | Mon-Fri, configurable | `feature_briefing_daily=true` | `jobs/briefing.py` |
| `briefing_weekly` | Mon, configurable | `feature_briefing_weekly=true` | `jobs/briefing.py` |
| `notion_sync` | Every N minutes (configurable) | `feature_notion=true` | `sync/notion.py` + `sync/notion_embeddings.py` |

**Briefing pattern:** The briefing jobs (`jobs/briefing.py`) receive `app.state` as argument. At runtime (not at registration), the connected WhatsApp number is determined from the `whatsapp_sessions` table. If no session is connected, the briefing is skipped (no error).

---

## 10. Further Documentation

- [Deployment Guide](Deployment.md) -- Setup, configuration, backup, troubleshooting
- [Technical Specification](Niles-Core-Spec.md) -- Architecture, components, configuration
- [API Reference](API.md) -- Endpoints, payloads, examples
