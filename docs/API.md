# Niles AI Core -- API Reference

> **Updated:** 2026-03-13

---

## HTTPS (homelab-gateway)

All external access goes through HTTPS via the homelab-gateway (Caddy reverse proxy in a separate repo) with subdomain-based routing.

| Subdomain | Service | Internal |
| --------- | ------- | -------- |
| niles.example.local | Niles Core API + Web UI | niles_core:8000 |
| whatsapp.example.local | Evolution API | evolution_api:8080 |
| vikunja.example.local | Vikunja (Task Management) | vikunja:3456 |

- **TLS termination:** Handled by homelab-gateway (separate docker-compose with CoreDNS + Caddy)
- **Internal Docker traffic:** Remains HTTP (container-to-container)
- **Network:** Services connect to the `proxy` external Docker network

---

## Authentication

### /chat -- API Key

Expects the `X-API-Key` header with the value of `NILES_API_KEY`. If no key is set, Niles generates a random key on startup (retrievable via `docker exec niles_core printenv NILES_API_KEY`).

```bash
curl -k -X POST https://localhost/chat \
  -H "X-API-Key: <NILES_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello"}'
```

### /webhook/whatsapp -- URL Token

Expects the query parameter `?token=` with the value of `EVOLUTION_API_KEY`. Evolution API (self-hosted v2.3.x) cannot send custom headers in webhook requests (feature request: [EvolutionAPI/evolution-api#1933](https://github.com/EvolutionAPI/evolution-api/issues/1933)), so a URL token is used instead.

```text
POST /webhook/whatsapp?token=<EVOLUTION_API_KEY>
```

**Risk assessment:** Query parameters can appear in server logs. Caddy does not log query parameters by default. The webhook traffic runs internally over the Docker network (HTTP, container-to-container), never over the public network. Once Evolution API supports custom headers, migration to header-based authentication is recommended.

### /ui/* -- Session Cookies (Google OAuth or API Key)

The web UI uses signed session cookies (itsdangerous). Login via three methods:

1. **Google OAuth 2.0** (primary, when `GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_SECRET` are configured)
2. **Password** (when an admin has assigned a password via the admin panel)
3. **API Key** (fallback, when Google OAuth is not configured)

Session cookies are signed with `SESSION_SECRET` (not `NILES_API_KEY`). All POST endpoints additionally require a CSRF token (Double-Submit Pattern: `niles_csrf` cookie + `X-CSRF-Token` header).

### /metrics -- API Key

Prometheus metrics endpoint. Requires `X-API-Key` header (same as `/chat`). Returns metrics in Prometheus text exposition format.

### /health -- No Auth

Health check is publicly accessible. Rate limiting (60 req/min) does not apply to `/health`.

### Request Tracing (X-Request-ID)

Every response includes an `X-Request-ID` header for request tracing. If the client sends an `X-Request-ID` header (max 64 characters, alphanumeric/dash/underscore), it is echoed back. Otherwise, a 12-character hex ID is generated. The request ID is bound to all log entries via structlog contextvars.

### Rate Limiting

All endpoints (except `/health` and `/static`) are limited to 60 requests per minute per client IP. HTTP 429 is returned when exceeded.

Password and API key login (`POST /ui/login`) have an additional dedicated limit: max 5 attempts per IP in 5 minutes.

### Secrets Rotation

Keys can be rotated at any time:

1. Set new key in `.env` (`NILES_API_KEY`, `SESSION_SECRET`, `EVOLUTION_API_KEY`)
2. Restart containers: `./scripts/start.sh`
3. When changing `EVOLUTION_API_KEY`: Update the webhook URL in the Evolution API (see below)
4. When changing `SESSION_SECRET`: All existing web UI sessions become invalid (users must log in again)

If `NILES_API_KEY` or `SESSION_SECRET` is not set, Niles generates a new key on each container start (automatic rotation).

---

## API Endpoints

### GET /health

Health check. Returns server status and DB pool info.

**Response:**

```json
{
  "status": "ok",
  "db_pool": {"size": 2, "free": 2, "min": 2, "max": 10}
}
```

---

### GET /metrics

Prometheus metrics endpoint. Returns all application metrics in Prometheus text exposition format.

**Authentication:** Requires `X-API-Key` header.

**Available metrics:**

| Metric | Type | Labels | Description |
| ------ | ---- | ------ | ----------- |
| `niles_http_requests_total` | Counter | method, endpoint, status | Total HTTP requests |
| `niles_http_request_duration_seconds` | Histogram | method, endpoint | HTTP request duration |
| `niles_llm_request_duration_seconds` | Histogram | -- | LLM API request duration |
| `niles_llm_tokens_total` | Counter | type (prompt/completion) | LLM tokens consumed |
| `niles_tool_calls_total` | Counter | tool_name, success | Tool call invocations |
| `niles_active_sse_connections` | Gauge | -- | Currently active SSE streams |

**Label cardinality:** Numeric and UUID path segments are normalized to `:id` (e.g., `/api/admin/users/42/password` becomes `/api/admin/users/:id/password`).

---

### POST /chat

Direct chat interface for tests and integrations. Processes the message through the agent (including tool calls, memory, history) and returns the response.

**Request:**

```json
{
  "message": "What's the weather like?"
}
```

**Response:**

```json
{
  "response": "I don't have access to weather data, but ..."
}
```

**Status Codes:**

| Code | Meaning |
| ---- | ------- |
| 200 | Message processed |
| 401 | Missing or invalid API key |
| 422 | Invalid request data |
| 500 | Internal error |

**Notes:**

- Requires `X-API-Key` header (see Authentication)
- Uses `chat_id = "api"` for conversation history
- Memory and tool calls are fully available (same pipeline as WhatsApp)

---

### POST /webhook/whatsapp

Webhook endpoint for the Evolution API. Receives WhatsApp events.

**Processing logic:**

1. Only `event == "messages.upsert"` is processed, everything else is ignored
2. Text is extracted from `message.conversation` or `message.extendedTextMessage.text`
3. Messages without text content are ignored
4. **Own messages (self-chat, `fromMe: true`):**
   - Echo guard: recently sent message IDs are skipped
   - Trigger detection ("Hey Niles", "Hi Niles", "Hallo Niles", "Niles")
   - With trigger: Agent processes, sends response back
   - Without trigger: Ignored
5. **External messages (`fromMe: false`):**
   - Ignored (no LLM call, no auto-reply)
   - Evolution API stores messages internally (queryable via `get_whatsapp_messages` tool)

**Authentication:** Requires `?token=<EVOLUTION_API_KEY>` as query parameter. HTTP 401 for invalid tokens.

**Response:** Always returns HTTP 200 (prevents retry spam from the Evolution API).

---

## Web UI Endpoints (`/ui/*`)

All `/ui/*` routes use signed session cookies. Unauthenticated users are redirected to `/ui/login`.

### GET /ui/login

Login page. Shows depending on configuration:

- **Google OAuth configured:** "Sign in with Google" button + API key as expandable fallback
- **No Google OAuth:** API key input field as primary login

### POST /ui/login

Login via password or API key. Expects `email` + `password` (password login) or `api_key` (API key fallback). Password login resolves the user from DB and verifies against Argon2 hash. API key login creates a local admin session (`uid=0`).

**Status Codes:** 303 (redirect on success), 401 (wrong credentials), 429 (rate limit)

### GET /ui/login/google

Redirects to Google OAuth consent screen. Sets `oauth_state` cookie for CSRF protection.

### GET /ui/callback/google

Google OAuth callback. Exchanges authorization code for access token, retrieves user info, checks:

1. State parameter (CSRF)
2. `email_verified` (only verified accounts)
3. `GOOGLE_ALLOWED_EMAILS` whitelist (if configured)

Creates or updates user in DB, sets session cookie.

**Error handling:** OAuth error codes are mapped to safe messages (no reflection of error parameters).

### POST /ui/logout

Deletes session, CSRF, and OAuth state cookies. POST (not GET) to prevent logout CSRF.

- **htmx requests:** Returns `HX-Redirect: /ui/login` header
- **Regular requests:** HTTP 303 redirect

### GET /ui/chat

Chat page with per-user conversation history. Shows the last 20 messages (paginated).

### GET /ui/settings

Settings dashboard. Shows feature flags, text settings, and infrastructure settings (passwords masked).

### GET /ui/api/chat/history

Loads older chat messages (pagination). Query parameter: `offset` (default: 0).

Returns an HTML fragment (htmx).

### POST /ui/api/chat/stream

Sends a chat message and streams the response via SSE (Server-Sent Events). Expects `message` as form field + CSRF token.

**Flow:**

1. User message is immediately displayed in the browser as a chat bubble (client-side, no server roundtrip)
2. SSE stream delivers events:
   - `{"type": "status", "text": "find_contact..."}` -- Tool call running
   - `{"type": "chunk", "text": "partial text"}` -- Response text (word by word)
   - `{"type": "done"}` -- Stream ended
3. Markdown is rendered client-side after completion (marked.js + DOMPurify)

**Validation:** Messages over 2000 characters are rejected with HTTP 400.

**Response:** `Content-Type: text/event-stream` with `X-Accel-Buffering: no` header.

### POST /ui/api/chat

Fallback endpoint (non-streaming). Sends a chat message. Expects `message` as form field + CSRF token.

Processes the message through the agent (same pipeline as `/chat` and WhatsApp). Returns an HTML fragment with user and assistant messages.

### POST /ui/api/chat/clear

Clears the chat history of the current user. Requires CSRF token.

### GET /ui/api/calendar/sources

Returns the list of all configured calendar sources as an HTML fragment (htmx). Shows name, URL, type badge (ICS/CalDAV), sync status, and errors.

### POST /ui/api/calendar/sources

Adds a new calendar source. Expects form fields: `source_type` (ics/caldav), `name`, `url`, optional `auth_user`, `auth_password`. Returns the updated source list as HTML fragment.

**Validation:** Only HTTPS URLs, max 2048 characters URL, max 200 characters name.

### DELETE /ui/api/calendar/sources/{source_id}

Removes a calendar source. Events from the source are automatically deleted via CASCADE. Returns the updated source list as HTML fragment.

### POST /ui/api/calendar/sources/{source_id}/sync

Triggers a manual sync for a single calendar source. Returns the updated source list as HTML fragment.

### GET /ui/api/calendar/google/connect

Redirects to Google OAuth with calendar scope (requires login session). Sets a `gcal_oauth_state` cookie for CSRF protection. Only visible when `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` are configured.

### GET /ui/callback/google/calendar

Google OAuth callback for calendar connection. Exchanges authorization code for access + refresh tokens, stores per-user tokens in `user_google_tokens` for the gws MCP server. Redirect URI must be registered in the Google Cloud Console: `https://<HOST>/ui/callback/google/calendar`.

### POST /ui/api/calendar/google/disconnect

Removes stored Google tokens and stops the user's gws MCP instance. Requires CSRF token. Returns `HX-Redirect: /ui/settings`.

### POST /ui/api/settings/{key}

Changes a single runtime setting. Expects `value` as form field + CSRF token.

- Only keys in `EDITABLE_SETTINGS` are allowed (feature flags, LLM config, timezone, log level, CardDAV credentials)
- Unknown keys are rejected with an error message
- Changes are persisted in the `settings_overrides` table

### GET /ui/api/whatsapp/status

Returns the WhatsApp connection status of the current user as an HTML fragment. Shows connected phone number, QR code (when connecting), or connect button.

### POST /ui/api/whatsapp/connect

Creates a new Evolution API instance for the current user and returns the QR code for WhatsApp pairing. Instance name: `niles-wa-{user_id}`. Webhook is automatically configured.

### POST /ui/api/whatsapp/disconnect

Disconnects the current user's WhatsApp connection. Performs logout and deletion of the Evolution API instance and removes the session from the DB.

### GET /ui/api/signal/status

Returns the Signal connection status as an HTML fragment. Shows connected phone number, QR code (when connecting), or connect button. Auto-discovers the phone number after QR linking via `GET /v1/accounts` on signal-cli-rest-api.

### GET /ui/api/signal/qrcode

Proxies the QR code PNG from signal-cli-rest-api (`GET /v1/qrcodelink?device_name=niles`). Returns `image/png` or HTTP 502 if unavailable.

### POST /ui/api/signal/link

Starts the Signal linking process. Returns the signal_status HTML fragment in "connecting" state, which shows the QR code and polls for status changes.

### GET /ui/api/contacts/status

Returns the CardDAV connection status as an HTML fragment. Shows number of synced contacts and last sync time.

### POST /ui/api/contacts/connect

Tests CardDAV connection with the provided credentials (`url`, `username`, `password`). On success: saves credentials in settings store, starts initial sync, and registers daily sync job.

### POST /ui/api/contacts/disconnect

Removes CardDAV credentials from the settings store, deletes all synced contacts, and removes the sync job.

### POST /ui/api/contacts/sync

Triggers a manual CardDAV contact sync. Returns the updated status as HTML fragment.

### GET /ui/api/caldav/calendars

Returns available CalDAV calendar collections as an HTML fragment (via PROPFIND discovery).

---

## Agent Tools

The agent can execute the following functions via LLM tool calls:

### find_contact

Searches for a contact by name in the PostgreSQL database. Supports multi-word search (e.g., "Thomas Brunner" also matches "Brunner Thomas").

**Parameters:**

| Name | Type | Required | Description |
| ---- | ---- | -------- | ----------- |
| `name` | string | Yes | Name or partial name (single or multi-word) |

**Return (success):**

```json
{
  "full_name": "Max Mustermann",
  "phone": "436601234567",
  "phones": [
    {"type": "mobile", "number": "436601234567"},
    {"type": "work", "number": "4312345678"}
  ],
  "email": "max@example.com"
}
```

**Return (error):**

```json
{"error": "Contact 'Maxl' not found"}
```

**Search prioritization:** exact > prefix > partial > multi-word across name fields.

---

### send_whatsapp

Sends a WhatsApp message. Accepts phone numbers or contact names (resolved automatically).

**Parameters:**

| Name | Type | Required | Description |
| ---- | ---- | -------- | ----------- |
| `to` | string | Yes | Phone number (e.g., `"436601234567"`) or contact name |
| `text` | string | Yes | Message text |

**Return (success):**

```json
{"status": "sent", "to": "436601234567"}
```

**Notes:**

- If `to` is not a number, `find_contact` is executed first
- **Multi-phone:** If the contact has multiple numbers, the user is asked for a selection (numbered list, 5 min TTL). This selection bypasses the LLM completely (bypass flow).
- Phone numbers are automatically converted to JID format (`@s.whatsapp.net`)
- **Per-user instance:** For web UI users, the per-user WhatsApp instance is used (fallback: global instance)
- Timeout: 30 seconds

---

### get_whatsapp_messages

Reads a contact's WhatsApp chat history. Uses the Evolution API (`POST /chat/findMessages/{instance}`).

**Parameters:**

| Name | Type | Required | Description |
| ---- | ---- | -------- | ----------- |
| `contact` | string | Yes | Contact name or phone number |

**Return (success):**

```json
{"messages": [{"from_me": false, "text": "Hello!", "timestamp": 1771900000, "push_name": "Max"}], "count": 1}
```

**Return (error):**

```json
{"error": "Contact 'Nobody' not found"}
```

**Notes:**

- Contact name is resolved to phone number via `find_contact`, then passed as JID (`@s.whatsapp.net`) to the Evolution API
- Returns both incoming and outgoing messages (conversation context)
- **30-day window:** Only messages from the last 30 days
- **Per-user instance:** Uses the requesting user's instance
- Non-text messages (images, audio, etc.) receive placeholders ([Image], [Video], [Voice message], [Sticker], [Document], [Contact], [Location])

---

### send_signal

Sends a Signal message. Accepts phone numbers or contact names (resolved automatically). Only available when `feature_signal` is active.

**Parameters:**

| Name | Type | Required | Description |
| ---- | ---- | -------- | ----------- |
| `to` | string | Yes | Phone number (e.g., `"+436601234567"`) or contact name |
| `text` | string | Yes | Message text |

**Return (success):**

```json
{"status": "sent", "to": "+436601234567"}
```

**Notes:**

- If `to` is not a number, `find_contact` is executed first
- Phone numbers use `+` prefix (Signal convention, e.g., `+436601234567`)
- Sending to contacts other than self requires `feature_signal_send_others=true`
- Timeout: 30 seconds

---

### get_signal_messages

Reads a contact's Signal message history from the local PostgreSQL store.

**Parameters:**

| Name | Type | Required | Description |
| ---- | ---- | -------- | ----------- |
| `contact` | string | Yes | Contact name or phone number |

**Return (success):**

```json
{"messages": [{"from_me": false, "text": "Hello!", "timestamp": "2026-02-25T14:00:00+01:00"}], "count": 1}
```

**Return (error):**

```json
{"error": "Contact 'Nobody' not found"}
```

**Notes:**

- Contact name is resolved to phone number via `find_contact`
- Messages are stored locally in PostgreSQL (signal-cli-rest-api has no findMessages API)
- **30-day window:** Only messages from the last 30 days
- Only available when `feature_signal` is active

---

### remember

Stores a fact permanently in the key-value memory. UPSERT semantics: existing keys are overwritten.

**Parameters:**

| Name | Type | Required | Description |
| ---- | ---- | -------- | ----------- |
| `key` | string | Yes | Short key (e.g., `"dentist_appointment"`) |
| `value` | string | Yes | Content to remember |

**Return:**

```json
{"status": "saved", "key": "dentist_appointment"}
```

---

### recall

Retrieves a stored fact from memory.

**Parameters:**

| Name | Type | Required | Description |
| ---- | ---- | -------- | ----------- |
| `key` | string | Yes | Key |

**Return (success):**

```json
{"key": "dentist_appointment", "value": "Tomorrow at 10 AM"}
```

**Note:** All memory entries are automatically injected into the system prompt. `recall` is only needed when the agent wants to search for a specific key.

---

### find_event

Searches calendar events from all configured calendar sources (ICS, CalDAV). Max 10 results, sorted by start time.

**Parameters:**

| Name | Type | Required | Description |
| ---- | ---- | -------- | ----------- |
| `query` | string | No | Search term (name, location, description). Leave empty for date-only search. |
| `date_from` | string | No | Start date (ISO format, e.g., `"2026-02-20"`). |
| `date_to` | string | No | End date (ISO format). Only for explicit date ranges. |
| `calendar` | string | No | Calendar name for targeted search. |

**Return (success):**

```json
{"events": [...], "count": 3}
```

Each event object contains:

| Field | Type | Always | Description |
| ----- | ---- | ------ | ----------- |
| `summary` | string | Yes | Event title |
| `start` | string | Yes | Start time (ISO) or date for all-day events |
| `all_day` | boolean | Yes | `true` for all-day events |
| `end` | string | No | End time (ISO), only if present |
| `description` | string | No | Description, only if present |
| `location` | string | No | Location, only if present |
| `status` | string | No | `"available"` when the event does not block time (iCal `TRANSP:TRANSPARENT`). Missing for normal (blocking) events. |

**Return (error):**

```json
{"error": "No events found"}
```

---

### create_event

Creates a new calendar entry on the first writable calendar source (via `CalendarSourceManager`). Returns an error if no writable source is configured.

**Parameters:**

| Name | Type | Required | Description |
| ---- | ---- | -------- | ----------- |
| `summary` | string | Yes | Event title |
| `start` | string | Yes | Start time (ISO format, e.g., `"2026-02-20T14:00"`) |
| `end` | string | No | End time (ISO format). Default: 1 hour after start. |
| `description` | string | No | Event description |
| `location` | string | No | Event location |

---

### list_tasks

Lists open tasks from Vikunja. Only available when the user has Vikunja credentials (auto-provisioned on login).

**Parameters:**

| Name | Type | Required | Description |
| ---- | ---- | -------- | ----------- |
| `project` | string | No | Project name to filter. Empty = all projects. |
| `include_done` | boolean | No | Also show completed tasks. Default: false. |

**Return (success):**

```json
{"tasks": [{"id": 1, "title": "Buy milk", "done": false, "due_date": "2026-02-25T18:00:00Z"}], "count": 1}
```

**Return (error):**

```json
{"error": "No tasks found"}
```

---

### create_task

Creates a new task in Vikunja. Only available when the user has Vikunja credentials (auto-provisioned on login).

**Parameters:**

| Name | Type | Required | Description |
| ---- | ---- | -------- | ----------- |
| `title` | string | Yes | Task title |
| `description` | string | No | Task description |
| `due_date` | string | No | Due date (ISO format, e.g., `"2026-02-25T18:00"`) |
| `priority` | integer | No | Priority: 0=none, 1=low, 2=medium, 3=high, 4=urgent. Default: 0. |
| `project` | string | No | Project name. Empty = default project. |

**Return (success):**

```json
{"created": true, "id": 20, "title": "Call dentist", "project_id": 1}
```

**Return (error):**

```json
{"error": "Project 'Nonexistent' not found"}
```

---

### complete_task

Marks a task as done. Searches by title among open tasks. Only available when the user has Vikunja credentials (auto-provisioned on login).

**Parameters:**

| Name | Type | Required | Description |
| ---- | ---- | -------- | ----------- |
| `title` | string | Yes | Title or partial title of the task |

**Return (success):**

```json
{"completed": true, "title": "Buy milk"}
```

**Return (error -- not found):**

```json
{"error": "No open task found: 'Nonexistent'"}
```

**Return (error -- ambiguous):**

```json
{"error": "Multiple tasks found. Which one do you mean?", "matches": ["Shopping", "Write email"]}
```

---

## MCP Tools (Auto-Discovered)

In addition to the built-in tools above, the agent can use tools from MCP servers. These are automatically discovered on startup from `config/mcp_servers.yaml`.

### mcp__fetch__fetch_url

Fetches a web page and extracts the main text content (strips navigation, ads, footer). Always active.

**Parameters:**

| Name | Type | Required | Description |
| ---- | ---- | -------- | ----------- |
| `url` | string | Yes | URL to fetch (https:// prepended if missing) |
| `max_chars` | integer | No | Max characters to return (default: 8000) |

**Return (success):** Extracted plain text content of the page.

**Return (error):** `"Fehler: ..."` with description (timeout, blocked scheme, SSRF, wrong content type).

**Security:**

- Blocked schemes: `file://`, `ftp://`, `data:`, `javascript:`
- SSRF protection: private/internal IP addresses are blocked (10.x, 172.16.x, 192.168.x, 127.x, 169.254.x, IPv6 link-local/ULA)
- Content-Type: only `text/html`, `text/plain`, `application/xhtml`
- Max response size: 5 MB
- Max redirects: 5

### mcp__searxng__web_search

Web search via SearXNG meta search engine. Only available when `FEATURE_SEARCH=true`.

**Parameters:**

| Name | Type | Required | Description |
| ---- | ---- | -------- | ----------- |
| `query` | string | Yes | Search query |
| `max_results` | integer | No | Max results (default: 10) |
| `language` | string | No | Language code (default: `de`) |
| `time_range` | string | No | Time filter (e.g., `day`, `week`, `month`) |

**Return:** Search results with title, URL, and snippet. Formatted for LLM context (low token usage).

### mcp__gws__*

Google Workspace tools via per-user gws MCP server instances. Only available when the user has connected their Google account (Settings > Calendar Sources > Connect Google Calendar). Each user gets a dedicated gws subprocess with their own OAuth token. Tools include calendar operations (list, create, update events). Tool names are prefixed with `mcp__gws__` (e.g., `mcp__gws__list_events`).

### mcp__weather__*

Weather tools via Open-Meteo API. Always active (when coordinates configured in Settings > Weather).

Tools include current weather conditions and forecasts. See [Weather MCP server](../src/niles/mcp/weather/server.py) for details.

---

## Automated Briefings (Scheduled)

Niles automatically sends daily and weekly overviews via the configured channel (WhatsApp, Signal, or both). These are not triggered through the API but run as APScheduler cron jobs.

| Briefing | Schedule | Feature Flag |
| -------- | -------- | ------------ |
| Daily | Mon-Fri, configurable (default: 07:30) | `FEATURE_BRIEFING_DAILY` |
| Weekly | Monday, configurable (default: 07:15) | `FEATURE_BRIEFING_WEEKLY` |

| Setting | Values | Default | Description |
| ------- | ------ | ------- | ----------- |
| `BRIEFING_CHANNEL` | `whatsapp` \| `signal` \| `both` | `whatsapp` | Delivery channel for automated briefings |

**Prerequisites:**

- Feature flag enabled (`true` in `.env` or Settings UI)
- At least one messenger connected (WhatsApp or Signal, depending on `BRIEFING_CHANNEL` setting)

**No LLM call.** Pure database queries (calendar events from PostgreSQL) + Vikunja API (open tasks) + template formatting.

**Daily briefing content:** Today's appointments, overdue tasks, tasks due today, open tasks summary.

**Weekly overview content:** Mon-Fri appointments grouped by day, open tasks compact.

**Distinction:** When a user asks in chat for a daily overview ("What's on today?"), the agent uses the `find_event` + `list_tasks` tools instead (LLM-based). The automated briefings are template-based and do not require an LLM.

Times and feature flags are configurable via the web UI (Settings > Briefing) or `.env`. See [Deployment Guide](Deployment.md#9-briefing-dailyweekly) for setup details.

---

## Evolution API Webhook Configuration

The Evolution API must be configured to send webhooks to Niles:

```bash
curl -k -X POST https://whatsapp.example.local/webhook/set/niles-whatsapp \
  -H "apikey: <EVOLUTION_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{
    "webhook": {
      "enabled": true,
      "url": "http://niles_core:8000/webhook/whatsapp?token=<EVOLUTION_API_KEY>",
      "events": ["MESSAGES_UPSERT"]
    }
  }'
```

**Note:** The webhook URL uses the Docker-internal hostname `niles_core` (HTTP, container-to-container). The `curl` call itself goes through homelab-gateway (HTTPS).

---

## Error Handling

| Scenario | Behavior |
| -------- | -------- |
| LLM unreachable | Error message to user, error logged |
| LLM returns empty response | Warning logged, empty string returned |
| Tool call with invalid arguments | `{"error": "Invalid arguments"}` returned to LLM |
| Unknown tool name | `{"error": "Unknown tool: ..."}` returned to LLM |
| Max tool rounds reached (5) | Warning logged, fallback message to user |
| Webhook: invalid JSON | Warning logged, HTTP 200 |
| Webhook: agent error | Exception logged, HTTP 200 (no retry) |
| WhatsApp send failed | Error logged, `{"error": "..."}` returned to LLM |
| Signal send failed | Error logged, `{"error": "..."}` returned to LLM |
| Web UI: invalid session | Redirect to /ui/login |
| Web UI: invalid CSRF | 403, redirect to /ui/login (via HX-Redirect) |
| Web UI: agent error | Error message displayed in chat fragment |
| Web UI: SSE stream error | Error message shown as assistant bubble |
| Web UI: message too long (>2000) | HTTP 400, message not sent |

---

## Further Documentation

- [Technical Specification](Niles-Core-Spec.md) -- Architecture, components, configuration
- [Development Guide](Development.md) -- Setup, testing, conventions
