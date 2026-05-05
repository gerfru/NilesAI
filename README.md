# Niles AI Core

A local, privacy-first AI butler running on a Mac Mini. Niles connects to WhatsApp, calendars, contacts, and task managers -- all processed by a local LLM with zero cloud dependencies for core functionality.

**Key principles:** 100% local inference, privacy first, extensible via MCP.

## Features

- **WhatsApp Integration** -- Self-chat via "Hey Niles" trigger, message history, contact lookup.
- **Calendar** -- Multi-source sync (CalDAV, Google Calendar, ICS), event search and creation.
- **Tasks** -- Vikunja integration (list, create, complete), auto-provisioned per-user accounts.
- **Contacts** -- CardDAV sync with multi-phone support.
- **Memory** -- Persistent key-value store, injected into every conversation.
- **Knowledge Base** -- Notion RAG integration with semantic search (pgvector embeddings, local Ollama). See [RAG Architecture](docs/RAG.md).
- **Web Search** -- SearXNG meta search (Google, Bing, DuckDuckGo), privacy-first, self-hosted.
- **Web Fetch** -- Extract and summarize web page content (trafilatura, SSRF-protected).
- **Briefings** -- Automated daily/weekly summaries via WhatsApp (no LLM, template-based).
- **Web UI** -- Chat with SSE streaming, settings dashboard, calendar/contact management.
- **MCP** -- Extend Niles with community tools via Model Context Protocol.
- **Multi-User** -- Google OAuth login, per-user WhatsApp sessions and task lists.
- **Security** -- HTTPS (homelab-gateway), rate limiting, CSRF protection, no-delete policy.

## Architecture

```text
Browser / curl / WhatsApp
    |
    v  HTTPS (homelab-gateway)
+-------------------------------------------------------------+
|  Niles Core (FastAPI :8000)                                 |
|                                                             |
|  /ui/*  ---- sources/web/ (htmx + Jinja2 + SSE)              |
|                 |  Google OAuth / API-Key Auth              |
|                 v                                           |
|  /chat  ---> agent/core.py (NilesAgent) --------> Ollama    |
|                 |  Tool-Call Loop (max 5)           :11434  |
|                 |                                           |
|                 +-- actions/contacts.py ----> PostgreSQL    |
|                 +-- actions/whatsapp.py ----> Evolution API |
|                 +-- actions/signal.py -----> signal-cli API |
|                 +-- actions/calendar.py ----> PostgreSQL    |
|                 +-- actions/tasks.py -------> Vikunja       |
|                 +-- actions/notion.py -----> pgvector (RAG) |
|                 +-- memory/store.py -------> PostgreSQL     |
|                 +-- mcp/client.py ---------> MCP Servers    |
|                                                             |
|  /webhook/whatsapp --- sources/whatsapp.py                  |
|                                                             |
|  jobs/briefing.py --- APScheduler (Mo-Fr 07:30, Mo 07:15)   |
+-------------------------------------------------------------+
```

## Quick Start

**Prerequisites:** Docker Desktop, Ollama (native on host), Python >= 3.11

```bash
# 1. Clone and configure
git clone <repo-url> Niles && cd Niles
cp .env.example .env
# Set: EVOLUTION_POSTGRES_PASSWORD, EVOLUTION_API_KEY

# 2. Pull the LLM model
ollama pull llama3.1:8b

# 3. Start all services
./scripts/start.sh

# 4. Open Web UI
# https://localhost/ui/login
```

For detailed setup including Google OAuth, WhatsApp, Vikunja, CalDAV, and Tailscale: see the [Deployment Guide](docs/Deployment.md).

## Project Structure

```text
Niles/
src/niles/                     Python Backend
  main.py                      FastAPI + Lifespan + Middleware
  config.py                    Pydantic Settings
  agent/                       LLM Agent (core, context, text_tool_parser), Prompts
    tools/                     Tool handler modules (registry-based)
  memory/                      Key-Value Store, Conversation History
  actions/                     12 action modules (Routes → Actions → Stores)
  jobs/                        Scheduled Jobs (Briefing)
  sources/                     Webhook Handler, Web UI (13 feature modules)
  sync/                        CardDAV, CalDAV, Notion, iCal Parser, Embeddings
  mcp/                         MCP Server Manager, Weather + Fetch servers
  *_store.py                   7 data stores (asyncpg, per-user credentials)
  templates/                   Jinja2 Templates (Tailwind CSS)
  static/                      CSS, JavaScript
alembic/                       Database migrations (7 versions)
tests/                         914 tests across 45 files (pytest + pytest-asyncio)
config/                        soul.md (Agent Personality)
docker/                        Dockerfile, docker-compose.yml
scripts/                       start, stop, status, dev, test, backup
docs/                          Technical Documentation
```

## Stack

| Component      | Technology                                  |
| -------------- | ------------------------------------------- |
| Backend        | FastAPI (Python 3.12)                       |
| Web UI         | Jinja2 + htmx + Tailwind CSS + SSE         |
| LLM            | Ollama (local, llama3.1:8b)                 |
| Embeddings     | nomic-embed-text-v2-moe (Ollama)            |
| Database       | PostgreSQL 15 + pgvector                    |
| WhatsApp       | Evolution API v2.3.7                        |
| Signal         | signal-cli-rest-api (signal-cli v0.13.24)   |
| Tasks          | Vikunja 1.1.0                               |
| Knowledge Base | Notion API + pgvector RAG                   |
| Reverse Proxy  | homelab-gateway (Caddy + CoreDNS)           |
| Logging        | structlog (JSON to stdout)                  |
| Metrics        | Prometheus (prometheus-client)              |
| Scheduling     | APScheduler                                 |
| Web Search     | SearXNG (self-hosted, optional)             |
| Web Fetch      | trafilatura (HTML text extraction)          |
| Extensions     | MCP (Model Context Protocol)                |

## Agent Tools

The LLM can invoke these tools during conversations:

| Tool                    | Description                              |
| ----------------------- | ---------------------------------------- |
| `find_contact`          | Search contacts by name                  |
| `send_whatsapp`         | Send WhatsApp message (by name or number) |
| `get_whatsapp_messages` | Read chat history (last 30 days)         |
| `find_event`            | Search calendar events                   |
| `create_event`          | Create calendar event                    |
| `list_tasks`            | List open tasks from Vikunja             |
| `create_task`           | Create a new task                        |
| `complete_task`         | Mark a task as done                      |
| `remember` / `recall`   | Persistent key-value memory              |
| `send_signal`           | Send Signal message (by name or number)  |
| `get_signal_messages`   | Read Signal chat history (last 30 days)  |
| `mcp__fetch__fetch_url` | Fetch and extract text from a web page   |
| `mcp__searxng__search`  | Web search via SearXNG (when enabled)    |
| `search_notion`         | Semantic search over Notion knowledge base |
| `mcp__weather__*`       | Weather data (current + forecast)        |

Additional MCP tools from external servers are automatically discovered and added.

## Development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest tests/ -v
```

See [Development Guide](docs/Development.md) for details on testing, Docker workflow, and conventions.

## Documentation

- [Deployment Guide](docs/Deployment.md) -- Setup, configuration, backup, troubleshooting
- [API Reference](docs/API.md) -- Endpoints, payloads, agent tools
- [Development Guide](docs/Development.md) -- Testing, Docker, conventions
- [Technical Spec](docs/Niles-Core-Spec.md) -- Architecture, components, roadmap
- [RAG Architecture](docs/RAG.md) -- Notion knowledge base, embeddings, retrieval
- [Quality Assessment](docs/Quality-Assessment.md) -- Codebase quality scores and metrics
- [Legal](docs/LEGAL.md) -- Licenses, legal notices
