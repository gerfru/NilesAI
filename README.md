<div align="center">

# Niles AI

**Your AI butler. Your server. Your data.**

A privacy-first, self-hosted AI assistant that connects WhatsApp, Signal, calendars,
contacts, and tasks — powered entirely by a local LLM with zero cloud dependencies.

![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.14-3776AB?style=flat-square&logo=python&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-pgvector-4169E1?style=flat-square&logo=postgresql&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=flat-square&logo=docker&logoColor=white)
![Ollama](https://img.shields.io/badge/Ollama-Local%20LLM-000000?style=flat-square)
![Self-hosted](https://img.shields.io/badge/Self--hosted-Privacy--first-10B981?style=flat-square)

[Quickstart](#quickstart) · [Features](#whats-inside) · [Docs](#documentation) · [Security](#security-at-a-glance)

</div>

---

> *Your messages live on someone else's server.*
> *Your calendar, your contacts, your tasks — accessible through APIs you don't control,
> processed by models you can't audit.*

**Niles takes it back.**

One `./scripts/start.sh`, and you have a personal AI assistant running on **your** hardware —
with WhatsApp and Signal integration, calendar management, task tracking, and a Notion-powered
knowledge base. All processed by a local LLM. No cloud. No subscription. No data leaving your network.

> **Self-hosted by design.** Niles runs entirely on hardware you control. LLM inference happens
> locally via Ollama, per-user credentials are Fernet-encrypted at rest, and your data never
> leaves your server.

---

## Why Niles

- **Privacy by architecture, not by promise** — 100% local LLM inference via Ollama. No cloud API calls, no telemetry, no data broker.
- **Talk to it like a person** — "Hey Niles, was steht morgen an?" via WhatsApp self-chat, Signal, or the web UI. Natural language in, tool calls under the hood.
- **Connects your world** — Calendar (CalDAV + Google), contacts (CardDAV), tasks (Vikunja), knowledge base (Notion + pgvector RAG), web search (SearXNG), weather — one assistant for everything.
- **Extensible via MCP** — Add community tools via Model Context Protocol. Destructive operations are automatically blocked.
- **Multi-user from day one** — Google OAuth, per-user WhatsApp sessions, per-user task lists, per-user Google Calendar.
- **One command to run it** — Docker Compose, auto-provisioned accounts, automated briefings. No manual wiring.

---

## What's inside

### Messaging

- WhatsApp self-chat via "Hey Niles" trigger (Evolution API, per-user instances)
- Signal integration as linked device (signal-cli-rest-api, WebSocket listener)
- Automated daily/weekly briefings via WhatsApp, Signal, or both (no LLM, template-based)

### Intelligence

- Local LLM agent with tool-call loop (Ollama, llama3.1:8b default, max 5 rounds)
- Notion RAG knowledge base: sync, chunk, embed, pgvector search (nomic-embed-text-v2-moe)
- Web search (SearXNG meta search) + web page extraction (trafilatura, SSRF-protected)
- Persistent key-value memory injected into every conversation

### Productivity

- Multi-source calendar sync (CalDAV, Google Calendar via MCP, ICS) with event search and creation
- Task management via Vikunja (list, create, complete) with auto-provisioned per-user accounts
- Contact sync via CardDAV with multi-phone support

### Web UI

- Chat with SSE streaming, markdown rendering (marked.js + DOMPurify)
- Settings dashboard, calendar/contact/WhatsApp/Signal management
- Dark mode, WCAG accessibility (labels, ARIA, skip-link, focus-visible)

---

## Quickstart

**Prerequisites:** Docker Desktop, Ollama (native on host), Python >= 3.14

```bash
# 1. Clone and configure
git clone <repo-url> Niles && cd Niles
cp .env.example .env
# Set: EVOLUTION_POSTGRES_PASSWORD, EVOLUTION_API_KEY, CREDENTIAL_ENCRYPTION_KEY

# 2. Pull the LLM model
ollama pull llama3.1:8b

# 3. Start homelab-gateway (HTTPS reverse proxy)
# See: https://github.com/gerfru/homelab-gateway

# 4. Start all services
./scripts/start.sh

# 5. Open Web UI
# https://niles.example.local/ui/login
```

> Full walkthrough: **[docs/Deployment.md](docs/Deployment.md)**

---

## Documentation

| | |
|---|---|
| **[Deployment Guide](docs/Deployment.md)** | Complete setup: Ollama, OAuth, WhatsApp, Signal, CalDAV, Vikunja, Notion, Tailscale |
| **[API Reference](docs/API.md)** | Every endpoint, auth methods, webhook configuration, request tracing |
| **[Development Guide](docs/Development.md)** | Local dev, testing, Docker workflow, conventions |
| **[Technical Spec](docs/Niles-Core-Spec.md)** | Architecture, components, database schema, configuration reference |
| **[RAG Architecture](docs/RAG.md)** | Notion knowledge base: pipeline, chunking, embedding, retrieval |
| **[LLM Evaluation](docs/LLM-Evaluation.md)** | Model comparison (llama3.1:8b vs mistral:7b), Claude-as-Judge framework |
| **[Quality Assessment](docs/Quality-Assessment.md)** | Codebase quality scores across 10 dimensions |
| **[Legal](docs/LEGAL.md)** | Third-party licenses, WhatsApp risk disclosure, GDPR, EU AI Act |

---

## Security at a glance

Self-hosting your AI butler only helps if the app itself is hard to break into. Niles ships
with Argon2id password hashing, rate-limited auth, CSRF protection (double-submit), signed
httpOnly session cookies (`SameSite=Lax`), Fernet-encrypted per-user credentials, parameterized
queries (asyncpg), a strict nonce-based CSP (`'strict-dynamic'`), and SAST/SCA/container scanning
in CI (bandit, semgrep, pip-audit, Trivy, gitleaks, detect-secrets).

> Vulnerability reports and threat model: **[SECURITY.md](SECURITY.md)**

---

## Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI (Python 3.14) · uvicorn |
| Web UI | Jinja2 · htmx · Tailwind CSS · SSE |
| LLM | Ollama (local, llama3.1:8b) |
| Embeddings | nomic-embed-text-v2-moe (Ollama, 768d) |
| Database | PostgreSQL 15 · pgvector · Alembic |
| WhatsApp | Evolution API v2.3.7 |
| Signal | signal-cli-rest-api (v0.13.24) |
| Tasks | Vikunja 1.1.0 |
| Knowledge Base | Notion API · pgvector RAG |
| Web Search | SearXNG (self-hosted, optional) |
| Reverse Proxy | homelab-gateway (Caddy · CoreDNS) |
| Extensions | MCP (Model Context Protocol) |

---

## Agent Tools

The LLM can invoke these tools during conversations:

| Tool | Description |
|------|-------------|
| `find_contact` | Search contacts by name (multi-phone support) |
| `send_whatsapp` | Send WhatsApp message (by name or number, per-user instance) |
| `get_whatsapp_messages` | Read WhatsApp chat history (last 30 days) |
| `send_signal` | Send Signal message (by name or number) |
| `get_signal_messages` | Read Signal chat history (last 30 days) |
| `find_event` | Search calendar events (CalDAV + ICS sources) |
| `create_event` | Create calendar event on writable source |
| `list_tasks` / `create_task` / `complete_task` | Vikunja task management |
| `remember` / `recall` | Persistent key-value memory |
| `search_notion` | Semantic search over Notion knowledge base (pgvector) |
| `mcp__fetch__fetch_url` | Fetch and extract text from web pages (SSRF-protected) |
| `mcp__searxng__web_search` | Web search via SearXNG (when enabled) |
| `mcp__weather__*` | Weather data (current + forecast, Open-Meteo) |
| `mcp__gws__*` | Google Calendar (per-user OAuth, when connected) |

Additional MCP tools from external servers are automatically discovered.

---

## Development

```bash
# Install dependencies (requires uv: https://docs.astral.sh/uv/)
uv sync --frozen --extra dev

# Run tests
uv run pytest tests/ -v

# Run pre-commit hooks
pre-commit run --all-files
```

> **[Development Guide](docs/Development.md)** — testing, Docker workflow, conventions

---

## License

[AGPL-3.0-only](LICENSE) — see [LEGAL.md](docs/LEGAL.md) for third-party licenses and obligations.

---

<div align="center">
<sub>Built for people who'd rather own their data than rent it back.</sub>
</div>
