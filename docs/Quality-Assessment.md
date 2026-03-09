# Technical Quality Assessment

> Last updated: 2026-03-09 | After Phase 1 + Phase 2 + Notion RAG + Per-User Google MCP

## Score Overview

| Dimension          | Score | Trend | Next Lever                                      |
|--------------------|-------|-------|-------------------------------------------------|
| KISS / Complexity  | 8.5   | =     | Extract `main.py` startup logic                 |
| Security           | 9.5   | =     | HSTS at app level, SBOM                         |
| Architecture       | 8.5   | =     | Extract `main.py` lifespan into builder/factory |
| DevOps             | 9.5   | =     | Staging environment, rollback docs              |
| UI/UX              | 8.0   | =     | axe-core CI integration, HTMX focus management  |
| Maintainability    | 8.5   | =     | Reduce remaining 10 mypy overrides              |
| Observability      | 7.0   | =     | Sentry or equivalent                            |
| Resilience         | 8.0   | =     | Circuit breakers, Ollama retry                  |
| Performance        | 8.5   | =     | Query result caching, remaining 3 raw clients   |
| API Design         | 8.0   | =     | OpenAPI schema curation                         |

**Average: 8.4/10** | Weighted (Security, Architecture, Maintainability x1.3; UI x0.8): **8.5/10**

---

## History

| Date       | Event                                          | Score |
|------------|------------------------------------------------|-------|
| 2026-02-28 | Initial evaluation (6 dims)                    | 7.8   |
| 2026-03-01 | After core.py refactoring                      | 8.2   |
| 2026-03-02 | +4 new dimensions, web split                   | 7.9   |
| 2026-03-03 | Phase 1 (PR #45) + Phase 2 (PR #46)            | 8.5   |
| 2026-03-09 | Notion RAG + Per-User Google MCP (PRs #50-#52) | 8.5   |

The drop from 8.2 to 7.9 (2026-03-02) was due to adding four new dimensions
(Observability, Resilience, Performance, API Design) that scored lower. Phase 1
raised 4 weak dimensions (Resilience +1.5, Performance +1.0, UI +1.0,
Maintainability +0.5). Phase 2 raised 4 structural dimensions (KISS +1.0,
Security +0.5, DevOps +0.5, API Design +0.5).

---

## 1. KISS / Complexity — 8.5/10

| Metric              | Value                                                       |
|---------------------|-------------------------------------------------------------|
| Largest file        | `agent/core.py` — 866 LOC (was 1,126)                      |
| Agent modules       | `core.py` 866, `context.py` 346, `text_tool_parser.py` 121 |
| Web module max      | 365 LOC (`_notion.py`) — was 2,444                         |
| Direct dependencies | 26 (pyproject.toml)                                         |
| Avg file size       | ~153 LOC across 82 Python files                             |

### Evidence

**Why 8.5 and not higher:**

`main.py` at 756 LOC still mixes app factory, middleware setup, lifespan
management, health endpoints, and metrics endpoint in one file. The lifespan
handler alone initializes 20+ `app.state` attributes (grew with Notion RAG
and per-user Google MCP pool).

**Why 8.5 and not lower:**

- NilesAgent split into 3 focused modules: `core.py` (orchestration, ~486 LOC
  class + 340 LOC TOOLS constant), `context.py` (context assembly, user/resource
  resolution), `text_tool_parser.py` (pure functions for JSON tool-call detection)
- 80% of files under 400 LOC
- Web split (14 modules, max 365 LOC) demonstrates the target structure

**Score change (Phase 2):** +1.0 from 7.5 — NilesAgent split eliminated the
last >1,000 LOC file. Each module now has a single responsibility.

---

## 2. Security — 9.5/10

**SQL injection — fully mitigated:**

Every SQL query uses asyncpg positional parameters. Verified across all stores:

```text
src/niles/user_store.py:38      "... WHERE email = $1", email
src/niles/user_store.py:97      "INSERT INTO users ... VALUES ($1, $2, $3, $4, $5)", ...
src/niles/memory/store.py:25    "INSERT INTO memory ... VALUES ($1, $2, $3)", ...
src/niles/settings_store.py:32  "... WHERE key = $1", key
```

No string formatting (`f"..."`, `%`, `.format()`) found in any SQL statement.

**XSS — mitigated via CSP + auto-escaping:**

Jinja2 auto-escaping is enabled (default for `Jinja2Templates`). The custom
`_NilesTemplates` class (`web/_core.py:23-32`) injects a CSP nonce into every
template context, which the base template uses for inline scripts.

CSP policy (`main.py`):

```text
default-src 'self';
script-src 'nonce-{nonce}' 'strict-dynamic' 'self';
style-src 'self';
img-src 'self' data: https://*.googleusercontent.com;
report-uri /csp-report
```

No `'unsafe-inline'` for scripts. `'strict-dynamic'` allows nonce-approved
scripts to load dependencies.

**CSRF — double-submit with timing-safe comparison:**

`_verify_csrf()` at `web/_core.py:111` compares header `x-csrf-token` against
cookie value using `hmac.compare_digest()`, preventing timing attacks. Applied
to all POST/DELETE handlers via `_require_auth_and_csrf()`.

**Authentication:**

- Argon2 password hashing (`_auth.py:34`, `_admin.py:18`)
- Timing defense: dummy hash on failed lookup (`_auth.py:112`) prevents
  user enumeration via response time
- Session cookies: `httponly=True` (`_core.py:102`), `secure` based on
  `_is_secure_context()` (`_core.py:57-62`), `samesite=lax` (`_core.py:104`)
- Cookie size guard: rejects tokens > 4096 bytes (`_core.py:76`)

**Rate limiting:**

- Global: `RateLimitMiddleware` at `main.py`, 60 req/min per IP
- Login: 5 attempts per 5 minutes per IP (`_auth.py:42-52`), with cleanup
  of expired entries to prevent memory leak

**Security headers** (`main.py`):

```text
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: camera=(), microphone=(), geolocation=()
```

**CSP violation reporting** (`main.py`):

`report-uri /csp-report` directive in CSP header. The `POST /csp-report`
endpoint logs violations at WARNING level and returns 204. Gracefully handles
malformed JSON. Rate limiting applies via existing middleware.

**Dependency vulnerability scanning:**

`pip-audit --desc --skip-editable` runs in CI (`dependency-audit` job).
Fails the pipeline on any known vulnerability (one documented exception:
CVE-2025-69872, diskcache pickle deserialization — transitive via trafilatura,
no upstream fix available). Runs independently of lint/test.

**Why 9.5 and not 10:**

- HSTS handled by Caddy reverse proxy, not at app level (single point of failure
  if Caddy is bypassed)
- No SBOM generation for supply chain transparency

**Score change (Phase 2):** +0.5 from 9.0 — CSP violation reports and pip-audit
close the two gaps identified in the initial assessment.

---

## 3. Architecture — 8.5/10

**Layer separation verified by import graph:**

```text
Routes (web/_*.py)
  imports from: _core (auth guards), actions/*, sync/*
  does NOT import from: agent/core, stores directly (except settings_store
  in _settings.py for runtime config — acceptable)

Agent (agent/core.py, agent/context.py)
  imports from: agent/tools/*, actions/*, config, memory/*
  does NOT import from: web/*, main

Actions (actions/*.py)
  imports from: config, external SDKs (httpx, openai)
  does NOT import from: web/*, agent/*, stores

Stores (*_store.py, memory/store.py)
  imports from: asyncpg only
  does NOT import from: anything in niles.*
```

No circular imports detected. Dependency arrows point strictly downward.

**Tool handler registry** (`agent/tools/__init__.py`):

```python
ToolHandler = Callable[[dict, str, ToolContext], Awaitable[dict]]
TOOL_REGISTRY: dict[str, ToolHandler] = {}

def register_tool(name: str):
    def decorator(func: ToolHandler) -> ToolHandler:
        TOOL_REGISTRY[name] = func
        return func
    return decorator
```

Each tool handler is an async function with signature
`async def handle_X(args, chat_id, ctx) -> dict`. The agent calls
`TOOL_REGISTRY[name](args, chat_id, ctx)` — no switch/case, no agent
knowledge of tool internals. 10 handler modules auto-registered via
side-effect imports in `__init__.py`.

**Web feature modules** (`web/__init__.py`):
Side-effect imports register routes on shared `router`. Each module imports
`router` from `_core` and decorates its handlers. The `__init__.py` only
re-exports public names — no logic.

**Why 8.5 and not higher:**

- `main.py` lifespan handler initializes 18+ app.state attributes —
  a factory or builder pattern would be cleaner
- No explicit service layer for CRUD operations — routes call stores directly
  for simple read/write, which is pragmatic but skips validation

---

## 4. DevOps — 9.5/10

**Docker** (`docker/Dockerfile.niles`):

- Multi-stage (3 stages): Builder (compiles Tailwind + installs deps),
  gws-downloader (fetches gws binary with SHA256 verification), runtime
- Base image pinned with SHA256 digest: `python:3.12-slim@sha256:...`
- Non-root user: `useradd --uid 1000 niles`, `USER niles`
- HEALTHCHECK: `curl -f http://localhost:8000/health`
- Tailwind binary SHA256-verified

**CI** (`.github/workflows/ci.yml`):

Pipeline stages: Ruff lint → Ruff format → mypy → pytest + coverage →
TruffleHog secret scan → Trivy container scan → pip-audit dependency audit.
All required to pass.

**Pre-commit** (`.pre-commit-config.yaml`):

5 hooks: TruffleHog, PII check, Ruff lint, Ruff format, mypy. Run on
every commit.

**Migrations** (`main.py`):

Alembic version check at startup. If the DB schema doesn't match the latest
migration, the app crashes immediately — no silent schema drift.

**Dependency vulnerability scanning** (`.github/workflows/ci.yml`):

`dependency-audit` CI job runs `pip-audit --desc --skip-editable` independently
of lint/test. Fails on any known vulnerability in the dependency tree.

**Renovate** (`renovate.json`):

Configured with `config:recommended` + `docker:pinDigests` +
`helpers:pinGitHubActionDigests`. devDeps patch auto-merge, major updates
require dashboard approval.

**Why 9.5 and not 10:**

- No staging environment or blue/green deployment
- No documented rollback procedure

**Score change (Phase 2):** +0.5 from 9.0 — pip-audit in CI and Renovate close
the dependency management gaps.

---

## 5. UI/UX — 8.0/10

**Responsive design present** — Tailwind breakpoint classes across templates:

```text
base.html        flex items-center gap-2 sm:gap-4
chat.html        max-w-3xl mx-auto px-4 sm:px-6
settings.html    grid grid-cols-1 md:grid-cols-2
```

Viewport meta tag present (`base.html`). Mobile-first layout.

**HTMX integration well-structured** — 17 templates split into full pages
and fragments. Fragment templates (`fragments/*.html`) return partial HTML
for HTMX swaps. No full-page reloads for interactive actions.

**Accessibility improvements (Phase 1, PR #45):**

- 32 `<label>` elements across forms (login, settings, admin, weather,
  CalDAV, Vikunja, Notion). Many use `sr-only` class for visually hidden
  labels on inputs that already have placeholders.
- 10 `aria-label` attributes: theme toggle, settings toggles, chat nav,
  channel selector, search toggle, send button.
- 7 `role` attributes: `role="alert"` on error messages, `role="status"` on
  success messages, `role="combobox"` on autocomplete, `role="log"` on chat
  container.
- Skip-to-content link in `base.html`: visually hidden, visible on focus,
  links to `#main-content`.
- 7 `scope="col"` on admin table headers.

**Why 8.0 and not higher:**

- No automated accessibility testing (axe-core not in CI)
- No focus management after HTMX content swaps (`hx-on::after-settle` not used)
- `aria-live` only on chat container — HTMX toast notifications may not be
  announced to screen readers

**Why 8.0 and not lower:**

Semantic HTML, form labels, ARIA attributes, skip-link, and table scopes
cover the fundamental accessibility requirements. The remaining gaps are
in dynamic content announcement and automated testing.

**Score change (Phase 1):** +1.0 from 7.0 — comprehensive accessibility
pass addresses BFSG/EU Accessibility Act basics.

---

## 6. Maintainability — 8.5/10

**Test suite:**

- 782 test functions across 48 files (36 unit + 9 integration + 3 E2E)
- Code-to-test ratio: ~12,528 LOC source / ~13,405 LOC tests = 1:1.07
- Coverage threshold: 65% minimum enforced in CI (`pyproject.toml`)
- Test categories: unit tests for stores, agent core, security, calendar sync,
  web routes, signal integration, migrations, Notion RAG, Google MCP pool,
  integration tests (multi-component), E2E tests (Docker-based)

**Modules with tests vs without:**

| Module                 | Test file                    | Tests |
|------------------------|------------------------------|-------|
| agent/core.py          | test_core.py                 | ~120  |
| web routes             | test_web.py                  | ~63   |
| security               | test_security.py             | ~40   |
| calendar manager       | test_calendar_manager        | ~50   |
| CalDAV sync            | test_caldav.py               | ~30   |
| iCal parser            | test_ical_parser.py          | ~40   |
| Signal                 | test_signal.py               | ~25   |
| Settings store         | test_settings_store          | ~20   |
| Contacts               | test_contacts.py             | ~25   |
| MCP / Google pool      | test_mcp, test_user_mcp_pool | ~40   |
| Notion RAG             | 5 test files                 | ~80   |
| Docker deployment      | tests/e2e/ (3 files)         | ~30   |

**Structured logging** (`logging_config.py`):
structlog configured with JSON renderer, context variable merging, and
request ID injection. Third-party loggers (httpx, httpcore) silenced at
WARNING level. All app code uses `logging.getLogger(__name__)` which
routes through structlog processors.

**Type checking:**

mypy enabled with 10 per-module override blocks (down from 12 — `web.*` and
`sync.caldav` overrides removed in Phase 1). `AppState` Protocol
(`types.py`) provides typed access to `app.state` attributes, replacing
untyped `request.app.state.X` patterns in web routes.

Remaining overrides: `sync.manager`, `main`, `sync.ical_parser`,
`sync.carddav`, `agent.core`, `agent.prompts`, `jobs.briefing`,
`actions.tasks`, `cli`, `mcp.client`.

**Why 8.5 and not higher:**

- 10 mypy override modules still suppress real type errors
- No architecture documentation or ADRs
- 65% coverage threshold is modest (CLAUDE.md spec: 70-80%)

**Why 8.5 and not lower:**

- 782 tests with good behavior-oriented style (+31% since Phase 2)
- Integration tests (9 files) and E2E tests (3 files) add multi-layer coverage
- structlog JSON logging is production-ready
- AppState Protocol and removal of `web.*` overrides show type safety
  trend is improving
- MCP and Notion components have dedicated test coverage

**Score change (Phase 1):** +0.5 from 8.0 — AppState Protocol and
removal of 2 mypy override groups improve type safety.

---

## 7. Observability — 7.0/10

**Prometheus metrics** (`metrics.py`, 40 lines):

```python
REQUESTS      = Counter("niles_http_requests_total", ..., ["method", "endpoint", "status"])
LATENCY       = Histogram("niles_http_request_duration_seconds", ..., ["method", "endpoint"])
LLM_LATENCY   = Histogram("niles_llm_request_duration_seconds")
LLM_TOKENS    = Counter("niles_llm_tokens_total", ..., ["type"])  # prompt/completion
TOOL_CALLS    = Counter("niles_tool_calls_total", ..., ["tool_name", "success"])
ACTIVE_SSE    = Gauge("niles_active_sse_connections")
```

Metrics endpoint at `/metrics`. HTTP middleware records request count and
latency for every request. LLM metrics recorded in agent core after each
inference call.

**Health endpoints:**

- `/health`: Returns DB pool stats (size, free, used). No external service
  dependency — appropriate for liveness probe.
- `/ready`: Checks DB connectivity + Alembic migration version. Returns error
  list if not ready.

**Logging:**

Structured JSON to stdout via structlog. Request ID generated per request.

**Why 7.0 and not higher:**

- No error tracking service — unhandled exceptions only appear in container
  logs. No alerting, no aggregation, no stack trace grouping. This is the
  single biggest operational gap.
- Request ID not consistently threaded through all async code paths
- No distributed tracing (acceptable for single-instance, but limits
  debugging of multi-service interactions)

**Why 7.0 and not lower:**

6 well-chosen Prometheus metrics cover the key operational signals (RED:
Rate, Errors, Duration). Health endpoints follow Kubernetes liveness/readiness
conventions. Structured logging is the right foundation.

---

## 8. Resilience — 8.0/10

**Timeouts — comprehensive:**

| Service          | Timeout             | Location                        |
|------------------|---------------------|---------------------------------|
| Ollama LLM       | SDK default (~120s) | agent/core.py (OpenAI SDK)      |
| Evolution API    | 30s                 | http_clients.py (shared client) |
| Signal API       | 10-30s              | actions/signal.py               |
| CalDAV servers   | 60s                 | sync/caldav.py                  |
| Google OAuth     | 30s                 | http_clients.py (shared client) |
| MCP subprocesses | 30s                 | mcp/client.py                   |
| Weather API      | 10s                 | http_clients.py (shared client) |
| Geocoding API    | 5s                  | http_clients.py (shared client) |
| Vikunja API      | 10s                 | actions/tasks.py                |

Every external HTTP call has an explicit timeout. No unbounded waits.

**Retry logic (Phase 1, PR #45):**

`@retry_http` decorator (`http_retry.py`) using tenacity:
- Retries on: `ConnectError`, `ConnectTimeout`, `ReadTimeout`, `WriteTimeout`,
  `PoolTimeout`, and `HTTPStatusError` with status >= 500
- Strategy: exponential jitter (initial=1s, max=10s, jitter=2s), max 3 attempts

Applied to 8 callables across 5 modules:

| Module                | Decorated methods                         |
|-----------------------|-------------------------------------------|
| sync/carddav.py       | 2 methods (propfind + vCard fetch)         |
| sync/caldav.py        | 2 methods (REPORT + propfind)             |
| sync/manager.py       | 1 method (ICS fetch)                      |
| actions/briefing.py   | 2 methods (weather + Vikunja tasks fetch) |
| mcp/weather/server.py | 1 function (Open-Meteo data fetch)        |

**Graceful shutdown** (`main.py`):

`shutdown_event` is an `asyncio.Event` set during lifespan teardown. All
long-running tasks (Signal listener, SSE streams) check this event between
iterations and exit cleanly. DB pool and HTTP clients closed on shutdown.

**Signal WebSocket reconnection** (`sources/signal.py`):

Exponential backoff (5s initial, 60s max) on WebSocket disconnects.

**Why 8.0 and not higher:**

- No circuit breakers — a consistently failing CalDAV server gets hammered
  on every sync cycle with no backoff beyond the per-request retry
- Ollama has no retry — a transient LLM timeout is an immediate error
- No bulkhead: one slow external call can't exhaust the event loop but
  there's no isolation between service call paths

**Why 8.0 and not lower:**

Timeouts are comprehensive, retry logic covers 5 of the 6 external service
integration modules, graceful shutdown works correctly, and Signal
reconnection demonstrates the right pattern. For a self-hosted single-user
app, the remaining gaps are low-probability scenarios.

**Score change (Phase 1):** +1.5 from 6.5 — retry decorator applied to
all sync and briefing modules. The biggest resilience gap (zero retries
on transient failures) is now addressed for the most critical paths.

---

## 9. Performance — 8.5/10

**Async consistency — verified:**

All I/O operations use async: asyncpg for DB, httpx for HTTP, OpenAI SDK
for LLM calls. No `time.sleep()`, no synchronous `requests` library, no
blocking file I/O in async handlers.

**Connection pooling:**

DB pool (`main.py`): asyncpg with min=2, max=10 connections. Pool stats
exposed via `/health` endpoint.

**Shared HTTP clients (Phase 1, PR #45):**

`HttpClients` container (`http_clients.py`) manages 5 long-lived
`httpx.AsyncClient` instances:

| Client         | Purpose                | Timeout |
|----------------|------------------------|---------|
| `evolution`    | Evolution/WhatsApp API | 30s     |
| `open_meteo`   | Weather data           | 10s     |
| `geocoding`    | Location search        | 5s      |
| `google_oauth` | Google OAuth flows     | 30s     |
| `general`      | General-purpose        | 10s     |

Created once in `main.py` lifespan, stored at `app.state.http_clients`,
closed via `close_all()` on shutdown. TCP connection reuse across requests.

**Remaining per-request clients — 3 occurrences:**

| File                         | Reason                                |
|------------------------------|---------------------------------------|
| vikunja_provisioning.py      | Per-user base_url (can't share)       |
| mcp/weather/server.py        | MCP subprocess (separate process)     |
| mcp/fetch/server.py          | MCP subprocess (separate process)     |

All 3 are outside the main FastAPI request path. The MCP servers run as
separate stdio subprocesses and can't share the main app's clients.

**SSE streaming** (`web/_chat.py`):

Proper async generator with gauge tracking. Shutdown event checked between
chunks. StreamingResponse with `X-Accel-Buffering: no` for reverse proxy
compatibility.

**Calendar source cache:**
`ContextBuilder` caches calendar source names with a 5-minute TTL, avoiding
a DB query on every chat message.

**Why 8.5 and not higher:**

- No caching for settings, user lookups, or contact lists
- Ollama model list fetched on every request
- 65% coverage threshold doesn't include performance regression tests

**Why 8.5 and not lower:**

Async is correct and consistent. DB pooling is properly configured. 5 shared
HTTP clients eliminate per-request TCP overhead for all main request paths.
SSE streaming is well-implemented with backpressure awareness.

**Score change (Phase 1):** +1.0 from 7.5 — shared httpx clients eliminate
the 15+ per-request client instances that were creating and destroying TCP
connections on every external API call.

---

## 10. API Design — 8.0/10

**REST conventions followed for internal API:**

```text
GET  /ui/chat              → chat page
GET  /api/chat/history     → paginated history (offset, limit)
POST /api/chat             → send message (non-streaming)
POST /api/chat/stream      → send message (SSE)
POST /api/chat/clear       → clear history

GET  /api/calendar/sources → list sources
POST /api/calendar/sources → add source
DELETE /api/calendar/sources/{id} → remove source

GET  /api/admin/users      → user list page
POST /api/admin/users      → create user
DELETE /api/admin/users/{id} → delete user
```

Consistent URL structure. Resources are nouns, actions are HTTP verbs.

**Pagination** implemented on:

- Chat history: `offset` + `limit=20` (`web/_chat.py`)
- User list: `limit=100, offset=0` (`user_store.py`)
- Memory store: `limit=200, offset=0` (`memory/store.py`)

**Unified error format (Phase 2, PR #46):**

JSON API error paths use the CLAUDE.md-specified envelope (`errors.py`):

```json
{"error": {"code": 429, "message": "Too many requests", "details": null}}
```

Applied to: `_api_exception_handler` (all HTTPExceptions), `RateLimitMiddleware`
(429), webhook auth (401). Helper function `error_response()` prevents format
drift.

HTMX endpoints correctly return template fragments (toast, redirect headers) —
these are the right format for HTMX interactions, not API responses.

**Why 8.0 and not higher:**

- No OpenAPI schema curation (auto-generated by FastAPI, but not documented
  or versioned)
- HTMX endpoints use different error patterns by design, but this creates
  two "styles" of error handling in the same codebase

**Why 8.0 and not lower:**

- REST conventions are correct where used
- Pagination implemented on all list endpoints
- Unified JSON error envelope per CLAUDE.md spec on all API error paths
- URL structure is consistent and predictable

**Score change (Phase 2):** +0.5 from 7.5 — unified error format addresses
the primary gap. The remaining HTMX/API duality is by design.

---

## Improvement Roadmap

### Phase 1 — Quick Wins (done, PR #45)

| #   | Dimension       | Before | After | Measure                                                                          |
|-----|-----------------|--------|-------|----------------------------------------------------------------------------------|
| 1   | Resilience      | 6.5    | 8.0   | `@retry_http` decorator (tenacity) on 8 callables across 5 modules              |
| 2   | Performance     | 7.5    | 8.5   | `HttpClients` container with 5 shared clients, replacing 15+ per-request clients |
| 3   | UI/UX           | 7.0    | 8.0   | 31 labels, 9 aria-labels, 7 roles, skip-link, table scopes                      |
| 4   | Maintainability | 8.0    | 8.5   | `AppState` Protocol, removed `web.*` and `sync.caldav` mypy overrides            |

### Phase 2 — Structural Improvements (done, PR #46)

| #   | Dimension        | Before | After | Measure                                                                     |
|-----|------------------|--------|-------|-----------------------------------------------------------------------------|
| 5   | KISS / Complexity| 7.5    | 8.5   | Split NilesAgent into `core.py`, `context.py`, `text_tool_parser.py`        |
| 6   | API Design       | 7.5    | 8.0   | Unified `{"error": {"code", "message", "details"}}` via `errors.py`         |
| 7   | DevOps           | 9.0    | 9.5   | `pip-audit` CI job + Renovate configured                                    |
| 8   | Security         | 9.0    | 9.5   | CSP `report-uri /csp-report` endpoint + pip-audit                           |

### Phase 3 — Long-term (7.0-8.5 → ~9.0 avg)

| #   | Dimension       | Score | Measure                                                                | Effort |
|-----|-----------------|-------|------------------------------------------------------------------------|--------|
| 9   | Observability   | 7.0   | Error tracking (Sentry/GlitchTip self-hosted), consistent request IDs  | Large  |
| 10  | Architecture    | 8.5   | Extract `main.py` lifespan into builder/factory pattern                | Medium |
| 11  | Maintainability | 8.5   | Reduce remaining 10 mypy overrides, raise coverage to 70%              | Medium |
| 12  | UI/UX           | 8.0   | axe-core in CI, HTMX focus management, aria-live on toasts             | Small  |
| 13  | Performance     | 8.5   | Settings/contact caching, Ollama model list caching                    | Small  |
| 14  | Resilience      | 8.0   | Circuit breakers for CalDAV, Ollama retry with backoff                 | Medium |

---

## Methodology

- **Data source:** Automated codebase analysis (grep for patterns, line counts,
  import graph traversal) combined with manual code review of critical paths.
  File paths cited for every claim.
- **Scoring:** 1-10 scale per dimension. Weighted average uses 1.3x multiplier
  for Security, Architecture, Maintainability (highest impact on project
  longevity); 0.8x for UI/UX (lower weight for backend-focused project);
  1.0x for all others.
- **Trend:** Delta compared to post-web-split baseline (2026-03-02). Dimensions
  unchanged since that baseline show "=".
- **Bias disclosure:** This assessment was performed by the same tool that
  implemented PRs #43-#46. Findings should be validated independently.
  Scores may be biased toward overvaluing recent improvements.
