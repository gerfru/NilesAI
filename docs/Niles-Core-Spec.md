# Niles AI Core -- Technical Specification

> **Spec Version:** 10.0
> **Project Version:** 0.2.11 (`pyproject.toml`)
> **Updated:** 2026-06-11

---

## 1. Project Overview

### 1.1 Vision

Niles is a local, private AI butler on a Mac Mini M4. It receives events from various sources (WhatsApp, web UI, API), processes them with a local LLM, and executes actions.

### 1.2 Core Principles

- **KISS** -- Keep It Simple, Stupid
- **100% Local** -- No cloud dependencies for core functionality
- **Privacy First** -- All data stays on your own server
- **Extensible** -- MCP protocol for community modules

### 1.3 Infrastructure

| Component | Internal Port | External Access | Purpose |
| --------- | ------------- | --------------- | ------- |
| Ollama (llama3.1:8b) | 11434 (Host) | `http://localhost:11434` | LLM inference (OpenAI-compatible) |
| PostgreSQL (pgvector) | 5432 | Not exposed | Database (evolution_db) |
| Evolution API v2.3.7 | 8080 | `https://whatsapp.example.local` | WhatsApp gateway |
| Niles Core (FastAPI) | 8000 | `https://niles.example.local` | Python backend + web UI |
| Vikunja 1.1.0 | 3456 | `https://vikunja.example.local` | Todo/task management |
| signal-cli-rest-api | 8080 | Not exposed | Signal gateway (optional) |
| SearXNG | 8080 | Not exposed | Meta search engine (optional, profile `search`) |
| Langfuse 3 | 3000 | `127.0.0.1:3000` | LLM tracing (optional, profile `langfuse`) |

**Network architecture:** All Docker services communicate internally via HTTP on `niles_network`. External access through homelab-gateway (Caddy reverse proxy on `proxy` network, HTTPS with self-signed certs, subdomain-based routing). PostgreSQL and internal service ports are not exposed. signal-cli-rest-api runs as a Docker service alongside other containers (activated via `feature_signal` in Settings UI).

**Database:** `evolution_db`, user `evolution`, password via `EVOLUTION_POSTGRES_PASSWORD`. Vikunja uses its own database `vikunja_db` (one-time: `CREATE DATABASE vikunja_db OWNER evolution;`). Signal messages are stored in `signal_messages` table (same database).

---

## 2. Architecture

### 2.1 System Overview

```text
External Clients (Browser, curl, Tailscale)
    |
    v HTTPS (self-signed, subdomain routing)
+---------------------------------------------+
|  homelab-gateway (Caddy)                    |
|  niles.example.local    -> niles_core:8000       |
|  whatsapp.example.local -> evolution_api:8080    |
|  vikunja.example.local  -> vikunja:3456          |
|  Security Headers, Access Logs              |
+-------------------+-------------------------+
                    | HTTP (proxy network)
                    v
Event Sources                Niles Core (FastAPI :8000)              External
                         +--------------------------------+
WhatsApp --- Webhook --> |  sources/whatsapp.py           |
                         |                                |
Signal --- WebSocket --> |  sources/signal.py             |
                         |         |                      |
Browser --- /ui/* -----> |  sources/web/ (htmx/Jinja2)    |
                         |    | Google OAuth + Sessions   |
                         |    |                           |
                         |         v                      |
POST /chat  ---------->  |  agent/core.py (NilesAgent)    |--> Ollama :11434
                         |    |  Tool-Call Loop (max 5)   |
                         |    |                           |
                         |    +- memory/store.py          |--> PostgreSQL :5432
                         |    +- memory/history.py        |--> PostgreSQL :5432
                         |    +- actions/contacts.py      |--> PostgreSQL :5432
                         |    +- actions/whatsapp.py      |--> Evolution API :8080
                         |    +- actions/signal.py        |--> signal-cli-rest-api :8080
                         |    +- actions/calendar.py      |--> PostgreSQL :5432
                         |    +- actions/tasks.py         |--> Vikunja :3456
                         |                                |
                         |  Middleware (execution order): |
                         |    RequestIdMiddleware         |
                         |    RateLimitMiddleware (60/min)|
                         |    SecurityHeadersMiddleware   |
                         |    MetricsMiddleware           |
                         |    API Key Auth (X-API-Key)    |
                         |                                |
                         |  GET  /health (unauthenticated)|
                         |  POST /chat (authenticated)    |
                         |  POST /webhook/whatsapp (token)|
                         |  /ui/* (Session Cookie / OAuth)|
                         +--------------------------------+
```

All components run in Docker containers on `niles_network` (internal) and `proxy` (external, shared with homelab-gateway). Ollama runs natively on the host and is reachable via `host.docker.internal:11434`.

### 2.2 Directory Structure

```text
Niles/
├── src/
│   └── niles/                        # Python Backend
│       ├── __init__.py
│       ├── main.py                   # FastAPI + Lifespan orchestrator + Middleware
│       ├── startup.py                # Lifespan helper functions (DB, stores, scheduler, actions, Notion)
│       ├── config.py                 # Pydantic Settings + apply_overrides
│       ├── logging_config.py         # Structured JSON logging (structlog)
│       ├── metrics.py                # Prometheus metrics definitions
│       ├── crypto.py                 # FieldEncryptor (Fernet column-level encryption)
│       ├── network.py                # SSRF guard / private-IP blocklist helpers
│       ├── redaction.py              # PII/secret redaction for logs
│       ├── tokens.py                 # Token helpers (signing/validation)
│       ├── user_store.py             # User management (Google OAuth)
│       ├── settings_store.py         # Runtime settings overrides (PostgreSQL)
│       ├── contact_store.py          # Per-user contacts data access (PostgreSQL)
│       ├── event_store.py            # Calendar events data access (PostgreSQL)
│       ├── whatsapp_store.py        # Per-user WhatsApp sessions (PostgreSQL)
│       ├── signal_store.py          # Signal message store (PostgreSQL)
│       ├── vikunja_store.py         # Per-user Vikunja credentials (PostgreSQL)
│       ├── vikunja_provisioning.py  # Auto-provision Vikunja accounts on login
│       ├── google_token_store.py   # Per-user Google OAuth tokens (PostgreSQL)
│       ├── http_clients.py         # Shared httpx.AsyncClient instances
│       ├── types.py                 # AppState Protocol, type definitions
│       ├── errors.py                # DuplicateEmailError, error_response()
│       ├── http_retry.py            # @retry_http decorator (tenacity)
│       ├── notion_store.py          # Notion pages data access (PostgreSQL)
│       ├── migrate.py               # Alembic migration runner
│       ├── cli.py                   # CLI entrypoint
│       ├── agent/
│       │   ├── core.py               # NilesAgent, pipeline orchestration
│       │   ├── tool_defs.py          # TOOLS list + MAX_TOOL_ROUNDS constant
│       │   ├── context.py            # Context assembly, user/resource resolution
│       │   ├── text_tool_parser.py   # JSON tool-call detection (pure functions)
│       │   ├── prompts.py            # System prompt loading/building
│       │   └── tools/                # Tool handler registry (decorator-based)
│       │       ├── __init__.py       # TOOL_REGISTRY, @register_tool, ToolContext
│       │       ├── calendar.py       # find_event, create_event
│       │       ├── contacts.py       # find_contact
│       │       ├── formatting.py     # Tool-result formatting helpers
│       │       ├── mcp.py            # MCP tool fallback handler
│       │       ├── memory.py         # remember, recall
│       │       ├── signal.py         # send_signal, get_signal_messages
│       │       ├── tasks.py          # list_tasks, create_task, complete_task
│       │       ├── whatsapp.py       # send_whatsapp, get_whatsapp_messages
│       │       └── notion.py        # search_notion
│       ├── memory/
│       │   ├── store.py              # Key-value memory (PostgreSQL, per-user)
│       │   └── history.py            # Conversation history
│       ├── actions/                  # Action modules (Routes → Actions → Stores)
│       │   ├── admin.py              # User CRUD with password hashing
│       │   ├── briefing.py           # BriefingGenerator (daily/weekly overview)
│       │   ├── calendar.py           # Calendar queries
│       │   ├── contacts.py           # Contact search + CardDAV connect/disconnect
│       │   ├── message_dispatch.py   # Shared channel send routing (WhatsApp/Signal)
│       │   ├── notion.py             # NotionRetriever (pgvector RAG search)
│       │   ├── settings.py           # Setting validation + persistence
│       │   ├── signal.py             # Signal send + status (signal-cli-rest-api)
│       │   ├── signal_setup.py       # Signal credential/link management (UI-facing)
│       │   ├── tasks.py              # Vikunja task CRUD (agent-facing)
│       │   ├── vikunja_setup.py      # Vikunja credential management (UI-facing)
│       │   ├── weather.py            # Location search + coordinate persistence
│       │   ├── whatsapp.py           # WhatsApp send (Evolution API)
│       │   └── whatsapp_setup.py     # WhatsApp instance/QR management (UI-facing)
│       ├── jobs/
│       │   └── briefing.py           # Scheduler jobs for briefing
│       ├── sources/
│       │   ├── whatsapp.py           # Webhook handler (token auth)
│       │   ├── signal.py             # WebSocket listener (background task)
│       │   ├── triggers.py           # Shared trigger detection (Hey Niles)
│       │   ├── echo_guard.py         # Echo-loop prevention (10s TTL)
│       │   └── web/                  # Web UI package (feature-based modules)
│       │       ├── __init__.py       # Re-exports for backward compatibility
│       │       ├── _core.py          # Router, templates, auth guards, shared helpers
│       │       ├── _deps.py          # Per-request dependency resolution (AppState access)
│       │       ├── _legal.py         # Legal/imprint/privacy pages
│       │       ├── _auth.py          # Login, Google OAuth, logout
│       │       ├── _chat.py          # Chat page, SSE streaming, history, clear
│       │       ├── _settings.py      # Settings page, update_setting, Ollama models
│       │       ├── _briefing.py      # Briefing test endpoint
│       │       ├── _calendar.py      # CalDAV, calendar sources, Google Calendar OAuth
│       │       ├── _whatsapp.py      # WhatsApp status/connect/disconnect
│       │       ├── _signal.py        # Signal status/QR/link/disconnect
│       │       ├── _weather.py       # Weather location search/set/remove
│       │       ├── _contacts.py      # CardDAV status/connect/disconnect/sync
│       │       ├── _vikunja.py       # Vikunja status/connect/disconnect
│       │       ├── _notion.py       # Notion status/connect/disconnect/sync/search
│       │       └── _admin.py         # User management: list/create/reset/delete
│       ├── sync/
│       │   ├── carddav.py            # CardDAV contact sync
│       │   ├── carddav_manager.py    # CardDAVSourceManager (per-user CRUD, sync, migration)
│       │   ├── caldav.py             # CalDAV calendar sync
│       │   ├── ical_parser.py        # Shared iCalendar parser
│       │   ├── manager.py            # CalendarSourceManager (CRUD, sync, migration)
│       │   ├── notion.py             # Notion API sync (pages → notion_pages)
│       │   ├── notion_embeddings.py  # Ollama embedding pipeline (→ notion_embeddings)
│       │   ├── notion_summarizer.py  # Page summaries for chunk context
│       │   └── ollama_embedder.py    # Ollama embedding client
│       ├── mcp/
│       │   ├── client.py             # MCP server manager
│       │   ├── user_pool.py          # Per-user gws MCP server pool
│       │   ├── weather/              # Weather MCP server (Open-Meteo)
│       │   │   ├── __init__.py
│       │   │   ├── __main__.py
│       │   │   └── server.py
│       │   ├── fetch/                # Web Fetch MCP server (trafilatura)
│       │   │   ├── __init__.py
│       │   │   ├── __main__.py
│       │   │   └── server.py
│       │   └── search/               # SearXNG web search MCP server (FEATURE_SEARCH)
│       │       ├── __init__.py
│       │       ├── __main__.py
│       │       └── server.py
│       ├── templates/
│       │   ├── base.html             # Layout (Nav, CSP, Tailwind CSS, htmx)
│       │   ├── login.html            # Login (Google + API key fallback)
│       │   ├── chat.html             # Chat UI with SSE streaming
│       │   ├── settings.html         # Settings dashboard
│       │   └── fragments/            # htmx fragments
│       │       ├── message.html
│       │       ├── history.html
│       │       ├── toast.html
│       │       ├── calendars.html
│       │       ├── calendar_sources.html
│       │       ├── signal_status.html
│       │       └── notion_status.html
│       └── static/
│           ├── css/
│           │   ├── input.css         # Tailwind directives + custom components
│           │   └── style.css         # Generated Tailwind output
│           └── js/app.js             # SSE streaming, dark mode, CSRF
├── tests/
│   ├── conftest.py                   # Shared fixtures (env variables)
│   ├── test_config.py               # Settings validation
│   ├── test_contacts.py             # ContactsAction, normalize_phone, multi-phone
│   ├── test_core.py                 # NilesAgent, tool-call pipeline
│   ├── test_health.py               # GET /health endpoint
│   ├── test_memory.py               # MemoryStore, ConversationHistory
│   ├── test_features.py             # Feature flags + webhook auth
│   ├── test_carddav.py              # CardDAV sync
│   ├── test_caldav.py               # CalDAV sync
│   ├── test_ical_parser.py          # iCalendar parser
│   ├── test_rrule_expansion.py      # RRULE expansion (recurring events)
│   ├── test_calendar_manager.py     # CalendarSourceManager (CRUD, sync, migration)
│   ├── test_calendar_improvements.py # Calendar query improvements
│   ├── test_google_token_store.py    # Per-user Google OAuth token store
│   ├── test_user_mcp_pool.py        # Per-user gws MCP server pool
│   ├── test_http_retry.py           # HTTP client retry logic
│   ├── test_mcp.py                  # MCP integration
│   ├── test_security.py             # API auth, rate limiting
│   ├── test_settings_store.py       # Runtime settings store
│   ├── test_web.py                  # Web UI, Google OAuth, sessions, CSRF
│   ├── test_whatsapp_sessions.py    # Per-user WhatsApp sessions
│   ├── test_tasks.py                # Vikunja task management
│   ├── test_vikunja_store.py        # Per-user Vikunja credentials + agent resolution
│   ├── test_vikunja_provisioning.py # Vikunja auto-provisioning
│   ├── test_migrations.py          # Alembic migration chain validation
│   ├── test_weather_mcp.py         # Weather MCP server integration
│   ├── test_self_chat.py            # WhatsApp self-chat trigger
│   ├── test_signal.py               # Signal action, listener, echo guard, triggers
│   ├── test_briefing.py              # BriefingGenerator + time parsing + channel routing
│   ├── test_logging.py              # Structured logging + Prometheus metrics
│   ├── test_fetch_mcp.py            # Web Fetch MCP server (SSRF, extraction, truncation)
│   ├── test_notion_sync.py          # Notion API sync (block-to-text, pagination, MD5)
│   ├── test_notion_embeddings.py    # Notion embedding pipeline (chunking, Ollama calls)
│   ├── test_notion_retriever.py     # NotionRetriever (pgvector search, threshold)
│   ├── test_notion_tool.py          # search_notion tool handler
│   ├── test_notion_web.py           # Notion web routes (status/connect/disconnect/sync/search)
│   ├── test_notion_rag_prompt.py    # Notion RAG context injection into prompts
│   ├── test_settings_action.py      # SettingsAction validation + persistence
│   ├── test_admin_action.py         # AdminAction user CRUD
│   ├── test_contacts_action_setup.py # ContactsAction connect/disconnect
│   └── test_vikunja_setup_action.py # VikunjaSetupAction SSRF, credentials, status
├── alembic/
│   ├── env.py                       # Alembic environment (sync connection)
│   ├── script.py.mako               # Migration template
│   └── versions/                    # Migration files (001_baseline, ..., 012_memory_user_id)
├── config/
│   ├── soul.md                       # Agent personality
│   ├── mcp_servers.yaml              # MCP server configuration
│   └── searxng/
│       └── settings.yml              # SearXNG engine config
├── docker/
│   ├── docker-compose.yml
│   ├── Dockerfile.niles              # Non-root user (UID 1000)
│   └── Caddyfile                     # HTTPS, security headers, access logs
├── scripts/
│   ├── dev.sh                        # Local dev server
│   ├── test.sh                       # pytest runner
│   ├── build.sh                      # Docker image build
│   ├── start.sh                      # Docker start
│   ├── stop.sh                       # Docker stop
│   ├── status.sh                     # Service status check
│   ├── backup.sh                     # Database + config backup
│   ├── cleanup.sh                    # Full reset (delete volumes)
│   └── check-pii.sh                  # PII leak detection
├── docs/
├── tailwind.config.js          # Tailwind CSS configuration
├── pyproject.toml
├── .env
└── .env.example
```

**Dependency injection:** Startup wiring is collected in a `StartupContext` dataclass (`startup.py`), which bundles the pool, encryptor, stores, actions, scheduler, and agent built during the lifespan. The runtime `app.state` shape is described by the `AppState` Protocol in `types.py`.

### 2.3 Data Flow: WhatsApp Message

```text
1. Evolution API receives WhatsApp message
2. Evolution API sends webhook POST to /webhook/whatsapp
3. sources/whatsapp.py filters on messages.upsert
   3a. Own messages (fromMe=true):
       - "Hey Niles" trigger -> Agent processes, sends response (self-chat)
       - Without trigger -> Ignore (notes, links, etc.)
   3b. External messages -> Ignored (no LLM call, no web chat, no auto-reply).
       Evolution API stores messages internally. Agent reads via findMessages API.
4. [Self-Chat] Extracts sender (JID -> phone number) and text
5. Creates event: {"type": "whatsapp", "from": "wa-self-{nr}", "content": "..."}
6. Calls agent.process_event(event)
   6a. Loads all memory entries -> injects into system prompt
   6b. Loads last 20 messages of the conversation
   6c. Builds messages: [system, ...history, user]
   6d. Saves user message in history
   6e. Calls LLM (OpenAI-compatible API)
   6f. If tool calls: execute, feed results back to LLM (max 5 rounds)
   6g. Saves response in history
7. Self-chat: sources/whatsapp.py sends response via WhatsAppAction
   External: Message stored by Evolution API (queryable via get_whatsapp_messages tool)
8. Returns HTTP 200 (regardless of result)
```

### 2.4 Data Flow: Web UI Chat (SSE Streaming)

```text
1. User opens /ui/chat (GET)
2. sources/web/_core.py checks signed session cookie (itsdangerous)
3. Loads per-user chat history (chat_id = "web-user-{uid}")
4. Renders chat.html with Jinja2, sets CSRF cookie
5. User sends message (Enter/Send button)
6. JavaScript: Display user bubble immediately, clear input, show "Niles is thinking..."
7. fetch() POST to /ui/api/chat/stream (SSE)
8. sources/web/_chat.py checks session + CSRF (Double-Submit Pattern)
9. Creates event: {"type": "web", "from": "web-user-1", "content": "..."}
10. Calls agent.process_event_stream(event)
    10a. Tool calls run non-streaming (yield status updates)
    10b. Final response is streamed (yield chunks word by word)
11. JavaScript: Create assistant bubble, insert text chunk by chunk
12. After stream end: Render markdown (marked.js + DOMPurify)
```

### 2.5 Data Flow: Google OAuth Login

```text
1. User clicks "Sign in with Google" on /ui/login
2. Redirect to Google OAuth (/ui/login/google)
   - State token set as cookie (CSRF protection)
   - Redirect URI from BASE_URL (or request headers as fallback)
3. Google shows consent screen (openid email profile)
4. Google callback to /ui/callback/google with auth code
5. Server checks state token, exchanges code for access token
6. Server calls Google Userinfo API (email, name, avatar)
7. Checks email_verified and GOOGLE_ALLOWED_EMAILS whitelist
8. user_store.create_or_update() -> INSERT ON CONFLICT UPDATE
9. Set signed session cookie (itsdangerous, 30 days)
10. Redirect to /ui/chat
```

---

## 3. Components

### 3.1 FastAPI Main (`src/niles/main.py`) + Startup Helpers (`src/niles/startup.py`)

Entry point. `main.py` defines the FastAPI app, middleware, and a thin `lifespan()` orchestrator that delegates to helper functions in `startup.py`:

**`startup.py` helpers:**

| Helper | Responsibility |
|--------|---------------|
| `setup_database(settings)` | asyncpg pool (min=2, max=10), FieldEncryptor, Alembic check |
| `setup_stores(pool, encryptor, settings)` | Memory, History, UserStore, WhatsApp, Vikunja, CardDAV, CalDAV, Calendar |
| `setup_scheduler(settings, stores)` | APScheduler + cron jobs (CardDAV 03:00, calendar 03:20, briefing, Notion) |
| `setup_actions(settings, stores)` | Contacts, WhatsApp, Signal, Weather, Admin, Settings, Vikunja setup actions |
| `setup_notion_rag(pool, settings, agent, scheduler)` | Notion sync/embed/retriever pipeline (when `feature_notion=true`) |

**`lifespan()` orchestrator sequence:**

1. Load settings (ValidationError on missing secrets -> `sys.exit(1)`)
2. Configure structured JSON logging via structlog
3. Call `setup_database()` — pool + Fernet encryptor
4. Call `setup_stores()` — all data stores initialized
5. Call `setup_scheduler()` — APScheduler + cron jobs
6. Start MCP manager + UserMCPPool
7. Call `setup_actions()` — action layer + agent
8. Call `setup_notion_rag()` — Notion pipeline (optional)
9. Start Signal WebSocket listener (when `feature_signal=true`)
10. Save everything to `app.state`

**Middleware** (execution order, outermost first):

1. `RequestIdMiddleware` -- Generates or validates `X-Request-ID` (max 64 chars, alnum/dash/underscore), binds to structlog contextvars, echoes in response header
2. `RateLimitMiddleware` -- 60 req/min per IP, /health and /static exempt, max 10,000 IPs tracked
3. `SecurityHeadersMiddleware` -- X-Content-Type-Options, X-Frame-Options, Referrer-Policy, Permissions-Policy
4. `MetricsMiddleware` -- Prometheus HTTP request count and duration, /metrics /health /static exempt, normalizes numeric/UUID path segments to `:id`

**Endpoints:** See `docs/API.md`.

### 3.2 Config (`src/niles/config.py`)

```python
class Settings(BaseSettings):
    # Logging
    log_level: str = "INFO"
    # LLM
    llm_base_url: str = "http://host.docker.internal:11434/v1"
    llm_model: str = "llama3.1:8b"
    llm_temperature_tools: float = 0.35  # temperature when tools are available
    llm_temperature_chat: float = 0.3    # temperature for pure chat (no tools)
    llm_max_tokens: int = 4096           # max completion tokens per LLM call
    llm_timeout: float = 120.0           # max seconds per LLM request
    llm_num_ctx: int = 8192              # Ollama context window (input+output)
    mcp_max_result_tokens: int = 3000    # cap a single MCP tool result (approx. tokens)
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
    # Internal base URL for webhooks (Evolution API -> Niles Core, Docker-internal)
    webhook_base_url: str = "http://niles_core:8000"
    # Auth
    niles_api_key: str      # Auto-generated via secrets.token_urlsafe(32)
    session_secret: str     # Auto-generated via secrets.token_urlsafe(64)
    base_url: str = ""      # For OAuth redirect URI
    # Timezone
    timezone: str = "Europe/Vienna"
    # Phone normalization: default country code (without +) for local numbers
    phone_country_code: str = "43"  # Austria
    # Features
    feature_whatsapp_send_others: bool = True  # May Niles send WhatsApp to others?
    # CardDAV (legacy env config; per-user creds live in carddav_sources table)
    carddav_url: str = ""
    carddav_user: str = ""
    carddav_password: str = ""
    # CalDAV (Legacy, auto-migrated into calendar_sources)
    caldav_url: str = ""
    caldav_user: str = ""
    caldav_password: str = ""
    caldav_calendars: str = ""  # Comma-separated collection hrefs
    # Google OAuth (optional)
    google_client_id: str = ""
    google_client_secret: str = ""
    google_allowed_emails: str = ""
    # Weather (configured via Settings UI, stored as strings for env-var pass-through)
    weather_latitude: str = ""
    weather_longitude: str = ""
    weather_location_name: str = ""
    # Vikunja (Todo/Task Management) — tokens are per-user (auto-provisioned)
    vikunja_api_url: str = ""
    vikunja_public_url: str = ""
    # Signal (signal-cli-rest-api)
    signal_api_url: str = "http://signal_api:8080"
    signal_phone_number: str = ""
    feature_signal_send_others: bool = False
    feature_signal: bool = False
    # Trusted reverse proxy CIDR for X-Forwarded-For (empty = disabled)
    trusted_proxy: str = ""
    # Web Search (SearXNG)
    feature_search: bool = False
    searxng_url: str = "http://searxng:8080"
    # Briefing / Digest
    briefing_channel: str = "whatsapp"        # whatsapp | signal | both
    feature_briefing_daily: bool = False
    feature_briefing_weekly: bool = False
    briefing_daily_time: str = "07:30"        # HH:MM, Mon-Fri
    briefing_weekly_time: str = "07:15"       # HH:MM, Monday
    # Notion RAG (see docs/RAG.md for architecture details)
    feature_notion: bool = False
    notion_token: str = ""
    notion_sync_interval: int = 30            # minutes between syncs
    notion_embedding_model: str = "nomic-embed-text-v2-moe"
    notion_summary_model: str = ""            # LLM for summaries (falls back to llm_model)
    notion_summary_max_input: int = 4000      # Max chars sent to LLM for summarization
    notion_summary_max_tokens: int = 200      # Max LLM output tokens for summary

    # Credential encryption (column-level, Fernet AES-128-CBC + HMAC)
    # REQUIRED by default. App refuses to start without it.
    credential_encryption_key: str = ""
    # Set to true to allow starting without a key (dev only)
    credential_encryption_optional: bool = False

    # LLM Tracing (Langfuse, opt-in — requires langfuse package)
    langfuse_host: str = ""
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""

    # Error tracking (Sentry, opt-in)
    sentry_dsn: str = ""
    sentry_traces_sample_rate: float = 0.1

    # Conversation history pruning
    history_retention_days: int = 90
```

Loads from `.env` and environment variables. `extra = "ignore"`.

`apply_overrides(settings, overrides)` returns a new Settings instance with the provided values (via `model_copy`).

Complete settings table with defaults and env variables: see #6.1.

### 3.3 Agent Core (`src/niles/agent/core.py`)

`NilesAgent` processes events through a tool-call pipeline:

```python
class NilesAgent:
    def __init__(self, config, contacts, whatsapp, memory, history,
                 mcp_manager=None, calendar=None, calendar_manager=None,
                 wa_store=None, vikunja_store=None,
                 signal=None, signal_store=None,
                 user_store=None, http_client=None): ...
    async def process_event(self, event: dict) -> str: ...
    async def process_event_stream(self, event: dict): ...  # SSE async generator
    async def _execute_tool_call(self, tool_call, chat_id) -> dict: ...
    async def _resolve_wa_instance(self, chat_id) -> str | None: ...
    async def _handle_phone_choice(self, chat_id, content) -> str | None: ...
```

`process_event_stream()` is an async generator for SSE streaming. Tool calls run non-streaming (yield `{"type": "status"}`), the final response is streamed word by word (yield `{"type": "chunk"}`). At the end yield `{"type": "done"}`.

**Tool handler registry (`agent/tools/`):** Tool execution logic is organized into feature-based handler modules. Each handler is registered via the `@register_tool("name")` decorator, which adds it to `TOOL_REGISTRY`. On tool call, `_execute_tool_call()` looks up the handler in the registry; if not found, falls back to the MCP handler. Tool definitions (OpenAI function calling format) are in `agent/tool_defs.py` as the `TOOLS` list (extracted from core.py for readability). A `ToolContext` dataclass bundles all dependencies (config, actions, stores, helper callables) and is passed to each handler.

**Event format:**

```json
{"type": "whatsapp|signal|chat|web", "from": "436601234...|signal-self-{nr}|api|web-user-1", "content": "..."}
```

**Registered tools:**

| Tool | Parameters | Description |
| ---- | ---------- | ----------- |
| `find_contact` | `name: str` | Contact search in PostgreSQL. Returns `full_name`, `phone` (preferred), `phones` (all with type), `email`. |
| `send_whatsapp` | `to: str, text: str` | Send message (number or name). Multi-phone: asks user for multiple numbers (TTL 5 min). Per-user instance resolution. |
| `get_whatsapp_messages` | `contact: str` | Read WhatsApp chat history (by contact name or phone number). 30-day window. Via Evolution API `findMessages`. Result contains `date_range` and `hinweis` for LLM summarization. Media placeholders for images, videos, voice messages, etc. |
| `send_signal` | `to: str, text: str` | Send Signal message (name or phone number). Feature flag: `feature_signal_send_others` for non-self messages. |
| `get_signal_messages` | `contact: str` | Read Signal message history (by contact name or phone number). 30-day window. From local PostgreSQL store. |
| `remember` | `key: str, value: str` | Store fact in memory |
| `recall` | `key: str` | Retrieve fact from memory |
| `find_event` | `query?, date_from?, date_to?, calendar?` | Search calendar events (max 10 results). Supports date filters and calendar selection. |
| `create_event` | `summary: str, start: str, end?, description?, location?` | Create calendar event on writable source (via CalendarSourceManager). |
| `list_tasks` | `project?, include_done?` | List open tasks from Vikunja (max 50). Feature flag: `feature_vikunja`. |
| `create_task` | `title: str, description?, due_date?, priority?, project?` | Create new task in Vikunja. |
| `complete_task` | `title: str` | Find task by title, request confirmation, then mark as done. |
| `mcp__gws__*` | varies | Google Calendar tools via per-user gws MCP (when Google connected). |
| `mcp__weather__*` | varies | Weather tools via MCP (Open-Meteo, always active). |
| `mcp__fetch__fetch_url` | `url: str, max_chars?: int` | Fetch and extract text from a web page (always active). SSRF-protected. |
| `mcp__searxng__web_search` | `query: str, result_count?: int, ...` | Web search via SearXNG (when `feature_search=true`). |
| `search_notion` | `query: str, max_results?: int` | Semantic search over Notion knowledge base (when `feature_notion=true`). |

**Pipeline per event:**

1. Check pending phone choice (bypass LLM for multi-phone selection, TTL 5 min)
2. Load all memory entries -> inject into system prompt
3. Load calendar source names (cached, 5 min TTL) -> inject into system prompt
4. Load last 20 messages of the conversation
5. Build messages: System + History + User
6. Call LLM (max 5 tool-call rounds)
7. Save user and assistant message together in history (atomic, no orphaned records)
8. Return response

**Per-user WhatsApp instance resolution:** For `chat_id` with prefix `web-user-`, the WhatsApp instance is resolved from `whatsapp_sessions`. Fallback to global instance (`config.evolution_instance`).

### 3.4 Memory Store (`src/niles/memory/store.py`)

Per-user key-value store in PostgreSQL (table `memory`). All operations are scoped by `user_id` (composite PK `(user_id, key)`).

```python
class MemoryStore:
    async def get(self, user_id: int, key: str) -> Any | None
    async def set(self, user_id: int, key: str, value: Any) -> None  # UPSERT
    async def delete(self, user_id: int, key: str) -> bool
    async def search(self, user_id: int, prefix: str) -> list[MemoryEntry]
    async def list_all(self, user_id: int, *, limit: int = 200,
                       offset: int = 0) -> list[MemoryEntry]   # For system prompt
```

### 3.5 Conversation History (`src/niles/memory/history.py`)

Per-chat message history in PostgreSQL (table `conversations`).

```python
class ConversationHistory:
    async def initialize(self) -> None
    async def add_message(self, chat_id: str, role: str, content: str) -> None
    async def get_recent(self, chat_id: str, limit: int = 20) -> list[dict]
    async def clear(self, chat_id: str) -> int
```

`chat_id` corresponds to `event["from"]` (phone number for WhatsApp, `"api"` for /chat, `"web-user-{uid}"` for web UI).

### 3.6 User Store (`src/niles/user_store.py`)

User management for Google OAuth in PostgreSQL (table `users`).

```python
class UserStore:
    async def initialize(self) -> None
    async def get_by_email(self, email: str) -> dict | None
    async def create_or_update(self, email, display_name, avatar_url) -> dict
    async def get_by_id(self, user_id: int) -> dict | None
    async def verify_password(self, email: str, password: str) -> dict | None
    async def update_password(self, user_id: int, password_hash: str) -> bool
```

Users are automatically created on first Google login (INSERT ON CONFLICT UPDATE). Password-based login is supported: admins can set passwords via the admin panel, and `update_password()` also sets `auth_method='password'`.

### 3.7 Settings Store (`src/niles/settings_store.py`)

Runtime setting overrides in PostgreSQL (table `settings_overrides`).

```python
EDITABLE_SETTINGS = {
    "llm_base_url", "llm_model", "timezone", "log_level",
    "feature_whatsapp_send_others",
    "caldav_calendars",
    "feature_signal_send_others",
    "signal_api_url", "signal_phone_number", "signal_disabled",
    "feature_briefing_daily", "feature_briefing_weekly",
    "briefing_daily_time", "briefing_weekly_time", "briefing_channel",
    "weather_latitude", "weather_longitude", "weather_location_name",
    "feature_search", "searxng_url",
    "feature_notion", "notion_token", "notion_sync_interval",
    "notion_embedding_model", "notion_chunk_size", "notion_chunk_overlap",
    "notion_similarity_threshold",
}

class SettingsStore:
    async def initialize(self) -> None
    async def get_all(self) -> dict[str, Any]
    async def set(self, key: str, value: Any) -> None  # Validates key
    async def delete(self, key: str) -> None
```

Only keys in `EDITABLE_SETTINGS` can be changed. Credentials and infrastructure settings are locked. **CardDAV credentials are no longer stored in `settings_overrides`** — they moved into the per-user `carddav_sources` table (managed by `CardDAVSourceManager`).

### 3.8 WhatsApp Session Store (`src/niles/whatsapp_store.py`)

Per-user WhatsApp sessions in PostgreSQL (table `whatsapp_sessions`).

```python
class WhatsAppSessionStore:
    async def initialize(self) -> None
    async def get_session(self, user_id: int) -> dict | None
    async def get_by_instance(self, instance_name: str) -> dict | None  # Webhook routing
    async def get_by_phone(self, phone_number: str) -> dict | None     # Self-chat user resolution
    async def upsert_session(self, user_id, instance_name, status, phone_number) -> None
    async def update_status(self, user_id, status, phone_number) -> None
    async def delete_session(self, user_id: int) -> None
```

Each web UI user can connect their own WhatsApp instance (via QR code in the web UI). Status: `disconnected`, `connecting`, `connected`. The instance is used for chat ID resolution on webhook receipt and as sender instance when sending.

### 3.9 System Prompts (`src/niles/agent/prompts.py`)

```python
def load_system_prompt(path: str | None = None) -> str
def build_system_prompt(
    base_prompt: str,
    memories: list[dict],
    timezone: str = "Europe/Vienna",
    calendar_sources: list[str] | None = None,
) -> str
```

`load_system_prompt` loads `config/soul.md`. `build_system_prompt` appends:

1. **Current time** section (weekday, date, time, timezone)
2. **Upcoming 7 days** (weekday → date mapping so the LLM doesn't have to calculate)
3. **Available calendars** (list of calendar source names, if any)
4. **Memory** section (all key-value entries)

### 3.10 Web UI (`src/niles/sources/web/`)

Web interface with Jinja2 templates, Tailwind CSS, and htmx. Chat uses SSE streaming (custom JavaScript), settings/history/calendar use htmx. The web UI is organized as a feature-based package with 12 modules (auth, chat, settings, calendar, etc.), each registering routes on a shared `router` via side-effect imports. Shared infrastructure (auth guards, session helpers, CSRF, templates) lives in `_core.py`:

**Authentication (two parallel systems):**

- **Google OAuth 2.0** -> Web UI login (signed session cookies via itsdangerous)
- **API Key** -> Fallback login (when Google OAuth is not configured)

**Session management:**

- Signed cookies via `URLSafeTimedSerializer` (itsdangerous)
- Separate `session_secret` (not `niles_api_key`)
- CSRF Double-Submit Pattern (cookie + X-CSRF-Token header)
- Per-user chat IDs: `web-user-{uid}`

**Routes:** See `docs/API.md`.

### 3.11 WhatsApp Source (`src/niles/sources/whatsapp.py`)

Webhook handler for Evolution API v2.3.7:

- Token authentication via query parameter (`?token=...`, hmac.compare_digest)
- Filters on `event == "messages.upsert"`
- Extracts text from `message.conversation` or `extendedTextMessage.text`
- Returns 401 for auth errors, 200 for all other cases (prevents retry spam)

**Self-chat trigger:** Own messages (`fromMe: true`) are checked for trigger phrases ("Hey Niles", "Hi Niles", "Hallo Niles", "Niles" -- case-insensitive, word-boundary). On trigger: Remove phrase, agent processes the rest, send response to own number. Without trigger: Ignore. Echo-loop guard: Sent message IDs are cached for 10s, echoed webhooks are skipped.

**Self-chat chat_id:** `wa-self-{number}` -- own conversation history, separate from external chats and web UI.

**LID addressing:** WhatsApp uses LID (Linked Identity Device) addresses since 2025. New messages have `key.remoteJid = "...@lid"` instead of `"...@s.whatsapp.net"`. The phone JID is in `key.remoteJidAlt`. The webhook handler detects `@lid` JIDs and uses `remoteJidAlt` instead for sender extraction, chat_id, and reply routing.

**External messages:** Stored internally by the Evolution API (no LLM call, no web chat, no auto-reply). The agent reads them via the `get_whatsapp_messages` tool directly through the Evolution API `findMessages` endpoint ("What did Max write me?"). Contact name is resolved to phone number via `contacts.find_by_name()`, then passed as JID to the API. 30-day window, max 50 messages. Niles only replies to external people when the user explicitly asks via the `send_whatsapp` tool (controlled by `feature_whatsapp_send_others`).

**Per-user instance routing:** The webhook identifies the Evolution API instance (`payload.instance`). For self-chat, the instance from the webhook payload is used. For `get_whatsapp_messages`, the instance is resolved via `_resolve_wa_instance(chat_id)` from the `whatsapp_sessions` table.

**Note:** Webhook token is passed as query parameter since Evolution API v2.3.x does not support custom headers (see [Issue #1933](https://github.com/EvolutionAPI/evolution-api/issues/1933)).

### 3.12 WhatsApp Action (`src/niles/actions/whatsapp.py`)

```python
class WhatsAppAction:
    async def send_message(self, to: str, text: str, instance: str | None = None) -> dict
    async def fetch_messages(self, remote_jid: str, instance: str | None = None) -> list[dict]
    async def create_instance(self, instance_name: str, webhook_url: str) -> dict
    async def get_connection_state(self, instance_name: str) -> str
    async def get_qr_code(self, instance_name: str) -> dict
    async def get_owner_jid(self, instance_name: str) -> str | None
    async def logout_instance(self, instance_name: str) -> dict
    async def delete_instance(self, instance_name: str) -> dict
```

`send_message` sends via `POST /message/sendText/{instance}` to Evolution API. Timeout 30s. Optional `instance` parameter for per-user WhatsApp sessions (fallback: global `evolution_instance` from config).

`fetch_messages` queries messages via `POST /chat/findMessages/{instance}`. The filter payload sets both `remoteJid` and `remoteJidAlt` to the phone JID -- Evolution API's Baileys override (PR #2249) combines these with OR, so both old phone JIDs and new LID messages are found. Both keys must be set (with only one key, the OR clause produces an empty match, Prisma bug). Client-side 30-day filter, chronologically sorted. Media messages without text receive placeholders ([Image], [Video], [Voice message], [Sticker], [Document], [Contact], [Location]).

`get_owner_jid` retrieves the owner JID (`phone@s.whatsapp.net`) of a connected instance via `GET /instance/fetchInstances`. Used in the web UI WhatsApp flow to determine the phone number after successful pairing.

**Tool result metadata:** The `get_whatsapp_messages` tool returns `date_range` (formatted time period) and `hinweis` (summarization instruction) alongside the transcript -- analogous to the `hinweis` field in `find_event`. These fields help the 8B LLM produce structured summaries instead of raw transcript dumps.

Instance management methods control Evolution API instances for the per-user WhatsApp flow (create, fetch QR code, check connection state, determine owner JID, disconnect, delete).

### 3.13 Signal Source (`src/niles/sources/signal.py`)

WebSocket-based background listener for signal-cli-rest-api:

```python
async def signal_listener(app_state, shutdown_event: asyncio.Event): ...
async def _handle_envelope(app_state, data: dict): ...
```

**Connection:** Maintains a persistent WebSocket connection to `ws://signal_api:8080/v1/receive/{number}?timeout=3600`. The `timeout` parameter keeps the server-side connection alive (signal-cli defaults to 1s without it). Reconnects with exponential backoff (5s, 10s, 20s, max 60s). Checks `shutdown_event` before each reconnect.

**Message handling (`_handle_envelope`):**

- `dataMessage` (incoming from others): Store in `signal_messages`, no trigger check, no auto-reply
- `syncMessage.sentMessage` (self-chat): Store, check echo guard, check trigger, agent call + reply
- Empty envelopes: Ignored

**Echo-loop guard:** Text-based (truncated to 200 chars as key, monotonic timestamp, 10s TTL). Different from WhatsApp's message-ID-based guard because signal-cli-rest-api does not provide message IDs for sent messages.

**Self-chat trigger:** Shared with WhatsApp via `sources/triggers.py`. Trigger phrases: "Hey Niles", "Hi Niles", "Hallo Niles", "Niles" (case-insensitive, word-boundary). Self-chat `chat_id`: `signal-self-{number}`.

> **Known Limitation:** Self-chat via "Note to Self" does not work due to an upstream signal-cli bug ([#1930](https://github.com/AsamK/signal-cli/issues/1930)). As a linked device, signal-cli cannot parse SyncMessage envelopes -- the message text is lost (`syncMessage: {}` or `InvalidMessageStructureException`). Affects all versions up to v0.13.24. The self-chat code path is implemented and tested but cannot be exercised until a fixed signal-cli release is available.

**Dynamic start:** The listener can be started dynamically after QR-code linking via `_ensure_signal_listener()` in `web/_signal.py`, without requiring a container restart.

### 3.14 Signal Action (`src/niles/actions/signal.py`)

```python
class SignalAction:
    def __init__(self, config: Settings): ...
    async def send_message(self, to: str, text: str) -> dict
    async def get_status(self) -> dict
    async def get_accounts(self) -> list[str]
    async def get_qr_link(self, device_name: str = "niles") -> bytes | None
```

- `send_message`: `POST /v2/send` to signal-cli-rest-api. Timeout 30s. No API key needed (signal-cli-rest-api has no auth).
- `get_status`: `GET /v1/about` -- registration status.
- `get_accounts`: `GET /v1/accounts` -- lists registered/linked phone numbers. Used for auto-discovery after QR linking.
- `get_qr_link`: `GET /v1/qrcodelink` -- returns QR code PNG for device linking.

Phone format: `+43660...` (international with `+` prefix, Signal convention).

### 3.15 Signal Message Store (`src/niles/signal_store.py`)

Local message store needed because signal-cli-rest-api has no `findMessages` equivalent (unlike Evolution API).

```python
class SignalMessageStore:
    async def initialize(self) -> None      # CREATE TABLE + INDEX
    async def store(self, phone, text, from_me, chat_id="") -> None
    async def get_messages(self, phone, days=30, limit=200) -> list[dict]
```

Table: `signal_messages` (see #4 Database Schema).

### 3.16 Contact Lookup (`src/niles/actions/contacts.py`)

```python
def normalize_phone(phone: str) -> str        # +43/00/0 -> 43...
class ContactsAction:
    async def find_by_name(self, name: str) -> dict | None
```

Search with priority: exact > prefix > partial > first/last name.
Multi-word search: With multiple words (e.g., "Thomas Brunner"), each word must appear in at least one name field (full_name, first_name, last_name).
Phone normalization: Austria-specific (leading 0 -> 43).

**Multi-phone support:** Contacts can have multiple phone numbers (table `contact_phones`, 1:N). `find_by_name` returns:

- `phone`: preferred number (priority: mobile > home > work > other)
- `phones`: all numbers with type (`[{"type": "mobile", "number": "436601234567"}, ...]`)
- Fallback to legacy columns (`phone_primary`, `phone_mobile`, `phone_work`) when `contact_phones` is empty.

### 3.17 CardDAV Sync (`src/niles/sync/carddav.py`)

PROPFIND for vCard URLs, vCard parsing (TEL, EMAIL, FN, N), UPSERT via UID. Supports multi-phone per contact (table `contact_phones`). Phone migration from legacy columns automatic.
APScheduler for daily sync (03:00, when `carddav_url` configured). CardDAV credentials can be configured and hot-reloaded via the web UI.

### 3.18 Calendar Sync (`src/niles/sync/`)

**CalendarSourceManager** (`manager.py`) manages calendar sources (ICS, CalDAV) via the `calendar_sources` table. CRUD operations, sync orchestration, and auto-migration from `.env` CalDAV config on first start.

**CalDAVSync** (`caldav.py`) synchronizes individual CalDAV sources via PROPFIND/REPORT. Parameterized constructor (URL, auth, timezone, source_id).

**iCalendar Parser** (`ical_parser.py`) is a shared parser for VEVENT data, used by CalDAV and ICS sync. Supports RRULE expansion for recurring events (DAILY, WEEKLY, MONTHLY, YEARLY, BYDAY, BYMONTH, EXDATE, UNTIL, COUNT). Max 500 occurrences per event. Dependency: `python-dateutil`.

**Google Calendar** is handled via per-user gws MCP server instances (see §3.22). The OAuth flow (`web/_calendar.py`) stores per-user tokens — the gws subprocess uses these for direct Google Calendar API access. Separate flow from login OAuth (different scope, different callback).

APScheduler for daily sync: CardDAV 03:00 (when `carddav_url` configured), calendar sources 03:20 (when sources exist). New calendar sources are managed via the web UI and synced automatically.

### 3.19 MCP Client (`src/niles/mcp/client.py`)

MCP server manager for external tool integrations. Configuration via `config/mcp_servers.yaml`.

**Configuration format:**

```yaml
servers:
  <name>:
    command: <executable>
    args: [<arg1>, ...]
    enabled: "${FEATURE_FLAG}"    # optional, default "true"
    env:
      KEY: "${ENV_VAR}"           # ${VAR} expands from environment
```

The `enabled` field supports environment variable expansion and defaults to `"true"`. Values like `"false"`, `"0"`, `"no"` skip the server. This mechanism controls feature-gated servers (e.g., SearXNG only starts when `FEATURE_SEARCH=true`).

**Configured servers:**

| Server | Module | Always Active | Description |
| ------ | ------ | ------------- | ----------- |
| `weather` | `niles.mcp.weather` | Yes | Open-Meteo weather data (current + forecast) |
| `fetch` | `niles.mcp.fetch` | Yes | Web page text extraction via trafilatura. SSRF protection (private IP blocklist). |
| `searxng` | `niles.mcp.search` | No (`FEATURE_SEARCH`) | SearXNG meta search (Google, Bing, DuckDuckGo, Wikipedia). Requires SearXNG Docker container. |

**Destructive tool blocking:** During tool discovery, MCP tools with destructive name prefixes are automatically blocked (delete, remove, drop, destroy, purge, erase, wipe, truncate). Case-insensitive. Blocked tools are logged but not registered. This prevents an MCP server from accidentally exposing deletion capabilities to the LLM.

### 3.20 Task Management (`src/niles/actions/tasks.py`)

Interface to the Vikunja REST API. Task tools are sent to the LLM when per-user Vikunja credentials exist (auto-provisioned on login via `vikunja_provisioning.py`). No global feature flag required.

```python
class TasksAction:
    def __init__(self, api_url: str, api_token: str): ...
    async def list_tasks(self, project="", include_done=False) -> list[dict]
    async def create_task(self, title, description="", due_date="",
                          priority=0, project="") -> dict
    async def complete_task(self, title: str) -> dict
```

- `list_tasks`: GET /tasks/all, result simplification for LLM context (max 50 tasks)
- `create_task`: PUT /projects/{id}/tasks, supports project assignment, due date, and priority (0-4)
- `complete_task`: Searches open tasks by title via `find_task()`, returns a confirmation prompt (`{"confirm": "..."}`). On user confirmation, calls `complete_task()` (POST /tasks/{id}). Error on zero or multiple matches. 5-minute TTL on pending confirmation.
- Default project ID is cached (first call triggers HTTP request)

### 3.21 Briefing (`src/niles/actions/briefing.py`, `src/niles/jobs/briefing.py`)

Automatic daily and weekly overview via WhatsApp. No LLM -- pure DB queries + template formatting.

```python
class BriefingGenerator:
    def __init__(self, pool, timezone, vikunja_store=None,
                 weather_latitude="", weather_longitude=""): ...
    async def generate_daily(self, user_id=None) -> str    # Mon-Fri: Appointments + Tasks + Weather
    async def generate_weekly(self, user_id=None) -> str   # Mon: Week by days (Mon-Fri)
```

- **Daily (Mon-Fri):** Today's appointments, overdue tasks, tasks due today, open tasks summary
- **Weekly (Mon):** Mon-Fri appointments grouped by day, open tasks compact
- **Events:** SQL SELECT from `events` table (with `calendar_sources` JOIN)
- **Tasks:** Vikunja REST API (`GET /tasks/all?filter=done=false`), optional (empty if not configured)
- **Scheduler:** APScheduler cron jobs (`briefing_daily`, `briefing_weekly`), registered when feature flag is active
- **Delivery:** Configurable via `briefing_channel` setting (`whatsapp` | `signal` | `both`). Default: `whatsapp`.
  - `whatsapp`: Via `WhatsAppAction.send_message()` to connected WhatsApp number (from `whatsapp_sessions`)
  - `signal`: Via `SignalAction.send_message()` to own Signal number (from `signal_phone_number`)
  - `both`: Send via both channels (failure on one does not block the other)
- **Settings UI:** Toggle, times, and channel configurable. At least one messenger must be connected

### 3.22 Per-User Google Calendar (`src/niles/mcp/user_pool.py`, `src/niles/google_token_store.py`)

Google Calendar access is handled via per-user **gws** (Google Workspace CLI) MCP server instances. Each user who connects their Google account gets a dedicated gws subprocess.

**GoogleTokenStore** (`google_token_store.py`) manages per-user OAuth tokens in PostgreSQL (table `user_google_tokens`):

```python
class GoogleTokenStore:
    async def upsert_tokens(self, user_id, refresh_token, access_token, token_expiry, scopes="") -> None
    async def get_tokens(self, user_id) -> dict | None
    async def has_tokens(self, user_id) -> bool
    async def delete_tokens(self, user_id) -> None
```

**UserMCPPool** (`mcp/user_pool.py`) manages the lifecycle of gws MCP server processes:

```python
class UserMCPPool:
    async def start(self) -> None         # Start cleanup timer
    async def stop(self) -> None          # Stop all instances
    async def has_google_tokens(self, user_id) -> bool
    async def disconnect_user(self, user_id) -> None  # Remove tokens + stop instance
    async def get_openai_tools(self, user_id) -> list[dict]  # Tool discovery (cached)
    def is_gws_tool(self, name) -> bool   # Check if tool name starts with mcp__gws__
    async def call_tool(self, user_id, prefixed_name, arguments) -> str
```

**Lifecycle:**

- **Lazy start:** gws subprocess starts on first tool call for a user
- **Token refresh:** Access tokens are refreshed automatically 5 min before expiry (restart subprocess)
- **Idle cleanup:** Instances are stopped after 30 min of inactivity
- **Disconnect:** `POST /api/calendar/google/disconnect` removes tokens and stops the instance

**OAuth flow:** `/ui/api/calendar/google/connect` redirects to Google OAuth with `https://www.googleapis.com/auth/calendar` scope. The callback stores tokens via `GoogleTokenStore.upsert_tokens()`. Tokens are separate from login OAuth (different scope, different callback).

---

## 4. Database Schema

All tables reside in database `evolution_db` (user `evolution`). Schema is managed by **Alembic** (see `alembic/versions/`). Migrations run automatically on container start via `scripts/start.sh`. Store `initialize()` methods contain only business logic, no `CREATE TABLE`.

### users

```sql
-- Created by UserStore (Google OAuth + Password)
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL,
    avatar_url TEXT,
    password_hash TEXT,
    auth_method TEXT NOT NULL DEFAULT 'google',
    is_admin BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW(),
    last_login TIMESTAMP DEFAULT NOW()
);
```

### whatsapp_sessions

```sql
-- Created by WhatsAppSessionStore (per-user WhatsApp instances)
CREATE TABLE IF NOT EXISTS whatsapp_sessions (
    user_id INTEGER PRIMARY KEY REFERENCES users(id),
    instance_name TEXT UNIQUE NOT NULL,
    phone_number TEXT,
    status TEXT NOT NULL DEFAULT 'disconnected'
        CHECK (status IN ('disconnected', 'connecting', 'connected')),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS whatsapp_sessions_phone_idx
ON whatsapp_sessions (phone_number);
```

### vikunja_credentials

```sql
-- Created by VikunjaCredentialStore (per-user Vikunja tokens)
CREATE TABLE IF NOT EXISTS vikunja_credentials (
    user_id INTEGER PRIMARY KEY REFERENCES users(id),
    api_token TEXT NOT NULL,
    api_url TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### carddav_sources

```sql
-- Created by Alembic migration 011 (per-user CardDAV sources)
-- CardDAV credentials moved here OUT of settings_overrides.
CREATE TABLE IF NOT EXISTS carddav_sources (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL,
    auth_user TEXT NOT NULL DEFAULT '',
    auth_password TEXT,
    last_synced TIMESTAMPTZ,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Per-user uniqueness (COALESCE not allowed in inline UNIQUE)
CREATE UNIQUE INDEX IF NOT EXISTS uq_carddav_sources_url_user
    ON carddav_sources (url, COALESCE(user_id, -1));
CREATE INDEX IF NOT EXISTS idx_carddav_sources_user_id
    ON carddav_sources (user_id);
```

### contacts

```sql
-- Created/populated by CardDAV sync. Per-user since migration 011.
CREATE TABLE contacts (
    id SERIAL PRIMARY KEY,
    full_name TEXT,
    first_name TEXT,
    last_name TEXT,
    phone_primary TEXT,   -- Legacy, replaced by contact_phones
    phone_mobile TEXT,    -- Legacy
    phone_work TEXT,      -- Legacy
    email TEXT,
    cardav_uid TEXT,
    cardav_url TEXT,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,         -- migration 011
    source_id INTEGER REFERENCES carddav_sources(id) ON DELETE CASCADE  -- migration 011
);

CREATE INDEX IF NOT EXISTS idx_contacts_user_id ON contacts (user_id);
CREATE INDEX IF NOT EXISTS idx_contacts_source_id ON contacts (source_id);
-- migration 011 replaced the global cardav_uid UNIQUE constraint with a
-- per-user unique index:
CREATE UNIQUE INDEX IF NOT EXISTS uq_contacts_cardav_uid_user
    ON contacts (cardav_uid, COALESCE(user_id, -1));
```

### contact_phones

```sql
-- Multi-phone support (1:N per contact)
CREATE TABLE IF NOT EXISTS contact_phones (
    id SERIAL PRIMARY KEY,
    contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    type TEXT NOT NULL,      -- 'mobile', 'home', 'work', 'other'
    number TEXT NOT NULL,
    UNIQUE (contact_id, type, number)
);
```

### signal_messages

```sql
-- Created by SignalMessageStore (signal_store.py)
CREATE TABLE IF NOT EXISTS signal_messages (
    id SERIAL PRIMARY KEY,
    phone TEXT NOT NULL,
    text TEXT NOT NULL,
    from_me BOOLEAN NOT NULL DEFAULT FALSE,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    chat_id TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_signal_messages_phone
ON signal_messages (phone, timestamp DESC);
```

### memory

```sql
-- Per-user since migration 012: user_id NOT NULL, composite PK (user_id, key)
CREATE TABLE IF NOT EXISTS memory (
    key TEXT NOT NULL,
    value JSONB NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,  -- migration 012
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (user_id, key)
);

CREATE INDEX IF NOT EXISTS idx_memory_updated
ON memory (updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_memory_user_id ON memory (user_id);
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
-- Created by CalendarSourceManager (sync/manager.py)
CREATE TABLE IF NOT EXISTS calendar_sources (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    source_type TEXT NOT NULL DEFAULT 'ics',   -- 'ics', 'caldav'
    writable BOOLEAN DEFAULT FALSE,
    enabled BOOLEAN DEFAULT TRUE,
    auth_user TEXT,
    auth_password TEXT,
    last_synced TIMESTAMP WITH TIME ZONE,
    last_error TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(url, source_type)
);
```

Note: Google Calendar is no longer managed via `calendar_sources`. Per-user Google tokens are stored in `user_google_tokens` (see below), and calendar operations go through the gws MCP server.

### events

```sql
-- Created in 001_baseline.py (unified definition, FK -> calendar_sources)
CREATE TABLE IF NOT EXISTS events (
    id SERIAL PRIMARY KEY,
    summary TEXT NOT NULL,
    dtstart TIMESTAMP WITH TIME ZONE NOT NULL,
    dtend TIMESTAMP WITH TIME ZONE,
    all_day BOOLEAN DEFAULT FALSE,
    description TEXT,
    location TEXT,
    transp TEXT DEFAULT 'OPAQUE',
    caldav_uid TEXT UNIQUE,
    caldav_url TEXT,
    source_id INTEGER REFERENCES calendar_sources(id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_events_dtstart ON events (dtstart);
CREATE INDEX IF NOT EXISTS idx_events_summary ON events (summary);
CREATE INDEX IF NOT EXISTS idx_events_source_id ON events (source_id);
```

`source_id` links events to their calendar source (NULL = legacy). `ON DELETE CASCADE` automatically removes all events of a source when deleted.

### settings_overrides

```sql
-- Runtime settings, editable via web UI
CREATE TABLE IF NOT EXISTS settings_overrides (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### notion_pages

```sql
CREATE TABLE IF NOT EXISTS notion_pages (
    id TEXT PRIMARY KEY,                          -- Notion page UUID
    title TEXT NOT NULL DEFAULT '',
    parent_id TEXT,                                -- Parent page/database ID
    object_type TEXT NOT NULL DEFAULT 'page',      -- 'page' or 'database'
    content_text TEXT NOT NULL DEFAULT '',          -- Markdown-formatted text (headings, lists, code)
    content_md5 TEXT,                               -- MD5 of content_text (change detection)
    url TEXT,                                       -- Notion page URL
    last_edited TIMESTAMP WITH TIME ZONE,
    synced_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    embedded_at TIMESTAMP WITH TIME ZONE           -- NULL = needs (re-)embedding
);
CREATE INDEX IF NOT EXISTS idx_notion_pages_parent ON notion_pages (parent_id);
CREATE INDEX IF NOT EXISTS idx_notion_pages_needs_embedding
    ON notion_pages (id) WHERE embedded_at IS NULL;
```

### notion_embeddings

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS notion_embeddings (
    id SERIAL PRIMARY KEY,
    page_id TEXT NOT NULL REFERENCES notion_pages(id) ON DELETE CASCADE,
    chunk_level INTEGER NOT NULL DEFAULT 1,        -- 0=summary, 1=detail
    chunk_index INTEGER NOT NULL DEFAULT 0,
    chunk_text TEXT NOT NULL,                       -- Prefixed with [Breadcrumb > # Heading] context
    embedding vector(768),                         -- nomic-embed-text-v2-moe dimension
    page_title TEXT NOT NULL DEFAULT '',            -- Breadcrumb for keyword boost
    heading_context TEXT NOT NULL DEFAULT '',       -- Heading hierarchy for keyword boost
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE (page_id, chunk_level, chunk_index)
);
CREATE INDEX IF NOT EXISTS idx_notion_embeddings_vector
    ON notion_embeddings USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
```

### user_google_tokens

```sql
-- Created by Alembic migration 004 (per-user Google OAuth for gws MCP)
CREATE TABLE IF NOT EXISTS user_google_tokens (
    user_id       INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    refresh_token TEXT NOT NULL,
    access_token  TEXT NOT NULL DEFAULT '',
    token_expiry  TIMESTAMPTZ,
    scopes        TEXT NOT NULL DEFAULT '',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

---

## 5. Security

### 5.1 Network

- **HTTPS via Caddy:** All external access through self-signed TLS certificates (`tls internal`)
- **No exposed ports:** PostgreSQL, Niles Core, and Evolution API are only reachable via Docker network
- **Security headers (Caddy + Middleware):** `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`, Server header removed
- **CSP:** `default-src 'self'; script-src 'self' https://unpkg.com https://cdn.jsdelivr.net; style-src 'self'; img-src 'self' data: https://*.googleusercontent.com; connect-src 'self'`
- **CDN resources** (htmx, marked.js, DOMPurify): SRI hashes for integrity checking

### 5.2 Authentication

**API (programmatic):**

- **API Key:** `/chat` requires `X-API-Key` header (hmac.compare_digest, max 256 characters)
- **Webhook Token:** `/webhook/whatsapp` requires `?token=` query parameter
- **Auto-generated key:** `NILES_API_KEY` is generated via `secrets.token_urlsafe(32)` if not set
- **Key is not logged:** Only hint to `docker exec niles_core printenv NILES_API_KEY`

**Web UI:**

- **Google OAuth 2.0:** Login via Google account (openid email profile)
- **Email whitelist:** `GOOGLE_ALLOWED_EMAILS` restricts access to named accounts
- **email_verified check:** Only verified Google accounts are accepted
- **API key fallback:** When Google OAuth is not configured, login with `NILES_API_KEY`
- **Signed session cookies:** `itsdangerous.URLSafeTimedSerializer` with dedicated `SESSION_SECRET`
- **CSRF:** Double-Submit Pattern (cookie + `X-CSRF-Token` header) for all POST endpoints
- **OAuth State:** CSRF protection for OAuth flow via state parameter in cookie
- **Logout:** POST (not GET) to prevent logout CSRF
- **Login rate limiting:** Max 5 attempts per IP in 5 minutes (API key login)
- **base_url config:** OAuth redirect URI from config instead of untrusted request headers

### 5.3 Rate Limiting

- In-memory rate limiter: 60 requests/minute per client IP
- `/health` and `/static` are exempt
- Memory safeguard: Max 10,000 IPs tracked, oldest are evicted
- HTTP 429 when exceeded

### 5.4 Docker

- Niles Core runs as non-root user (UID/GID 1000)
- PostgreSQL port not exposed

### 5.5 Logging

- **Application logs:** Structured JSON to stdout via structlog (`src/niles/logging_config.py`). All stdlib loggers (httpx, uvicorn, asyncpg) are routed through structlog processors for uniform JSON output. Request tracing via `request_id` (bound to structlog contextvars by `RequestIdMiddleware`).
- **Caddy access logs:** JSON-formatted to stdout (12-factor compliant, no file rotation needed)
- **Prometheus metrics:** `/metrics` endpoint (API-key protected). HTTP request count/duration, LLM request duration/tokens, tool call count, active SSE connections. See `src/niles/metrics.py`.

### 5.6 Data Integrity (No Deletions)

Niles follows the principle **"Read and create, never delete"**:

- **No LLM tool has deletion capabilities.** `complete_task` marks tasks as done (no delete). `remember` overwrites via UPSERT (no delete).
- **`MemoryStore.delete()` exists** but is NOT exposed as a tool -- only used internally by the web UI.
- **MCP tools:** Destructive name prefixes are automatically blocked (#3.19).
- **Evolution API:** Niles only uses `sendText` and `findMessages` -- no delete endpoints.
- **soul.md Rule 7:** The LLM is explicitly instructed that it cannot delete data and should refer users to the respective app for deletion requests.

| Integration | Read | Create | Modify | Delete |
| ----------- | ---- | ------ | ------ | ------ |
| WhatsApp (Evolution) | Yes | Yes (send) | No | No |
| Calendar (CalDAV) | Yes | Yes | No | No |
| Google Calendar (gws MCP) | Yes | Yes | Yes (update) | No |
| Tasks (Vikunja) | Yes | Yes | Yes (complete) | No |
| Signal (signal-cli-rest-api) | Yes | Yes (send) | No | No |
| Contacts (CardDAV) | Yes | No | No | No |
| Memory (PostgreSQL) | Yes | Yes | Yes (update) | No |
| Web Search (SearXNG) | Yes | No | No | No |
| Web Fetch | Yes | No | No | No |
| Notion (Knowledge Base) | Yes | No | No | No |

---

## 6. Configuration

### 6.1 Settings

Pydantic Settings (`src/niles/config.py`) loads values from `.env` and environment variables. `extra = "ignore"` prevents errors on unknown variables.

| Field | Default | Env Variable | Required |
| ----- | ------- | ------------ | -------- |
| `log_level` | `"INFO"` | `LOG_LEVEL` | No |
| `llm_base_url` | `"http://host.docker.internal:11434/v1"` | `LLM_BASE_URL` | No |
| `llm_model` | `"llama3.1:8b"` | `LLM_MODEL` | No |
| `llm_temperature_tools` | `0.35` | `LLM_TEMPERATURE_TOOLS` | No |
| `llm_temperature_chat` | `0.3` | `LLM_TEMPERATURE_CHAT` | No |
| `llm_max_tokens` | `4096` | `LLM_MAX_TOKENS` | No |
| `llm_timeout` | `120.0` | `LLM_TIMEOUT` | No |
| `llm_num_ctx` | `8192` | `LLM_NUM_CTX` | No |
| `mcp_max_result_tokens` | `3000` | `MCP_MAX_RESULT_TOKENS` | No |
| `langfuse_host` | `""` | `LANGFUSE_HOST` | No |
| `langfuse_public_key` | `""` | `LANGFUSE_PUBLIC_KEY` | No |
| `langfuse_secret_key` | `""` | `LANGFUSE_SECRET_KEY` | No |
| `postgres_host` | `"evolution_postgres"` | `POSTGRES_HOST` | No |
| `postgres_port` | `5432` | `POSTGRES_PORT` | No |
| `postgres_db` | `"evolution_db"` | `POSTGRES_DB` | No |
| `postgres_user` | `"evolution"` | `POSTGRES_USER` | No |
| `postgres_password` | -- | `EVOLUTION_POSTGRES_PASSWORD` | Yes |
| `evolution_api_url` | `"http://evolution_api:8080"` | `EVOLUTION_API_URL` | No |
| `evolution_api_key` | -- | `EVOLUTION_API_KEY` | Yes |
| `evolution_instance` | `"niles-whatsapp"` | `EVOLUTION_INSTANCE` | No |
| `webhook_base_url` | `"http://niles_core:8000"` | `WEBHOOK_BASE_URL` | No |
| `niles_api_key` | auto-generated | `NILES_API_KEY` | No |
| `session_secret` | auto-generated | `SESSION_SECRET` | No |
| `base_url` | `""` | `BASE_URL` | No\* |
| `timezone` | `"Europe/Vienna"` | `TIMEZONE` | No |
| `phone_country_code` | `"43"` | `PHONE_COUNTRY_CODE` | No |
| `trusted_proxy` | `""` | `TRUSTED_PROXY` | No |
| `feature_whatsapp_send_others` | `true` | `FEATURE_WHATSAPP_SEND_OTHERS` | No |
| `carddav_url` | `""` | `CARDDAV_URL` | No |
| `carddav_user` | `""` | `CARDDAV_USER` | No |
| `carddav_password` | `""` | `CARDDAV_PASSWORD` | No |
| `caldav_url` | `""` | `CALDAV_URL` | No\* |
| `caldav_user` | `""` | `CALDAV_USER` | No\* |
| `caldav_password` | `""` | `CALDAV_PASSWORD` | No\* |
| `caldav_calendars` | `""` | `CALDAV_CALENDARS` | No\* |
| `google_client_id` | `""` | `GOOGLE_CLIENT_ID` | No\*\* |
| `google_client_secret` | `""` | `GOOGLE_CLIENT_SECRET` | No\*\* |
| `google_allowed_emails` | `""` | `GOOGLE_ALLOWED_EMAILS` | No |
| `weather_latitude` | `""` | `WEATHER_LATITUDE` | No |
| `weather_longitude` | `""` | `WEATHER_LONGITUDE` | No |
| `weather_location_name` | `""` | `WEATHER_LOCATION_NAME` | No |
| `vikunja_api_url` | `""` | `VIKUNJA_API_URL` | No\*\*\* |
| `vikunja_public_url` | `""` | `VIKUNJA_PUBLIC_URL` | No |
| `signal_api_url` | `"http://signal_api:8080"` | `SIGNAL_API_URL` | No\*\*\*\* |
| `signal_phone_number` | `""` | `SIGNAL_PHONE_NUMBER` | No |
| `feature_signal_send_others` | `false` | `FEATURE_SIGNAL_SEND_OTHERS` | No |
| `feature_signal` | `false` | `FEATURE_SIGNAL` | No |
| `briefing_channel` | `"whatsapp"` | `BRIEFING_CHANNEL` | No |
| `feature_briefing_daily` | `false` | `FEATURE_BRIEFING_DAILY` | No |
| `feature_briefing_weekly` | `false` | `FEATURE_BRIEFING_WEEKLY` | No |
| `briefing_daily_time` | `"07:30"` | `BRIEFING_DAILY_TIME` | No |
| `briefing_weekly_time` | `"07:15"` | `BRIEFING_WEEKLY_TIME` | No |
| `feature_search` | `false` | `FEATURE_SEARCH` | No\*\*\*\*\* |
| `searxng_url` | `"http://searxng:8080"` | `SEARXNG_URL` | No |
| `feature_notion` | `false` | `FEATURE_NOTION` | No\*\*\*\*\*\* |
| `notion_token` | `""` | `NOTION_TOKEN` | No |
| `notion_sync_interval` | `30` | `NOTION_SYNC_INTERVAL` | No |
| `notion_embedding_model` | `"nomic-embed-text-v2-moe"` | `NOTION_EMBEDDING_MODEL` | No |
| `notion_chunk_size` | `600` | `NOTION_CHUNK_SIZE` | No |
| `notion_chunk_overlap` | `100` | `NOTION_CHUNK_OVERLAP` | No |
| `notion_similarity_threshold` | `0.3` | `NOTION_SIMILARITY_THRESHOLD` | No |
| `notion_summary_model` | `""` | `NOTION_SUMMARY_MODEL` | No |
| `notion_summary_max_input` | `4000` | `NOTION_SUMMARY_MAX_INPUT` | No |
| `notion_summary_max_tokens` | `200` | `NOTION_SUMMARY_MAX_TOKENS` | No |
| `credential_encryption_key` | `""` | `CREDENTIAL_ENCRYPTION_KEY` | Yes\*\*\*\*\*\*\* |
| `credential_encryption_optional` | `false` | `CREDENTIAL_ENCRYPTION_OPTIONAL` | No |
| `sentry_dsn` | `""` | `SENTRY_DSN` | No |
| `sentry_traces_sample_rate` | `0.1` | `SENTRY_TRACES_SAMPLE_RATE` | No |
| `history_retention_days` | `90` | `HISTORY_RETENTION_DAYS` | No |

\* `base_url` is recommended when Google OAuth is behind a reverse proxy (prevents redirect URI from untrusted headers).

\*\* Required if Google OAuth is desired. Without Google OAuth, API key login is used.

\*\*\* Required if Vikunja integration is desired. Accounts are auto-provisioned on login (no manual token needed).

\*\*\*\* Required if Signal integration is desired. Phone number is auto-discovered after QR linking.

\*\*\*\*\* Enables SearXNG web search. Requires the SearXNG Docker container (profile `search`).

\*\*\*\*\*\* Enables Notion knowledge base (RAG). Requires `notion_token` and `ollama pull nomic-embed-text-v2-moe`.

\*\*\*\*\*\*\* `credential_encryption_key` is required by default — the app refuses to start without it (set `CREDENTIAL_ENCRYPTION_OPTIONAL=true` for development).

Briefing: WhatsApp number is automatically detected (connected instance). No manual configuration needed.

\* `caldav_url/user/password` are legacy fields. On first start, they are automatically migrated into the `calendar_sources` table. New calendar sources are managed via the web UI (Settings > Calendar Sources).

`postgres_password` uses `validation_alias="EVOLUTION_POSTGRES_PASSWORD"` -- the env variable has a different name than the Python field because the existing PostgreSQL instance already expects this variable.

### 6.2 Runtime Overrides

Feature flags and selected text settings (see `EDITABLE_SETTINGS` in #3.7) can be changed via the web UI. Changes are persisted in the `settings_overrides` table and loaded on startup via `apply_overrides()`.

### 6.3 .env Template

```bash
# Required
EVOLUTION_POSTGRES_PASSWORD=<password>
EVOLUTION_API_KEY=<api-key>

# Recommended
SESSION_SECRET=<random-string>
NILES_API_KEY=<api-key>
BASE_URL=https://niles.example.ts.net

# Google OAuth (optional)
GOOGLE_CLIENT_ID=<client-id>
GOOGLE_CLIENT_SECRET=<client-secret>
GOOGLE_ALLOWED_EMAILS=user1@gmail.com,user2@gmail.com

# Vikunja (optional, accounts auto-provisioned)
VIKUNJA_JWT_SECRET=<openssl rand -hex 32>
VIKUNJA_API_URL=http://vikunja:3456/api/v1
VIKUNJA_PUBLIC_URL=https://vikunja.example.local
```

### 6.4 Environment Variables

**Required:** `EVOLUTION_POSTGRES_PASSWORD`, `EVOLUTION_API_KEY`.

**Optional:** `NILES_API_KEY`, `SESSION_SECRET`, `BASE_URL`, `WEBHOOK_BASE_URL`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_ALLOWED_EMAILS`, `CARDDAV_URL`, `CARDDAV_USER`, `CARDDAV_PASSWORD`, `CALDAV_URL`, `CALDAV_USER`, `CALDAV_PASSWORD`, `CALDAV_CALENDARS` (legacy, auto-migrated into DB), `VIKUNJA_API_URL`, `VIKUNJA_PUBLIC_URL`, `VIKUNJA_JWT_SECRET` (Docker only), `SIGNAL_API_URL`, `SIGNAL_PHONE_NUMBER`, `FEATURE_SIGNAL_SEND_OTHERS`, `BRIEFING_CHANNEL`, `FEATURE_BRIEFING_DAILY`, `FEATURE_BRIEFING_WEEKLY`, `BRIEFING_DAILY_TIME`, `BRIEFING_WEEKLY_TIME`, `LOG_LEVEL`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_TEMPERATURE_TOOLS`, `LLM_TEMPERATURE_CHAT`, `LLM_MAX_TOKENS`, `LANGFUSE_HOST`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `TIMEZONE`, `WEATHER_LATITUDE`, `WEATHER_LONGITUDE`, `WEATHER_LOCATION_NAME`, `EVOLUTION_API_URL`, `EVOLUTION_INSTANCE`, `FEATURE_WHATSAPP_SEND_OTHERS`, `FEATURE_SEARCH`, `SEARXNG_URL`, `SEARXNG_SECRET_KEY`, `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_HOST_PORT` (Docker debugging), `CADDY_HOSTS_443`, `CADDY_HOSTS_8443`, `CADDY_HOSTS_3457` (Caddy reverse proxy hostnames).

See `.env.example` for complete documentation.

---

## 7. Docker

### 7.1 Dockerfile (`docker/Dockerfile.niles`)

Multi-stage build (Builder → gws-downloader → Runtime):

- **Builder stage:** Installs uv, runs `uv sync --frozen --no-dev` for dependency caching, builds Tailwind CSS with SHA256-verified CLI
- **gws-downloader stage:** Fetches the gws (Google Workspace CLI) binary with SHA256 verification
- **Runtime stage:** Base image pinned with SHA256 digest (`python:3.14-slim@sha256:...`), copies virtualenv + built assets, non-root user (`niles:1000`), HEALTHCHECK on `/health`

**Key design decisions:**

- `uv sync --frozen` replaces `pip install` for reproducible builds (lockfile-based)
- Dependencies are installed before copying source code. This keeps the dependency layer cached when only source code changes.
- `entrypoint.sh` runs Alembic migrations (`python -m niles.migrate`) before starting uvicorn. Port is configurable via `${PORT:-8000}`.
- Resource limits (`deploy.resources.limits`: 1 CPU, 512 MB) configured in `docker-compose.yml`
- Named volumes for all persistent data (PostgreSQL, WhatsApp sessions, Signal config, etc.)

### 7.2 Docker Compose Services

| Container | Image | Network | Purpose |
| --------- | ----- | ------- | ------- |
| `niles_core` | `niles-core:${NILES_VERSION:-latest}` (Dockerfile.niles) | niles_network, proxy | Python backend + web UI |
| `niles_evolution_postgres` | `pgvector/pgvector:pg15` | niles_network | PostgreSQL (pgvector for Notion RAG) |
| `niles_evolution_api` | `evoapicloud/evolution-api:v2.3.7` | niles_network, proxy | WhatsApp gateway |
| `vikunja` | `vikunja/vikunja:1.1.0` | niles_network, proxy | Todo/task management |
| `niles_signal_api` | `bbernhard/signal-cli-rest-api:1771797934-ci` | niles_network | Signal gateway (signal-cli v0.13.24) |
| `niles_searxng` | `searxng/searxng:2025.5.10-1b787ed35` | niles_network | Meta search engine (profile `search`) |
| `niles_langfuse` | `langfuse/langfuse:3` | niles_network | LLM tracing (opt-in, profile `langfuse`) |

HTTPS termination is handled by `gateway-caddy` in the separate [homelab-gateway](../../homelab-gateway) repo.

### 7.3 Network

All containers on bridge network `niles_network` (internal) + `proxy` (external, for gateway routing). Container names serve as hostnames for internal communication:

- `niles_core` -> `evolution_postgres:5432`
- `niles_core` -> `evolution_api:8080` (only for WhatsApp sending)
- `evolution_api` -> `niles_core:8000` (webhook)
- `niles_core` -> `vikunja:3456` (task management API)
- `niles_core` -> `signal_api:8080` (Signal messaging, optional)
- `niles_core` -> `searxng:8080` (SearXNG search, optional, via MCP)
- `niles_core` -> `host.docker.internal:11434` (Ollama on host)

### 7.4 Volumes

| Volume | Mount | Purpose |
| ------ | ----- | ------- |
| `evolution_postgres` | `/var/lib/postgresql/data` | PostgreSQL data |
| `vikunja_files` | `/app/vikunja/files` | Vikunja files |
| `caddy_data` | `/data` | TLS certificates |
| `caddy_config` | `/config` | Caddy configuration |
| `~/.evolution/instances` | `/evolution/instances` | WhatsApp sessions |
| `signal_cli_config` | `/home/.local/share/signal-cli` | Signal account data |
| `searxng_data` | `/etc/searxng` | SearXNG configuration |
| `../config` | `/app/config:ro` | Agent configuration |

---

## 8. Technology Stack & Dependencies

| Component | Technology | Version |
| --------- | ---------- | ------- |
| Runtime | Python | >= 3.14 |
| Web Framework | FastAPI | >= 0.129.0 |
| ASGI Server | uvicorn | >= 0.41.0 |
| HTTP Client | httpx | >= 0.28.1 |
| PostgreSQL Driver | asyncpg | >= 0.31.0 |
| LLM Client | openai (Python SDK) | >= 2.21.0 |
| Config | pydantic-settings | >= 2.13.0 |
| Templates | Jinja2 | >= 3.1.0 |
| Session Signing | itsdangerous | >= 2.0 |
| CSS Framework | Tailwind CSS | v3.4.17 (standalone CLI) |
| Markdown Rendering | marked.js + DOMPurify | CDN (SRI) |
| Frontend Interaction | htmx | 2.0.4 (CDN) |
| RRULE Expansion | python-dateutil | >= 2.8.0 |
| Structured Logging | structlog | >= 24.1.0 |
| Metrics | prometheus-client | >= 0.21.0 |
| Scheduling | APScheduler | >= 3.11.2 |
| Container | Docker Compose | -- |
| LLM Inference | Ollama (native on host) | local |
| WebSocket Client | websockets | >= 14.0 |
| WhatsApp Gateway | Evolution API | v2.3.7 |
| Signal Gateway | signal-cli-rest-api | 1771797934-ci (signal-cli v0.13.24) |
| HTML Extraction | trafilatura | >= 2.0.0 |
| Search MCP | niles.mcp.search (built-in) | — |
| Search Engine | SearXNG | 2025.5.10-1b787ed35 (Docker) |

### pyproject.toml Dependencies

```toml
fastapi>=0.129.0          # Web Framework
uvicorn[standard]>=0.41.0 # ASGI Server
httpx>=0.28.1             # Async HTTP Client (+ Google OAuth)
asyncpg>=0.31.0           # PostgreSQL (async)
alembic>=1.13.0           # Database migrations
sqlalchemy>=2.0.0         # ORM (Alembic dependency)
psycopg2-binary>=2.9.0    # PostgreSQL (sync, for Alembic)
openai>=2.21.0            # LLM Client (OpenAI-compatible)
mcp>=1.26.0               # MCP SDK
pydantic-settings>=2.13.0 # Config Management
pyyaml>=6.0.3             # YAML Parsing
apscheduler>=3.11.2       # Scheduling (CardDAV/CalDAV Sync)
jinja2>=3.1.0             # HTML Templates (Web UI)
aiofiles>=24.0.0          # Static File Serving
itsdangerous>=2.0         # Signed Session Cookies
argon2-cffi>=25.1.0       # Password hashing (Argon2id)
python-dateutil>=2.8.0    # RRULE Expansion (recurring calendar events)
structlog>=24.1.0         # Structured JSON Logging
prometheus-client>=0.21.0 # Prometheus Metrics
websockets>=14.0          # Signal WebSocket listener
trafilatura>=2.0.0        # HTML text extraction (Web Fetch MCP)
# MCP Web Search is built-in (src/niles/mcp/search)
json-repair>=0.58.0       # Robust JSON repair for malformed LLM tool-call output
```

Dev: `pytest>=9.0.0`, `pytest-asyncio>=1.3.0`, `httpx` (TestClient).

---

## 9. Notes

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

## 10. Further Documentation

- [API Reference](API.md) -- Endpoints, payloads, examples
- [Development Guide](Development.md) -- Setup, testing, conventions
