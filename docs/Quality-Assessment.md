# Technical Quality Assessment

> Last updated: 2026-03-02 | After PR #43 (Tool-Handler-Registry) + PR #44 (Web-Package-Split)

## Score Overview

| Dimension          | Score | Trend   | Next Lever                          |
|--------------------|-------|---------|-------------------------------------|
| KISS / Complexity  | 7.5   | +1.0    | Split `NilesAgent` in `core.py`     |
| Security           | 9.0   | =       | CSP violation reports, dep audit    |
| Architecture       | 8.5   | =       | Extract `main.py` startup logic     |
| DevOps             | 9.0   | =       | Renovate / Dependabot               |
| UI/UX              | 7.0   | -0.5    | Accessibility audit (axe-core)      |
| Maintainability    | 8.0   | +1.0    | Reduce mypy exclusions              |
| Observability      | 7.0   | new     | Sentry or equivalent                |
| Resilience         | 6.5   | new     | Retry logic for external services   |
| Performance        | 7.5   | new     | Shared httpx client, caching        |
| API Design         | 7.5   | new     | Unified error response format       |

**Average: 7.7/10** | Weighted (Security, Architecture, Maintainability x1.3; UI x0.8): **7.9/10**

---

## History

| Date       | Event                        | Score |
|------------|------------------------------|-------|
| 2026-02-28 | Initial evaluation (6 dims)  | 7.8   |
| 2026-03-01 | After core.py refactoring    | 8.2   |
| 2026-03-02 | +4 new dimensions, web split | 7.9   |

The apparent drop from 8.2 to 7.9 is due to adding four new dimensions
(Observability, Resilience, Performance, API Design) that score lower. The
original 6 dimensions alone remain at **8.2**.

---

## 1. KISS / Complexity — 7.5/10

| Metric              | Value                                |
|---------------------|--------------------------------------|
| Largest file        | `agent/core.py` — 1,126 LOC         |
| Average file size   | 302 LOC (69 files)                   |
| Web module max      | 382 LOC (`_calendar.py`) — was 2,444 |
| Direct dependencies | 22 (pyproject.toml)                  |
| Call chain depth    | 5-6 layers typical                   |

### Evidence

**Why 7.5 and not higher:**

The biggest complexity problem (web.py at 2,444 LOC) is resolved, but
`agent/core.py` remains at 1,126 LOC with the `NilesAgent` class spanning
lines 351-1126 (775 LOC). This class has too many responsibilities:

- Event routing: `process_event()` at line 953 dispatches by event type
- Tool-call loop: `_run_tool_loop()` iterates up to 5 rounds of LLM calls
- Context building: `_build_system_prompt()` assembles calendar, contacts, memory
- Streaming: `process_event_stream()` handles SSE chunking + JSON buffering

`main.py` at 641 LOC mixes app factory, middleware setup, lifespan management,
health endpoints, and metrics endpoint in one file.

**Why 7.5 and not lower:**

- Average file size (302 LOC) is healthy — 80% of files are under 400 LOC
- Call chain depth of 5-6 layers is reasonable for this domain complexity
- 22 direct dependencies is disciplined for a project integrating 6 external
  services (Ollama, Evolution API, Signal, CalDAV, Google, Vikunja)
- The web split (13 modules, max 382 LOC) demonstrates the target structure

**Score change:** +1.0 from 6.5 — web.py split eliminated the single worst
offender. core.py prevents a higher score.

---

## 2. Security — 9.0/10

### Evidence

**SQL injection — fully mitigated:**

Every SQL query uses asyncpg positional parameters. Verified across all stores:

```
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

CSP policy (`main.py:477-495`):
```
default-src 'self';
script-src 'nonce-{nonce}' 'strict-dynamic' 'self';
style-src 'self';
img-src 'self' data: https://*.googleusercontent.com;
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

- Global: `RateLimitMiddleware` at `main.py:453-470`, 60 req/min per IP
- Login: 5 attempts per 5 minutes per IP (`_auth.py:42-52`), with cleanup
  of expired entries to prevent memory leak

**Security headers** (`main.py:473-478`):
```
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: camera=(), microphone=(), geolocation=()
```

**Why 9.0 and not 10:**

- No CSP violation reporting (`report-uri`/`report-to`) — attacks go unnoticed
- No dependency vulnerability scanning (only container-level Trivy)
- HSTS handled by Caddy reverse proxy, not at app level (single point of failure
  if Caddy is bypassed)

---

## 3. Architecture — 8.5/10

### Evidence

**Layer separation verified by import graph:**

```
Routes (web/_*.py)
  imports from: _core (auth guards), actions/*, sync/*
  does NOT import from: agent/core, stores directly (except settings_store
  in _settings.py for runtime config — acceptable)

Agent (agent/core.py)
  imports from: agent/tools/*, actions/*, config
  does NOT import from: web/*, main

Actions (actions/*.py)
  imports from: config, external SDKs (httpx, openai)
  does NOT import from: web/*, agent/*, stores

Stores (*_store.py, memory/store.py)
  imports from: asyncpg only
  does NOT import from: anything in niles.*
```

No circular imports detected. Dependency arrows point strictly downward.

**Tool handler registry** (`agent/tools/__init__.py:54-68`):

```python
TOOL_REGISTRY: dict[str, ToolHandler] = {}

def register_tool(*names):
    def decorator(cls):
        for name in names:
            TOOL_REGISTRY[name] = cls()
        return cls
    return decorator
```

Each tool handler is a class implementing `async def run(self, agent, args)`.
The agent calls `TOOL_REGISTRY[name].run(...)` — no switch/case, no agent
knowledge of tool internals.

**Web feature modules** (`web/__init__.py`):

Side-effect imports register routes on shared `router`:
```python
from . import _admin, _auth, _briefing, _calendar, _chat, ...
```

Each module imports `router` from `_core` and decorates its handlers. The
`__init__.py` only re-exports public names — no logic.

**Why 8.5 and not higher:**

- `NilesAgent` (775 LOC) mixes orchestration with context assembly
- `main.py` lifespan handler (lines 72-306) initializes 15+ app.state
  attributes — a factory or builder pattern would be cleaner
- No explicit service layer for CRUD operations — routes call stores directly
  for simple read/write, which is pragmatic but skips validation

---

## 4. DevOps — 9.0/10

### Evidence

**Docker** (`docker/Dockerfile.niles`):

- Multi-stage: Builder (lines 1-27) compiles Tailwind + installs deps;
  runtime (lines 29+) copies only artifacts
- Base image pinned with SHA256 digest (line 2):
  `python:3.12-slim@sha256:f3fa41d...`
- Non-root user (lines 51-56): `useradd --uid 1000 niles`, `USER niles`
- HEALTHCHECK (lines 61-62): `curl -f http://localhost:8000/health`
- Tailwind binary SHA256-verified (lines 18-26)

**CI** (`.github/workflows/ci.yml`):

Pipeline stages: Ruff lint -> Ruff format -> mypy -> pytest + coverage ->
TruffleHog secret scan -> Trivy container scan. All required to pass.

**Pre-commit** (`.pre-commit-config.yaml`):

5 hooks: TruffleHog, PII check, Ruff lint, Ruff format, mypy. Run on
every commit — verified by the commit attempts during this session where
hooks caught ruff and mypy issues.

**Migrations** (`main.py:114-125`):

Alembic version check at startup. If the DB schema doesn't match the latest
migration, the app crashes immediately — no silent schema drift.

**Why 9.0 and not 10:**

- No Renovate/Dependabot for automated dependency updates
- No staging environment or blue/green deployment
- No documented rollback procedure
- No `pip audit` or `safety` check in CI for Python dependency vulnerabilities

---

## 5. UI/UX — 7.0/10

### Evidence

**Responsive design present** — Tailwind breakpoint classes found across templates:

```
base.html:24    flex items-center gap-2 sm:gap-4
chat.html:15    max-w-3xl mx-auto px-4 sm:px-6
settings.html   grid grid-cols-1 md:grid-cols-2
```

Viewport meta tag present (`base.html:6`). Mobile-first layout.

**HTMX integration well-structured** — 17 templates split into full pages
and fragments. Fragment templates (`fragments/*.html`) return partial HTML
for HTMX swaps. No full-page reloads for interactive actions.

**Accessibility gaps** — verified by searching templates:

- `aria-label` found only once: theme toggle button (`base.html:41`)
- Zero `<label for="...">` elements across all form inputs (login, settings,
  admin forms). Inputs use placeholder text instead of labels.
- No `role` attributes on custom widgets
- No skip-to-content link in `base.html`
- No focus management after HTMX content swaps (`hx-on::after-settle` not used)

**Why 7.0 and not the previous 7.5:**

The initial assessment noted "Tailwind, responsive, HTMX" as strengths without
deeply checking accessibility. Closer inspection reveals the gaps above are
more significant — EU Accessibility Act (BFSG) compliance requires form labels
and ARIA attributes. Correcting the score to reflect reality.

---

## 6. Maintainability — 8.0/10

### Evidence

**Test suite:**

- 577 test functions across 28 files (`tests/test_*.py`)
- Code-to-test ratio: ~21,200 LOC source / ~18,900 LOC tests = 1:0.89
- Coverage threshold: 65% minimum enforced in CI (`pyproject.toml:155`)
- Test categories: unit tests for stores, agent core, security, calendar sync,
  web routes, signal integration, migrations

**Modules with tests vs without:**

| Module                 | Test file              | Tests |
|------------------------|------------------------|-------|
| agent/core.py          | test_core.py           | ~120  |
| web routes             | test_web.py            | 63    |
| security               | test_security.py       | ~40   |
| calendar manager       | test_calendar_manager  | ~50   |
| CalDAV sync            | test_caldav.py         | ~30   |
| iCal parser            | test_ical_parser.py    | ~40   |
| Signal                 | test_signal.py         | ~25   |
| Settings store         | test_settings_store    | ~20   |
| Contacts               | test_contacts.py       | ~25   |
| **MCP subprocesses**   | **none**               | 0     |
| **Docker deployment**  | **none (no E2E)**      | 0     |

**Structured logging** (`logging_config.py:1-60`):

structlog configured with JSON renderer, context variable merging, and
request ID injection. Third-party loggers (httpx, httpcore) silenced at
WARNING level. All app code uses `logging.getLogger(__name__)` which
routes through structlog processors.

**Type checking:**

mypy enabled but with per-module overrides disabling certain checks:
```toml
[[tool.mypy.overrides]]
module = ["niles.sources.web.*"]
disable_error_code = ["union-attr", "index", "arg-type"]
```

This means type safety is partially enforced — better than nothing, but
real type errors could hide behind the exclusions.

**Why 8.0 and not higher:**

- mypy exclusions for 3 core modules weaken type safety guarantees
- No architecture documentation or ADRs
- 15+ copy-pasted `async with httpx.AsyncClient(timeout=X)` blocks
- 65% coverage threshold is modest (industry standard: 70-80%)

**Score change:** +1.0 from 7.0 — web split reduced file sizes, tool registry
improved code organization, both refactorings made the codebase more navigable.

---

## 7. Observability — 7.0/10

### Evidence

**Prometheus metrics** (`metrics.py`, 40 lines):

```python
REQUESTS      = Counter("niles_http_requests_total", ..., ["method", "endpoint", "status"])
LATENCY       = Histogram("niles_http_request_duration_seconds", ..., ["method", "endpoint"])
LLM_LATENCY   = Histogram("niles_llm_request_duration_seconds")
LLM_TOKENS    = Counter("niles_llm_tokens_total", ..., ["type"])  # prompt/completion
TOOL_CALLS    = Counter("niles_tool_calls_total", ..., ["tool_name", "success"])
ACTIVE_SSE    = Gauge("niles_active_sse_connections")
```

Metrics endpoint at `/metrics` (`main.py:571`). HTTP middleware records
request count and latency for every request. LLM metrics recorded in
agent core after each inference call.

**Health endpoints:**

- `/health` (`main.py:582-594`): Returns DB pool stats (size, free, used).
  No external service dependency — appropriate for liveness probe.
- `/ready` (`main.py:597-625`): Checks DB connectivity + Alembic migration
  version. Returns error list if not ready.

**Logging:**

Structured JSON to stdout. Example output format:
```json
{"event": "...", "logger": "niles.agent.core", "level": "info",
 "timestamp": "2026-03-02T...", "request_id": "uuid"}
```

**Why 7.0 and not higher:**

- No error tracking service — an unhandled exception in production only
  appears in container logs. No alerting, no aggregation, no stack trace
  grouping. This is the single biggest operational gap.
- Request ID generated (`main.py:509`) but not consistently threaded through
  `structlog.contextvars` in all code paths — some async branches lose it.
- No distributed tracing (acceptable for single-instance, but limits
  debugging of multi-service interactions with Evolution API, Signal, etc.)

**Why 7.0 and not lower:**

6 well-chosen Prometheus metrics cover the key operational signals (RED:
Rate, Errors, Duration). Health endpoints follow Kubernetes liveness/readiness
conventions. Structured logging is the right foundation.

---

## 8. Resilience — 6.5/10

### Evidence

**Timeouts — comprehensive:**

| Service           | Timeout | Location                          |
|-------------------|---------|-----------------------------------|
| Ollama LLM        | SDK default (~120s) | agent/core.py (OpenAI SDK) |
| Evolution API     | 10s     | actions/whatsapp.py               |
| Signal API        | 10-30s  | actions/signal.py                 |
| CalDAV servers    | 30s     | sync/caldav.py                    |
| Google OAuth      | 10-30s  | web/_auth.py, web/_calendar.py    |
| MCP subprocesses  | 30s     | mcp/client.py:11                  |
| Weather API       | 10s     | mcp/weather/server.py             |
| Vikunja API       | 10s     | actions/tasks.py                  |

Every external HTTP call has an explicit timeout. No unbounded waits.

**Graceful shutdown** (`main.py:72-306`):

`shutdown_event` is an `asyncio.Event` set during lifespan teardown. All
long-running tasks (Signal listener, SSE streams) check this event between
iterations and exit cleanly. DB pool is closed on shutdown.

**Retry logic — only Signal:**

Signal WebSocket reconnection (`sources/signal.py:35-41`):
```python
backoff = 5
max_backoff = 60
backoff = min(backoff * 2, max_backoff)  # exponential
```

No other service has retry logic. A transient Ollama timeout or Evolution API
503 results in an immediate error to the user.

**Why 6.5 and not higher:**

- No retries for transient failures on 5 of 6 external services
- No circuit breakers — a consistently failing CalDAV server gets hammered
  on every sync cycle with no backoff
- Ollama down = instant failure for every chat message (no queue, no retry,
  no "try again in a moment" with automatic retry)
- No bulkhead: one slow `httpx.AsyncClient` call can exhaust the event loop
  if many requests arrive simultaneously

**Why 6.5 and not lower:**

Timeouts are comprehensive (no infinite hangs), graceful shutdown works
correctly, and the Signal reconnection shows the pattern is understood.
For a self-hosted single-user app, the risk of cascading failures is low.

---

## 9. Performance — 7.5/10

### Evidence

**Async consistency — verified:**

All I/O operations use async: asyncpg for DB, httpx for HTTP, OpenAI SDK
for LLM calls. No `time.sleep()`, no synchronous `requests` library, no
blocking file I/O in async handlers found.

**Connection pooling:**

DB pool (`main.py:101-109`): asyncpg with min=2, max=10 connections.
Pool stats exposed via `/health` endpoint.

HTTP clients: `httpx.AsyncClient` created per-request via context manager
(`async with httpx.AsyncClient() as client`). This means a new TCP connection
per external API call — no connection reuse across requests. Found 15+
instances of this pattern across web modules and actions.

**SSE streaming** (`web/_chat.py:162-226`):

```python
async def event_generator():
    ACTIVE_SSE.inc()
    try:
        async for item in agent.process_event_stream(event):
            data = json.dumps(item, ensure_ascii=False)
            yield f"data: {data}\n\n"
    finally:
        ACTIVE_SSE.dec()
```

Proper async generator with gauge tracking. Shutdown event checked between
chunks. StreamingResponse with `X-Accel-Buffering: no` for Nginx/Caddy
compatibility.

**Why 7.5 and not higher:**

- No caching at any level — settings, user lookups, calendar data, and
  Ollama model lists are fetched from DB/API on every request
- httpx clients not shared — each request creates and destroys a connection.
  For Ollama (same host), this wastes TCP setup overhead on every LLM call.
- No query result caching for frequently-read, rarely-written data like
  settings or contact lists

**Why 7.5 and not lower:**

Async is correct and consistent — no blocking calls. DB pooling is properly
configured. SSE streaming is well-implemented with backpressure awareness.
For a single-user self-hosted app, the missing caching doesn't cause
user-visible latency issues.

---

## 10. API Design — 7.5/10

### Evidence

**REST conventions followed for internal API:**

```
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

- Chat history: `offset` + `limit=20` (`web/_chat.py:90`)
- User list: `limit=100, offset=0` (`user_store.py:140`)
- Memory store: `limit=200, offset=0` (`memory/store.py:78`)

**Error response inconsistency:**

Some endpoints return JSON errors:
```python
raise HTTPException(status_code=401, detail="Session invalid")
# → {"detail": "Session invalid"}
```

Others return raw HTML:
```python
return Response(content="Passwort zu kurz.", status_code=400)
```

Others return HTMX template fragments:
```python
return templates.TemplateResponse(request, "fragments/toast.html",
    {"message": "...", "toast_type": "error"})
```

Three different error formats in one API. The CLAUDE.md specifies
`{ error: { code, message, details } }` — not implemented.

**Why 7.5 and not higher:**

- Three inconsistent error response formats
- No unified error envelope as specified in CLAUDE.md
- No OpenAPI schema curation (auto-generated by FastAPI, but not documented
  or versioned)

**Why 7.5 and not lower:**

- REST conventions are correct where used
- Pagination implemented on all list endpoints
- The hybrid HTMX/API approach is an intentional design choice, and
  HTMX fragment responses are the correct format for that interaction model
- URL structure is consistent and predictable

---

## Improvement Roadmap

### Phase 1 — Quick Wins (6.5-7.5 → ~8.0 avg)

| # | Dimension        | Score | Measure                                                        | Effort |
|---|------------------|-------|----------------------------------------------------------------|--------|
| 1 | Resilience       | 6.5   | Retry decorator for httpx calls (tenacity/stamina) — 5 services without retry | Small  |
| 2 | Performance      | 7.5   | Shared `httpx.AsyncClient` as app.state instead of 15+ per-request clients | Small  |
| 3 | UI/UX            | 7.0   | `<label for>` on all forms, `aria-label` on buttons, skip-to-content link | Small  |
| 4 | Maintainability  | 8.0   | Reduce mypy exclusions for `web.*` modules                     | Medium |

### Phase 2 — Structural Improvements (7.5-7.7 → ~8.3 avg)

| # | Dimension        | Score | Measure                                                        | Effort |
|---|------------------|-------|----------------------------------------------------------------|--------|
| 5 | KISS / Complexity| 7.5   | Split `NilesAgent` (775 LOC): context builder, tool loop, streaming as separate modules | Medium |
| 6 | API Design       | 7.5   | Unified error format `{ error: { code, message, details } }` per CLAUDE.md spec | Medium |
| 7 | DevOps           | 9.0   | Renovate + `pip-audit` in CI                                   | Small  |
| 8 | Security         | 9.0   | CSP `report-uri` endpoint + `pip-audit` in CI                  | Small  |

### Phase 3 — Long-term (7.0-8.5 → ~8.5+ avg)

| # | Dimension        | Score | Measure                                                        | Effort |
|---|------------------|-------|----------------------------------------------------------------|--------|
| 9 | Observability    | 7.0   | Error tracking (Sentry/GlitchTip self-hosted), consistent request IDs | Large  |
| 10| Architecture     | 8.5   | Extract `main.py` lifespan into builder/factory pattern        | Medium |

---

## Methodology

- **Data source:** Automated codebase analysis (grep for patterns, line counts,
  import graph traversal) combined with manual code review of critical paths.
  File paths and line numbers cited for every claim.
- **Scoring:** 1-10 scale per dimension. Weighted average uses 1.3x multiplier
  for Security, Architecture, Maintainability (highest impact on project
  longevity); 0.8x for UI/UX (lower weight for backend-focused project);
  1.0x for all others.
- **Trend:** Delta compared to previous assessment (2026-02-28 / 2026-03-01)
  where a prior score exists. "new" for dimensions added in this round.
- **Bias disclosure:** This assessment was performed by the same tool that
  implemented PR #43 and #44. Findings should be validated independently.
  Scores may be biased toward overvaluing recent improvements.
