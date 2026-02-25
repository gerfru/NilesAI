# Niles AI -- Deployment Guide

> **Updated:** 2026-02-25

This guide describes the complete setup of Niles AI -- from a blank machine to a running system.

For technical details on architecture and development, see [Development.md](Development.md).

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Quick Start](#2-quick-start)
3. [Ollama (LLM Backend)](#3-ollama-llm-backend)
4. [Google OAuth (Web UI Login)](#4-google-oauth-web-ui-login)
5. [WhatsApp (Evolution API)](#5-whatsapp-evolution-api)
6. [Contacts (CardDAV)](#6-contacts-carddav)
7. [Calendar (CalDAV + Google Calendar)](#7-calendar-caldav--google-calendar)
8. [Tasks (Vikunja)](#8-tasks-vikunja)
9. [Briefing (Daily/Weekly)](#9-briefing-dailyweekly)
10. [HTTPS & Remote Access (Tailscale + Caddy)](#10-https--remote-access-tailscale--caddy)
11. [Backup & Maintenance](#11-backup--maintenance)
12. [Troubleshooting](#12-troubleshooting)
13. [Reference](#13-reference)

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
| Google Cloud | OAuth login for web UI + Google Calendar sync |
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
4. Automatically creates the `vikunja_db` database
5. Outputs the service URLs

### Health Check

```bash
curl -sk https://localhost/health
# Expected response: {"status":"ok"}
```

Web UI: `https://localhost/ui/login` (self-signed certificate -- accept browser warning)

### Alternative: Interactive Setup

```bash
./scripts/setup-interactive.sh
```

Guides step by step through the setup with status checks.

---

## 3. Ollama (LLM Backend)

Ollama runs **natively on the host** (not in Docker) to utilize full GPU performance.

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

### Step 1: Google Cloud Project

1. Open [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (e.g., "Niles AI")
3. Configure **APIs & Services > OAuth consent screen**:
   - User Type: External
   - App name: "Niles AI"
   - Scopes: `email`, `profile`, `openid`
   - For Google Calendar additionally: `https://www.googleapis.com/auth/calendar.readonly`

### Step 2: Create OAuth Client

1. **APIs & Services > Credentials > Create Credentials > OAuth client ID**
2. Application type: **Web application**
3. Name: "Niles"
4. **Authorized redirect URIs** (enter both!):

```
https://<YOUR-URL>/ui/callback/google
https://<YOUR-URL>/ui/callback/google/calendar
```

Examples:
- Local: `https://localhost/ui/callback/google`
- Tailscale: `https://niles.tail1d4a0f.ts.net/ui/callback/google`

### Step 3: Configure .env

```bash
GOOGLE_CLIENT_ID=123456789-abc.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-xxxxxxxxxxxx

# Comma-separated whitelist (empty = all Google accounts allowed)
GOOGLE_ALLOWED_EMAILS=user@gmail.com

# Must be set when behind a reverse proxy
BASE_URL=https://niles.tail1d4a0f.ts.net
```

### Step 4: Restart & Test

```bash
./scripts/start.sh
```

Open `https://<YOUR-URL>/ui/login` -- the Google login button should appear.

---

## 5. WhatsApp (Evolution API)

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

## 6. Contacts (CardDAV)

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

By default, `https://dav.mailbox.org/carddav/` is used. For other providers, adjust `CARDDAV_URL` in `.env`:

```bash
CARDDAV_URL=https://cloud.example.com/remote.php/dav/addressbooks/users/USER/contacts/
```

---

## 7. Calendar (CalDAV + Google Calendar)

Niles supports multiple calendar sources simultaneously. Management is done via the **web UI** (Settings > Calendar Sources).

### Adding CalDAV Sources

1. Open web UI: Settings > Calendar Sources
2. **Add New Source**
3. Type: CalDAV
4. Enter URL, username, and password
5. **Save** -- Niles syncs automatically

### Connecting Google Calendar

1. Google OAuth must be configured (see [Section 4](#4-google-oauth-web-ui-login))
2. Settings > Calendar Sources > **Connect Google Calendar**
3. Complete Google login and allow calendar access
4. Select desired calendars

### Legacy Migration

The old `CALDAV_*` variables from `.env` are automatically migrated to the database on first start. New calendar sources are managed exclusively via the web UI.

### Sync Schedule

- Automatic sync: daily at 03:20 UTC
- Manual sync: Settings > Calendar Sources > **Sync Now**

---

## 8. Tasks (Vikunja)

Vikunja is an open-source task manager. Niles can create, list, and complete tasks through it.

### Initial Setup

#### 1. Generate JWT Secret

```bash
openssl rand -hex 32
```

Enter in `.env`:

```bash
VIKUNJA_JWT_SECRET=<generated-hex-string>
```

#### 2. Set Additional .env Variables

```bash
VIKUNJA_API_URL=http://vikunja:3456/api/v1
VIKUNJA_API_TOKEN=               # comes in step 5
FEATURE_VIKUNJA=true

# For Tailscale/remote access: Set external URL (for email links etc.)
#VIKUNJA_PUBLIC_URL=https://niles.tail1d4a0f.ts.net:3457
```

**Important:** `VIKUNJA_API_URL` must use the Docker-internal hostname `vikunja` (not `localhost`). `VIKUNJA_PUBLIC_URL` however must be the **externally reachable** URL.

#### 3. Start Containers

```bash
./scripts/start.sh
```

Automatically creates the `vikunja_db` database.

#### 4. Create Admin Account

1. Open `https://localhost:3457` (or `https://<tailscale-ip>:3457`)
2. **Create Account** -- Choose username and password
3. Create a default project (e.g., "Inbox")

Then **disable registration** in `docker/docker-compose.yml`:

```yaml
VIKUNJA_SERVICE_ENABLEREGISTRATION: "false"
```

> **Security note:** As long as `ENABLEREGISTRATION=true`, **anyone with network access** to port 3457 can create a Vikunja account. On Tailscale-only setups, this is protected by network ACLs. If the host is reachable from the internet, disable registration after account creation.

#### 5. Generate API Token

1. Log in to Vikunja
2. Settings > API Tokens > **Create Token**
3. Permissions: at least `tasks` (Read + Write)
4. Enter token in `.env`:

```bash
VIKUNJA_API_TOKEN=<token-from-vikunja>
```

#### 6. Restart Niles

```bash
./scripts/start.sh
```

### Per-User Tokens

Each user can store their own Vikunja token (Settings > Tasks). This gives each user their own task lists. The token from `.env` serves as fallback.

### Verification

Ask in chat: "What's on my todo list?" -- Niles calls `list_tasks`.

### Disable

Set `FEATURE_VIKUNJA=false` in `.env`. Task tools will then not be sent to the LLM.

---

## 9. Briefing (Daily/Weekly)

Niles can automatically send morning overviews via WhatsApp:

- **Daily (Mon-Fri):** Today's appointments, overdue/due tasks, open tasks
- **Weekly (Mon):** Week overview with appointments by day (Mon-Fri)

No LLM needed. Pure database queries + template formatting.

### Prerequisites

1. **WhatsApp must be connected** (Settings > WhatsApp > Connect). The recipient number is automatically detected from the connected session.
2. **Enable feature flag** (see below)

### Configuration

In `.env`:

```bash
FEATURE_BRIEFING_DAILY=true
FEATURE_BRIEFING_WEEKLY=true

# Times (optional, defaults)
BRIEFING_DAILY_TIME=07:30
BRIEFING_WEEKLY_TIME=07:15
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
| "No connected WhatsApp session" | WhatsApp not connected | In web UI: Settings > WhatsApp > Connect |
| Briefing without tasks | Vikunja not configured | Normal -- briefing only shows calendar appointments |
| Wrong time | Timezone wrong | Check `TIMEZONE=Europe/Vienna` in `.env` |

### Disable

Set `FEATURE_BRIEFING_DAILY=false` and `FEATURE_BRIEFING_WEEKLY=false` in `.env` (or toggles in the Settings UI).

---

## 10. HTTPS & Remote Access (Tailscale + Caddy)

### Caddy (Reverse Proxy)

Caddy runs as a Docker container and terminates TLS with **self-signed certificates**. Configuration in `docker/Caddyfile`.

#### Adjust Hostnames

The Caddyfile contains preconfigured hostnames:

```
https://localhost, https://100.85.159.70, https://192.168.0.248, https://niles.tail1d4a0f.ts.net {
    tls internal
    reverse_proxy niles_core:8000
}
```

**Important:** The Caddyfile contains hardcoded IPs (`100.85.159.70` = Tailscale, `192.168.0.248` = LAN). These must be adjusted for each deployment environment -- in **all three** server blocks (Niles Core :443, Evolution API :8443, Vikunja :3457).

Enter your own IPs/hostnames here. After changes:

```bash
docker restart niles_caddy
```

#### Ports

| Port | Service | Access |
| ---- | ------- | ------ |
| 443 | Niles Web UI + API | HTTPS via Caddy |
| 8443 | Evolution API Manager | HTTPS via Caddy |
| 3457 | Vikunja Web UI | HTTPS via Caddy |
| 11434 | Ollama API | HTTP local |

### Tailscale (Remote Access)

Tailscale enables secure access from anywhere -- without port forwarding or VPN configuration.

#### Setup

1. [Install Tailscale](https://tailscale.com/download)
2. Log in on the Mac Mini: `tailscale up`
3. Note the Tailscale IP or MagicDNS name (e.g., `niles.tail1d4a0f.ts.net`)
4. Enter the hostname in `docker/Caddyfile` (see above)
5. Set `BASE_URL` in `.env`:

```bash
BASE_URL=https://niles.tail1d4a0f.ts.net
```

6. Restart: `./scripts/start.sh`

Niles is now accessible from any device on the Tailscale network.

---

## 11. Backup & Maintenance

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

For changes to `src/`, no rebuild is needed -- the directory is mounted via volume and the uvicorn server reloads automatically.

### Full Reset

```bash
./scripts/cleanup.sh
```

Deletes all containers and Docker volumes (PostgreSQL data). WhatsApp sessions (`~/.evolution/`) are **not** deleted.

---

## 12. Troubleshooting

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
| 401 Unauthorized | Token expired or wrong | Generate new token in Vikunja, enter in `.env` |
| "tasks" tool not available | Feature disabled | Set `FEATURE_VIKUNJA=true` in `.env` |
| Database error | `vikunja_db` doesn't exist | `docker exec niles_evolution_postgres createdb -U evolution vikunja_db` |

---

## 13. Reference

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

**Google OAuth (optional):**

| Variable | Description |
| -------- | ----------- |
| `GOOGLE_CLIENT_ID` | OAuth Client ID (from Google Cloud Console) |
| `GOOGLE_CLIENT_SECRET` | OAuth Client Secret |
| `GOOGLE_ALLOWED_EMAILS` | Comma-separated email whitelist (empty = all allowed) |

**Vikunja (optional):**

| Variable | Description |
| -------- | ----------- |
| `FEATURE_VIKUNJA` | `true` to enable (default: `false`) |
| `VIKUNJA_API_URL` | API endpoint (`http://vikunja:3456/api/v1`) |
| `VIKUNJA_API_TOKEN` | API token (fallback, per-user tokens via Settings UI) |
| `VIKUNJA_JWT_SECRET` | JWT secret for the Vikunja container |

**Briefing (optional):**

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `FEATURE_BRIEFING_DAILY` | `false` | Daily briefing Mon-Fri via WhatsApp |
| `FEATURE_BRIEFING_WEEKLY` | `false` | Weekly overview Mon via WhatsApp |
| `BRIEFING_DAILY_TIME` | `07:30` | Time for daily briefing (HH:MM) |
| `BRIEFING_WEEKLY_TIME` | `07:15` | Time for weekly overview (HH:MM) |

**Feature Flags:**

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `FEATURE_WHATSAPP_SEND_OTHERS` | `true` | May Niles send to other people? |

Contacts (CardDAV) and calendars (CalDAV) are configured via the **web UI** (Settings > Contacts / Calendar Sources). The complete list of all variables including internal defaults is in the [Technical Specification #6.1](Niles-Core-Spec.md#61-settings).

### Ports

| Port | Service | Protocol |
| ---- | ------- | -------- |
| 443 | Niles Web UI + API | HTTPS (Caddy, self-signed) |
| 8443 | Evolution API Manager | HTTPS (Caddy, self-signed) |
| 3457 | Vikunja Web UI | HTTPS (Caddy, self-signed) |
| 11434 | Ollama API | HTTP (local only) |
| 8000 | Niles Core (internal) | HTTP (not directly accessible) |
| 8080 | Evolution API (internal) | HTTP (not directly accessible) |

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
| `./scripts/setup-interactive.sh` | Interactive setup wizard |

### Further Documentation

- [Development Guide](Development.md) -- Architecture, tests, development
- [Technical Specification](Niles-Core-Spec.md) -- Components, configuration
- [API Reference](API.md) -- Endpoints, payloads, examples
