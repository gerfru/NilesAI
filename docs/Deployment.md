# Niles AI -- Deployment Guide

> **Updated:** 2026-03-09

This guide describes the complete setup of Niles AI -- from a blank machine to a running system.

For technical details on architecture and development, see [Development.md](Development.md).

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Quick Start](#2-quick-start)
3. [Ollama (LLM Backend)](#3-ollama-llm-backend)
4. [Google OAuth (Web UI Login)](#4-google-oauth-web-ui-login)
5. [WhatsApp (Evolution API)](#5-whatsapp-evolution-api)
6. [Signal (signal-cli-rest-api)](#6-signal-signal-cli-rest-api)
7. [Contacts (CardDAV)](#7-contacts-carddav)
8. [Calendar (CalDAV + Google Calendar)](#8-calendar-caldav--google-calendar)
9. [Tasks (Vikunja)](#9-tasks-vikunja)
10. [Briefing (Daily/Weekly)](#10-briefing-dailyweekly)
11. [Web Search & Fetch](#11-web-search--fetch)
12. [Notion (Knowledge Base)](#12-notion-knowledge-base)
13. [HTTPS & Remote Access (Tailscale + Caddy)](#13-https--remote-access-tailscale--caddy)
14. [Backup & Maintenance](#14-backup--maintenance)
15. [Troubleshooting](#15-troubleshooting)
16. [Reference](#16-reference)

---

## 1. Prerequisites

### Hardware

- Mac Mini (Apple Silicon recommended for local LLM inference)
- At least 8 GB RAM (16 GB recommended)
- At least 20 GB free storage

### Software

| Software | Version | Purpose |
| -------- | ------- | ------- |
| Docker Desktop | current | Container runtime (PostgreSQL, Evolution API, Caddy, Vikunja) |
| Ollama | >= 0.13 | Local LLM inference (GPU accelerated) |
| Git | current | Clone repository |
| Tailscale | optional | Secure remote access from anywhere |

### Accounts (optional, depending on desired features)

| Account | Purpose |
| ------- | ------- |
| Google Cloud | OAuth login for web UI + Google Calendar (via gws MCP) |
| CardDAV provider (e.g., mailbox.org) | Contact sync |
| CalDAV provider (e.g., mailbox.org) | Calendar sync |

---

## 2. Quick Start

### Clone Repository

```bash
git clone <repo-url> Niles
cd Niles
```

### Create .env

```bash
cp .env.example .env
```

Set the two **required variables**:

```bash
# Freely chosen -- set as DB password on first start
EVOLUTION_POSTGRES_PASSWORD=a-secure-password

# Freely chosen -- authenticates Niles against Evolution API
EVOLUTION_API_KEY=a-secure-api-key
```

### Start

```bash
./scripts/start.sh
```

The script:
1. Checks if Docker is running
2. Builds the Niles Core image
3. Starts all containers (PostgreSQL, Evolution API, Vikunja, Caddy, Niles Core)
4. Applies database migrations automatically (Alembic)
5. Automatically creates the `vikunja_db` database
6. Outputs the service URLs

### Health Check

```bash
curl -sk https://localhost/health
# Expected response: {"status":"ok"}
```

Web UI: `https://localhost/ui/login` (self-signed certificate -- accept browser warning)

---

## 3. Ollama (LLM Backend)

Ollama runs **natively on the host** (not in Docker) to utilize full GPU performance. See [Ollama documentation](https://docs.ollama.com/) for details.

### Installation

```bash
brew install ollama
```

### Load Model

```bash
ollama pull llama3.1:8b
```

Ollama starts automatically and listens on port `11434`.

### Verification

```bash
curl http://localhost:11434/v1/models
```

### Configuration

The default values in `.env` work for most setups:

```bash
# Only change if a different model or host is desired
#LLM_BASE_URL=http://host.docker.internal:11434/v1
#LLM_MODEL=llama3.1:8b
```

`host.docker.internal` is Docker's internal address for the host system -- this is how Niles Core (in the container) reaches the Ollama server (on the host).

---

## 4. Google OAuth (Web UI Login)

Without Google OAuth, the web UI is only accessible via API key. With Google OAuth, users can conveniently log in via Google.

> Official guides: [OAuth 2.0 for Web Server Applications](https://developers.google.com/identity/protocols/oauth2/web-server) | [Configure OAuth Consent](https://developers.google.com/workspace/guides/configure-oauth-consent)

### Step 1: Google Cloud Project

1. Open [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (e.g., "Niles AI")
3. **Enable APIs** -- Go to **APIs & Services > Library** and enable:
   - **Google Calendar API** ([docs](https://developers.google.com/workspace/calendar/api/guides/overview))
4. Configure **APIs & Services > OAuth consent screen**:
   - User Type: External
   - App name: "Niles AI"
   - Scopes: `email`, `profile`, `openid`
   - For Google Calendar additionally: `https://www.googleapis.com/auth/calendar` (full read/write access)
   - Add yourself as **test user** (required while the app is in "Testing" publishing status)

### Step 2: Create OAuth Client

1. **APIs & Services > Credentials > Create Credentials > OAuth client ID**
2. Application type: **Web application**
3. Name: "Niles"
4. **Authorized redirect URIs** -- add both on the **same** client:

```
https://<YOUR-URL>/ui/callback/google
https://<YOUR-URL>/ui/callback/google/calendar
```

Examples:
- Local: `https://localhost/ui/callback/google`
- Tailscale: `https://niles.example.ts.net/ui/callback/google`

> **Important:** Use a single OAuth client for both login and calendar. Both redirect URIs must be on the same client that matches `GOOGLE_CLIENT_ID` in `.env`.

### Step 3: Configure .env

```bash
GOOGLE_CLIENT_ID=123456789-abc.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-xxxxxxxxxxxx

# Comma-separated whitelist (empty = all Google accounts allowed)
GOOGLE_ALLOWED_EMAILS=user@gmail.com

# Must be set when behind a reverse proxy
BASE_URL=https://niles.example.ts.net
```

### Step 4: Restart & Test

```bash
./scripts/start.sh
```

Open `https://<YOUR-URL>/ui/login` -- the Google login button should appear.

> **Note:** While your app is in "Testing" mode (not verified by Google), you will see a warning page: "Google has not verified this app". Click **Continue** to proceed. This is normal for personal/private apps and only visible to test users. Verification is only required for apps used by external users.

---

## 5. WhatsApp (Evolution API)

> [Evolution API documentation](https://doc.evolution-api.com/)

### How It Works

- Niles uses the **Evolution API** for WhatsApp integration
- Each user gets their own WhatsApp instance (`niles-wa-<user-id>`)
- WhatsApp sessions are persisted in `~/.evolution/instances/`
- Webhooks are configured automatically

### Connecting

1. Log in to the web UI: `https://localhost/ui/login`
2. Open **Settings**
3. In the "WhatsApp" section, click **Connect**
4. **Scan the QR code with WhatsApp** (Phone > Linked Devices > Link a Device)
5. Status changes to "Connected"

### Self-Chat ("Hey Niles")

Niles can be addressed directly in your own WhatsApp chat -- without a second person involved.

**How it works:**

1. In your own WhatsApp chat (message to yourself), write a message starting with a trigger:
   - `Hey Niles, what's on tomorrow?`
   - `Hi Niles, remind me about the appointment`
   - `Hello Niles!`
   - `Niles appointment tomorrow`
2. Niles recognizes the trigger, processes the message, and replies directly in the same chat
3. Messages without a trigger (e.g., a normal shopping list) are ignored

**Behavior by channel:**

| Channel | Processing | Auto-reply |
| ------- | ---------- | ---------- |
| Self-chat with trigger | yes | yes (always) |
| Self-chat without trigger | no | no |
| Incoming (other people) | yes (stored by Evolution API) | no (never) |
| Web UI | yes | yes (streaming) |

**Web UI WhatsApp log:** At `/ui/chat?channel=whatsapp`, the self-chat history is viewable as a read-only log. The tab appears automatically once a WhatsApp connection exists.

### Evolution API Manager

The Evolution API has its own web interface:

```
https://localhost:8443/manager
```

Login with the `EVOLUTION_API_KEY` from `.env`.

### Troubleshooting

| Problem | Solution |
| ------- | -------- |
| QR code doesn't appear | Restart container: `docker restart niles_evolution_api` |
| Session lost | Reconnect via Settings > WhatsApp > Connect |
| Messages not arriving | Check webhook: `./scripts/status.sh` |
| Messages missing (LID) | WhatsApp uses LID addresses since 2025. Niles supports this automatically (PR #29). If messages are missing after an update: check `DATABASE_SAVE_DATA_NEW_MESSAGE=true` in Evolution API. |

---

## 6. Signal (signal-cli-rest-api)

> [signal-cli-rest-api documentation](https://github.com/bbernhard/signal-cli-rest-api)

### How It Works

- Niles uses **signal-cli-rest-api** as a Docker container for Signal integration
- Signal runs as a **Linked Device** to your existing Signal account (like Signal Desktop)
- Messages are received via WebSocket, sent via REST API
- Signal is single-instance: one phone number for the entire deployment
- Message history is stored locally in PostgreSQL (signal-cli has no message query API)

### Third-Party License Notice

Signal integration uses the following third-party components:

- **signal-cli** (GPLv3) -- [Source code](https://github.com/AsamK/signal-cli)
- **signal-cli-rest-api** (MIT) -- [Source code](https://github.com/bbernhard/signal-cli-rest-api)
- **GPLv3 License** -- [Full text](https://www.gnu.org/licenses/gpl-3.0.html)

The `docker-compose.yml` includes signal-cli-rest-api which bundles signal-cli (GPLv3). No modifications are made to signal-cli or signal-cli-rest-api.

> **Note:** This is an unofficial integration. Signal availability is not guaranteed by an SLA.

### Setup

#### 1. Link Signal Account

1. In Settings, click **Signal verbinden** (Connect Signal)
2. Scan the QR code with your Signal app (Settings > Linked Devices > Link New Device)
3. Status changes to "Connected" with your phone number
4. Phone number is auto-discovered -- no manual configuration needed

### Self-Chat ("Hey Niles")

> **Known Limitation:** Self-chat via "Note to Self" does **not work** due to an upstream signal-cli bug ([#1930](https://github.com/AsamK/signal-cli/issues/1930)). As a linked device, signal-cli cannot parse SyncMessage envelopes for Note-to-Self -- the message text is lost. This affects all signal-cli versions up to and including v0.13.24. A fix has been committed to the [Turasa/libsignal-service-java](https://github.com/AsamK/signal-cli/issues/1930) fork but is not yet included in a release. Once a fixed signal-cli version is available, update the Docker image tag in `docker-compose.yml`.

Messages from **other Signal users** are stored in the local database. Niles does **not** auto-reply to incoming Signal messages -- the agent only responds when explicitly triggered via self-chat. Stored messages can be retrieved by the agent via `get_signal_messages` when the user asks about them.

### Troubleshooting

| Problem | Solution |
| ------- | -------- |
| Signal card not visible | Signal activates automatically when `signal_api_url` is configured |
| QR code not loading | Check if signal_api container is running: `docker ps` |
| QR code disappears quickly | Normal during linking -- keep the Settings page open until status changes to "Connected" |
| Connection lost | Re-link via Settings > Signal > Connect |
| Messages not arriving | Check WebSocket listener in logs: `docker logs niles_core` |

---

## 7. Contacts (CardDAV)

Contacts are synchronized via CardDAV (e.g., from mailbox.org, Nextcloud, iCloud).

### Configuration via .env

```bash
CARDDAV_USER=your-username
CARDDAV_PASSWORD=your-password
FEATURE_CARDDAV_SYNC=true
```

Alternatively via the web UI: **Settings > Contacts**.

### Sync Schedule

- Automatic sync: daily at 03:00 UTC
- Manual sync: Settings > Contacts > **Sync Now**

### Default URL

By default, `https://dav.example.com/carddav/` is used. For other providers, adjust `CARDDAV_URL` in `.env`:

```bash
CARDDAV_URL=https://cloud.example.com/remote.php/dav/addressbooks/users/USER/contacts/
```

---

## 8. Calendar (CalDAV + Google Calendar)

Niles supports multiple calendar sources simultaneously. Management is done via the **web UI** (Settings > Calendar Sources).

### Adding CalDAV Sources

1. Open web UI: Settings > Calendar Sources
2. **Add New Source**
3. Type: CalDAV
4. Enter URL, username, and password
5. **Save** -- Niles syncs automatically

### Connecting Google Calendar

Google Calendar uses per-user gws (Google Workspace CLI) MCP server instances. Each user gets a dedicated subprocess with their own OAuth token.

1. Google OAuth must be configured (see [Section 4](#4-google-oauth-web-ui-login))
2. Settings > Calendar Sources > **Connect Google Calendar**
3. Complete Google login and allow calendar access
4. Tokens are stored per-user in `user_google_tokens`
5. The gws MCP subprocess starts lazily on first tool call (auto-refreshes tokens, auto-stops after 30 min idle)

To disconnect: Settings > Calendar Sources > **Trennen** (removes tokens and stops the gws instance).

### Legacy Migration

The old `CALDAV_*` variables from `.env` are automatically migrated to the database on first start. New calendar sources are managed exclusively via the web UI.

### Sync Schedule

- Automatic sync: daily at 03:20 UTC
- Manual sync: Settings > Calendar Sources > **Sync Now**

---

## 9. Tasks (Vikunja)

[Vikunja](https://vikunja.io/docs/) is an open-source task manager. Niles can create, list, and complete tasks through it. Vikunja accounts are **auto-provisioned** -- each Niles user automatically gets a Vikunja account and API token on first login.

### Setup

#### 1. Generate JWT Secret

```bash
openssl rand -hex 32
```

Enter in `.env`:

```bash
VIKUNJA_JWT_SECRET=<generated-hex-string>
```

#### 2. Set .env Variables

```bash
VIKUNJA_API_URL=http://vikunja:3456/api/v1

# For Tailscale/remote access: external URL for nav link + Vikunja web UI
VIKUNJA_PUBLIC_URL=https://niles.example.ts.net:3457
```

**Important:** `VIKUNJA_API_URL` must use the Docker-internal hostname `vikunja` (not `localhost`). `VIKUNJA_PUBLIC_URL` must be the **externally reachable** URL (port 3457).

#### 3. Start Containers

```bash
./scripts/start.sh
```

Automatically creates the `vikunja_db` database.

### Auto-Provisioning

When a user logs in to Niles (via Google OAuth or API key), a Vikunja account is automatically created:

1. Niles registers a Vikunja user (username derived from email, password derived via HMAC)
2. Niles logs in to obtain a JWT
3. Niles creates a persistent API token (`tk_...`)
4. The token is stored in `vikunja_credentials` (per-user)

No manual account creation or token generation required. The Vikunja web UI (`https://<host>:3457`) is available for direct task management.

### Verification

Ask in chat: "What's on my todo list?" -- Niles calls `list_tasks` with the user's auto-provisioned credentials.

### Vikunja Web UI

The nav bar shows a "Vikunja" link when `VIKUNJA_PUBLIC_URL` is set. Users can manage tasks directly in the Vikunja web UI using the same credentials that Niles auto-provisioned.

---

## 10. Briefing (Daily/Weekly)

Niles can automatically send morning overviews via WhatsApp, Signal, or both:

- **Daily (Mon-Fri):** Today's appointments, overdue/due tasks, open tasks
- **Weekly (Mon):** Week overview with appointments by day (Mon-Fri)

No LLM needed. Pure database queries + template formatting.

### Prerequisites

1. **Messenger must be connected** (WhatsApp and/or Signal, depending on channel setting). The recipient number is automatically detected from the connected session.
2. **Enable feature flag** (see below)

### Configuration

In `.env`:

```bash
FEATURE_BRIEFING_DAILY=true
FEATURE_BRIEFING_WEEKLY=true

# Times (optional, defaults)
BRIEFING_DAILY_TIME=07:30
BRIEFING_WEEKLY_TIME=07:15

# Briefing delivery channel (default: whatsapp)
#BRIEFING_CHANNEL=whatsapp    # or: signal, both
```

Alternatively via the web UI: **Settings > Briefing** (toggles + times).

### Schedule

| Briefing | When | Condition |
| -------- | ---- | --------- |
| Weekly overview | Monday at `BRIEFING_WEEKLY_TIME` | `FEATURE_BRIEFING_WEEKLY=true` |
| Daily briefing | Mon-Fri at `BRIEFING_DAILY_TIME` | `FEATURE_BRIEFING_DAILY=true` |

On Monday both arrive: first the weekly overview, then the daily briefing. Nothing on weekends.

### Verification

- Startup log shows: `Daily briefing scheduled Mon-Fri at 07:30` (or configured time)
- At briefing time the log shows: `Daily briefing sent to <number>` or `Briefing: No connected WhatsApp session found`
- Check WhatsApp message on own number

### Troubleshooting

| Symptom | Cause | Solution |
| ------- | ----- | -------- |
| No briefing, no log | Feature flag not active | Set `FEATURE_BRIEFING_DAILY=true` in `.env` or Settings UI, restart |
| "No connected WhatsApp session" | WhatsApp/Signal not connected | In web UI: Settings > WhatsApp/Signal > Connect |
| Briefing without tasks | Vikunja not configured | Normal -- briefing only shows calendar appointments |
| Wrong time | Timezone wrong | Check `TIMEZONE=Europe/Vienna` in `.env` |

### Disable

Set `FEATURE_BRIEFING_DAILY=false` and `FEATURE_BRIEFING_WEEKLY=false` in `.env` (or toggles in the Settings UI).

---

## 11. Web Search & Fetch

Niles can search the web and read web pages via two MCP tools.

### Web Search (SearXNG)

[SearXNG](https://docs.searxng.org/) is a self-hosted meta search engine that aggregates results from Google, Bing, DuckDuckGo, and Wikipedia. It runs as a Docker container and requires no API keys.

#### Setup

1. Set in `.env`:

```bash
FEATURE_SEARCH=true
#SEARXNG_URL=http://searxng:8080     # default, usually no change needed
#SEARXNG_SECRET_KEY=<openssl rand -hex 32>  # optional, has a default
```

2. Start with the `search` profile:

```bash
./scripts/start.sh
```

The start script automatically detects `FEATURE_SEARCH=true` and activates the SearXNG Docker profile.

#### How It Works

- SearXNG runs in the Docker network (port 8080, not externally exposed)
- The MCP server `searxng-simple-mcp` runs as a stdio process inside `niles_core`
- The agent uses the `mcp__searxng__search` tool when the user asks to research something
- Results include title, URL, and snippet

#### Verification

```bash
# Check SearXNG is running
docker ps | grep searxng

# Test search (from inside Docker network)
docker exec niles_core python -c "import httpx; print(httpx.get('http://searxng:8080/healthz').status_code)"
```

In chat: "Recherchiere aktuelle Nachrichten zu Apple" -- Niles should call the search tool and return results with source URLs.

### Web Fetch

The Web Fetch MCP server extracts clean text from web pages. It is **always active** (no feature flag, no external container).

#### How It Works

- Runs as a Python MCP server (`niles.mcp.fetch`) inside `niles_core`
- Uses `trafilatura` to extract main content (strips navigation, ads, footer)
- SSRF protection: private/internal IP addresses are blocked
- Supports HTML and plain text only (PDFs, images, etc. are rejected)
- Automatic truncation at 8000 characters (configurable via `FETCH_MAX_CHARS`)

#### Use Cases

- User shares a URL: "What does this page say?"
- After a web search: agent reads full article from a search result
- "Summarize this article: https://..."

#### Combined Research Flow

When both search and fetch are active, the agent can perform deep research:

1. Search with `mcp__searxng__search` for a topic
2. Read 1-2 relevant results with `mcp__fetch__fetch_url`
3. Summarize findings with source URLs

### Search & Fetch Troubleshooting

| Problem | Solution |
| ------- | -------- |
| Search tool not available | Check `FEATURE_SEARCH=true` in `.env`, restart |
| SearXNG container not starting | Run `docker compose -f docker/docker-compose.yml --profile search up -d` |
| "Zugriff auf interne Adressen nicht erlaubt" | SSRF protection working correctly -- internal URLs are blocked by design |
| Fetch returns "Content-Type" error | Only HTML/text pages are supported (no PDFs, images) |

---

## 12. Notion (Knowledge Base)

Niles can use a Notion workspace as a knowledge base via RAG (Retrieval-Augmented Generation). Pages are synced, chunked, and embedded locally using Ollama. Queries are answered via pgvector similarity search.

### Prerequisites

- **Ollama embedding model**: `ollama pull nomic-embed-text`
- **Notion Internal Integration Token**: Create at [notion.so/my-integrations](https://www.notion.so/my-integrations) with "Read content" capability
- **Share pages/databases** with the integration in Notion

### Setup

1. Create a Notion integration at [notion.so/my-integrations](https://www.notion.so/my-integrations):
   - Name: "Niles" (or any name)
   - Capabilities: Read content (no write needed)
   - Copy the Internal Integration Token (`ntn_...`)

2. In Notion, share the pages/databases you want Niles to search with the integration (Share > Invite > select integration).

3. Pull the embedding model on the host:
   ```bash
   ollama pull nomic-embed-text
   ```

4. **Option A: Via Settings UI** (recommended)

   Open Settings > Notion, paste the token, click "Verbinden". Niles tests the connection and starts syncing automatically.

5. **Option B: Via `.env`**

   ```bash
   FEATURE_NOTION=true
   NOTION_TOKEN=ntn_xxxxxxxxxxxxxxxxxxxx
   # Optional:
   # NOTION_SYNC_INTERVAL=30       # minutes between syncs
   # NOTION_EMBEDDING_MODEL=nomic-embed-text-v2-moe  # default set in config.py
   ```
   Then restart: `./scripts/start.sh`

   > **Note:** `NOTION_EMBEDDING_MODEL` is optional — the default (`nomic-embed-text-v2-moe`) is set in `config.py`. Only override via `.env` if you need a different model. When changing models, call `POST /api/notion/reembed` to regenerate all embeddings.

### How It Works

1. **Sync**: Niles discovers all accessible pages via the Notion Search API, fetches block content recursively with markdown formatting (headings, lists, code blocks, quotes), and stores it in `notion_pages`. MD5 change detection avoids redundant work.
2. **Embed**: Changed pages go through a hierarchical chunking pipeline:
   - **Level 0 (Summary)**: LLM-generated 2-4 sentence summary per page (via Ollama). Skipped for pages < 100 chars.
   - **Level 1 (Detail)**: Heading-aware splitting — text is split at `#`/`##`/`###` boundaries first, then by character limit (600 chars) within each section. No cross-section overlap.
   - Each chunk is prefixed with navigation context: `[Parent > Page > # Section > ## Sub-Section]` using breadcrumbs from the `parent_id` chain (max 2 ancestors).
   - Chunks are embedded via Ollama (`nomic-embed-text-v2-moe`, 768 dimensions) and stored in `notion_embeddings` using pgvector.
3. **Search**: The `search_notion` agent tool (or the Notion toggle in the chat UI) embeds the query and runs a cosine similarity search against stored embeddings. Auto-merge scoring combines summary and detail hits.

### Monitoring

Check sync and embedding progress:

```sql
docker exec niles_evolution_postgres psql -U evolution -d evolution_db -c "
SELECT
  COUNT(*) FILTER (WHERE content_md5 != '') AS synced,
  COUNT(*) FILTER (WHERE content_md5 = '') AS sync_pending,
  COUNT(*) FILTER (WHERE embedded_at IS NOT NULL) AS embedded
FROM notion_pages"
```

### Force Re-sync

After a code change to `_block_to_text()` (e.g. new markdown markers), existing `content_text` must be re-fetched from Notion. Reset both `content_md5` and `last_edited` so the sync bypasses its skip checks:

```sql
docker exec niles_evolution_postgres psql -U evolution -d evolution_db -c "
UPDATE notion_pages SET content_md5 = '', embedded_at = NULL, last_edited = NULL"
```

Then trigger a sync via the Settings UI. For embedding-only changes (e.g. chunk size), use the "Re-embed" button in the UI or `POST /api/notion/reembed`.

### Troubleshooting

| Problem | Solution |
| ------- | -------- |
| "Notion-Integration nicht konfiguriert" | Enable `FEATURE_NOTION=true` or connect via Settings UI |
| Connection test fails | Verify token is correct and integration has access to at least one page |
| No search results | Check that sync has completed (`docker logs niles_core \| grep notion`), and that `nomic-embed-text` model is pulled |
| Slow embedding | Normal for first sync with many pages. Subsequent syncs only re-embed changed pages |
| Sync shows "unchanged" after code change | Reset `content_md5` and `last_edited` (see Force Re-sync above) |
| 0 summaries generated | Check Ollama is reachable and summary model supports `"think": false` |

---

## 13. HTTPS & Remote Access (Tailscale + Caddy)

### Caddy (Reverse Proxy)

[Caddy](https://caddyserver.com/docs/) runs as a Docker container and terminates TLS with **self-signed certificates**. Configuration in `docker/Caddyfile`.

#### Adjust Hostnames

Caddy hostnames are configured via environment variables in `.env` (not hardcoded in the Caddyfile). Three variables control the three server blocks:

```bash
# Comma-separated list of hostnames/IPs for each service
CADDY_HOSTS_443=https://localhost, https://192.168.1.100, https://niles.example.ts.net
CADDY_HOSTS_8443=https://localhost:8443, https://192.168.1.100:8443, https://niles.example.ts.net:8443
CADDY_HOSTS_3457=https://localhost:3457, https://192.168.1.100:3457, https://niles.example.ts.net:3457
```

Enter your own IPs/hostnames (Tailscale, LAN, etc.). After changes:

```bash
./scripts/start.sh
```

#### Ports

| Port | Service | Access |
| ---- | ------- | ------ |
| 443 | Niles Web UI + API | HTTPS via Caddy |
| 8443 | Evolution API Manager | HTTPS via Caddy |
| 3457 | Vikunja Web UI | HTTPS via Caddy |
| 11434 | Ollama API | HTTP local |

### Tailscale (Remote Access)

[Tailscale](https://tailscale.com/kb/1081/magicdns) enables secure access from anywhere -- without port forwarding or VPN configuration. See also: [Tailscale HTTPS](https://tailscale.com/kb/1153/enabling-https).

#### Setup

1. [Install Tailscale](https://tailscale.com/download)
2. Log in on the Mac Mini: `tailscale up`
3. Note the Tailscale IP or MagicDNS name (e.g., `niles.example.ts.net`)
4. Add the hostname to `CADDY_HOSTS_*` in `.env` (see above)
5. Set `BASE_URL` in `.env`:

```bash
BASE_URL=https://niles.example.ts.net
```

6. Restart: `./scripts/start.sh`

Niles is now accessible from any device on the Tailscale network.

---

## 14. Backup & Maintenance

### Create Backup

```bash
./scripts/backup.sh
```

Backs up:
- WhatsApp sessions (`~/.evolution/`)
- PostgreSQL database (Docker volume)
- Configuration files (`docker/`, `config/`, `scripts/`, `.env`)
- Restore script

Storage location: `~/Backups/Niles/` (compressed `.tar.gz` archive). Old backups are automatically cleaned up (last 7 kept).

### Restore

```bash
tar -xzf niles-backup-YYYYMMDD_HHMMSS.tar.gz
cd YYYYMMDD_HHMMSS
./restore.sh
```

Then: `./scripts/start.sh`

### Container Updates

```bash
# Rebuild images (with cache)
./scripts/build.sh

# Rebuild images (without cache, when having issues)
./scripts/build.sh --clean

# Start
./scripts/start.sh
```

All code changes to `src/` require rebuilding the Docker image (`./scripts/build.sh && ./scripts/start.sh`). For local development with auto-reload, use `./scripts/dev.sh` instead.

### Full Reset

```bash
./scripts/cleanup.sh
```

Deletes all containers and Docker volumes (PostgreSQL data). WhatsApp sessions (`~/.evolution/`) are **not** deleted.

---

## 15. Troubleshooting

### Service Won't Start

```bash
# Show logs for all containers
docker compose -f docker/docker-compose.yml logs -f

# Niles Core only
docker compose -f docker/docker-compose.yml logs -f niles_core

# Check status
./scripts/status.sh
```

| Symptom | Cause | Solution |
| ------- | ----- | -------- |
| `ValidationError` on start | Required variable missing in `.env` | Set `EVOLUTION_POSTGRES_PASSWORD` and `EVOLUTION_API_KEY` |
| Port 443 in use | Another service using the port | Check `docker ps`, stop other service if needed |
| Container starts and stops immediately | Error in startup | Check `docker logs niles_core` |

### WhatsApp

| Symptom | Cause | Solution |
| ------- | ----- | -------- |
| QR code doesn't appear | Evolution API unreachable | `docker restart niles_evolution_api`, then reconnect |
| Session lost after restart | Volume not mounted | Check if `~/.evolution/instances/` exists |
| "Device was removed" | Offline for too long | Reconnect via Settings > WhatsApp |

### LLM Not Responding

| Symptom | Cause | Solution |
| ------- | ----- | -------- |
| Timeout / no response | Ollama not started | `ollama serve` or `brew services start ollama` |
| Model not found | Model not loaded | `ollama pull llama3.1:8b` |
| Connection error | Wrong LLM_BASE_URL | Check: `curl http://localhost:11434/v1/models` |

### OAuth Errors

| Symptom | Cause | Solution |
| ------- | ----- | -------- |
| "redirect_uri_mismatch" | Redirect URI wrong in Google Console | Check both URIs: `/ui/callback/google` and `/ui/callback/google/calendar` |
| Login works, calendar doesn't | Second redirect URI missing | Add `<BASE_URL>/ui/callback/google/calendar` in Google Console |
| "access_denied" | Email not in whitelist | Check `GOOGLE_ALLOWED_EMAILS` in `.env` (empty = all allowed) |
| Error after IP change | BASE_URL no longer correct | Update `BASE_URL` in `.env`, `./scripts/start.sh` |

### Vikunja

| Symptom | Cause | Solution |
| ------- | ----- | -------- |
| 400 Bad Request | `due_date` without time | Niles normalizes automatically since v0.8. For older versions: update |
| "tasks" tool not available | No Vikunja credentials | Check if `VIKUNJA_API_URL` is set; log in again to trigger auto-provisioning |
| Provisioning failed | Vikunja unreachable | Check container: `docker ps`, check logs: `docker logs vikunja` |
| Database error | `vikunja_db` doesn't exist | `docker exec niles_evolution_postgres createdb -U evolution vikunja_db` |

---

## 16. Reference

### Environment Variables

**Required:**

| Variable | Description |
| -------- | ----------- |
| `EVOLUTION_POSTGRES_PASSWORD` | PostgreSQL password (freely chosen on first start) |
| `EVOLUTION_API_KEY` | Evolution API authentication (freely chosen) |

**General:**

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `NILES_API_KEY` | auto-generated | API key for `/chat` endpoint and fallback login |
| `SESSION_SECRET` | auto-generated | Cookie signing (set stable for sessions across restarts) |
| `BASE_URL` | from request | Base URL for OAuth redirects (required behind reverse proxy) |
| `TIMEZONE` | `Europe/Vienna` | Timezone for calendar, briefings, and prompts |
| `LLM_MODEL` | `llama3.1:8b` | Ollama model |
| `LOG_LEVEL` | `INFO` | Log level (DEBUG, INFO, WARNING, ERROR) |

**Caddy (reverse proxy hostnames):**

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `CADDY_HOSTS_443` | `https://localhost` | Hostnames for Niles Core (:443) |
| `CADDY_HOSTS_8443` | `https://localhost:8443` | Hostnames for Evolution API (:8443) |
| `CADDY_HOSTS_3457` | `https://localhost:3457` | Hostnames for Vikunja (:3457) |

**Google OAuth (optional):**

| Variable | Description |
| -------- | ----------- |
| `GOOGLE_CLIENT_ID` | OAuth Client ID (from Google Cloud Console) |
| `GOOGLE_CLIENT_SECRET` | OAuth Client Secret |
| `GOOGLE_ALLOWED_EMAILS` | Comma-separated email whitelist (empty = all allowed) |

**Vikunja (optional):**

| Variable | Description |
| -------- | ----------- |
| `VIKUNJA_API_URL` | API endpoint (`http://vikunja:3456/api/v1`) |
| `VIKUNJA_PUBLIC_URL` | External URL for nav link + web UI (`https://<host>:3457`) |
| `VIKUNJA_JWT_SECRET` | JWT secret for the Vikunja container |

**Signal (optional, configured via Settings UI):**

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `SIGNAL_API_URL` | `http://signal_api:8080` | signal-cli-rest-api endpoint (override only) |
| `FEATURE_SIGNAL_SEND_OTHERS` | `false` | May Niles send Signal to other people? |
| `BRIEFING_CHANNEL` | `whatsapp` | Briefing delivery: whatsapp, signal, or both |

**Briefing (optional):**

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `FEATURE_BRIEFING_DAILY` | `false` | Daily briefing Mon-Fri via WhatsApp |
| `FEATURE_BRIEFING_WEEKLY` | `false` | Weekly overview Mon via WhatsApp |
| `BRIEFING_DAILY_TIME` | `07:30` | Time for daily briefing (HH:MM) |
| `BRIEFING_WEEKLY_TIME` | `07:15` | Time for weekly overview (HH:MM) |

**Web Search (optional):**

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `FEATURE_SEARCH` | `false` | Enable SearXNG web search |
| `SEARXNG_URL` | `http://searxng:8080` | SearXNG endpoint (Docker-internal) |
| `SEARXNG_SECRET_KEY` | `niles-local-default` | SearXNG secret key (generate with `openssl rand -hex 32`) |

**Notion (optional):**

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `FEATURE_NOTION` | `false` | Enable Notion knowledge base (RAG) |
| `NOTION_TOKEN` | -- | Notion Internal Integration Token (`ntn_...`) |
| `NOTION_SYNC_INTERVAL` | `0` | Minutes between auto-syncs (0 = disabled, manual only) |
| `NOTION_EMBEDDING_MODEL` | `nomic-embed-text-v2-moe` | Ollama embedding model |
| `NOTION_SUMMARY_MODEL` | *(llm_model)* | Ollama model for page summaries (Level-0 chunks) |

**Feature Flags:**

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `FEATURE_WHATSAPP_SEND_OTHERS` | `true` | May Niles send to other people? |
| `FEATURE_SIGNAL_SEND_OTHERS` | `false` | May Niles send Signal to other people? |
| `FEATURE_SEARCH` | `false` | Enable SearXNG web search (requires Docker profile `search`) |
| `FEATURE_NOTION` | `false` | Enable Notion knowledge base (requires `NOTION_TOKEN` + `ollama pull nomic-embed-text`) |

Contacts (CardDAV) and calendars (CalDAV) are configured via the **web UI** (Settings > Contacts / Calendar Sources). Google Calendar is connected per-user via OAuth (Settings > Calendar Sources > Connect Google Calendar). The complete list of all variables including internal defaults is in the [Technical Specification #6.1](Niles-Core-Spec.md#61-settings).

### Ports

| Port | Service | Protocol |
| ---- | ------- | -------- |
| 443 | Niles Web UI + API | HTTPS (Caddy, self-signed) |
| 8443 | Evolution API Manager | HTTPS (Caddy, self-signed) |
| 3457 | Vikunja Web UI | HTTPS (Caddy, self-signed) |
| 11434 | Ollama API | HTTP (local only) |
| 8000 | Niles Core (internal) | HTTP (not directly accessible) |
| 8080 | Evolution API (internal) | HTTP (not directly accessible) |
| 8080 | signal-cli-rest-api (internal, profile: signal) | HTTP (not directly accessible) |
| 8080 | SearXNG (internal, profile: search) | HTTP (not directly accessible) |

### Scripts

| Script | Description |
| ------ | ----------- |
| `./scripts/start.sh` | Start all containers (build + up) |
| `./scripts/stop.sh` | Stop all containers |
| `./scripts/status.sh` | Check status of all services |
| `./scripts/build.sh` | Build Docker images (`--clean` for no cache) |
| `./scripts/backup.sh` | Create full backup |
| `./scripts/cleanup.sh` | Delete all containers and volumes (reset) |
| `./scripts/dev.sh` | Local dev server without Docker |
| `./scripts/test.sh` | Run tests |
| `./scripts/check-pii.sh` | Scan code for PII leaks |

### Further Documentation

- [Development Guide](Development.md) -- Architecture, tests, development
- [Technical Specification](Niles-Core-Spec.md) -- Components, configuration
- [API Reference](API.md) -- Endpoints, payloads, examples
