# Technical Quality Assessment

> Last updated: 2026-06-11 | After Phase 2 Refactoring (PR #92) — God Function Extraction + Security Fixes
>
> **Note:** Scores below remain from the 2026-03-13 assessment. LOC metrics have been updated
> to reflect the Phase 2 refactoring. A full re-scoring is pending.

## Score Overview

| Dimension          | Score | Trend | Next Lever                                      |
|--------------------|-------|-------|-------------------------------------------------|
| KISS / Complexity  | 8.5   | =     | Extract `main.py` startup logic                 |
| Security           | 9.5   | =     | HSTS at app level, SBOM                         |
| Architecture       | 9.0   | +0.5  | Extract `main.py` lifespan into builder/factory |
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
| 2026-03-12 | Markdown-aware chunking + RAG docs (PR #57)    | 8.5   |
| 2026-03-13 | Action layer extraction (PRs #59, #60)          | 8.5   |

The drop from 8.2 to 7.9 (2026-03-02) was due to adding four new dimensions
(Observability, Resilience, Performance, API Design) that scored lower. Phase 1
raised 4 weak dimensions (Resilience +1.5, Performance +1.0, UI +1.0,
Maintainability +0.5). Phase 2 raised 4 structural dimensions (KISS +1.0,
Security +0.5, DevOps +0.5, API Design +0.5).

Architecture +0.5 (2026-03-13) from action layer extraction — 12 action modules
now mediate between routes and stores.

Phase 2 Refactoring (2026-06-11, PR #92) extracted `startup.py` (499 LOC) from
`main.py` (now 448 LOC) and `tool_defs.py` (322 LOC) from `agent/core.py` (now
557 LOC). License changed from MIT to AGPL-3.0-only. Added Fernet credential
encryption, gitleaks + detect-secrets to pre-commit, SBOM generation in CI.

---

## 1. KISS / Complexity — 8.5/10

| Metric              | Value                                                          |
|---------------------|----------------------------------------------------------------|
| Largest file        | `agent/core.py` — 557 LOC (was 866, tool_defs.py extracted)   |
| Second largest      | `startup.py` — 499 LOC (extracted from main.py)               |
| Third largest       | `main.py` — 448 LOC (was 802, startup.py extracted)           |
| Agent modules       | `core.py` 557, `tool_defs.py` 322, `context.py` ~346          |
| Web module max      | 388 LOC (`_notion.py`) — was 2,444                             |
| Direct dependencies | 25 production + 8 dev (pyproject.toml)                         |
| Avg file size       | ~140 LOC across 97 Python files                                |
| File size dist.     | No files > 600 LOC (was 2 files > 800 LOC)                    |

### Evidence

**Why 8.5 and not higher:**

`main.py` at 802 LOC still mixes app factory, middleware setup, lifespan
management, health endpoints, and metrics endpoint in one file. The lifespan
handler initializes 34 `app.state` attributes (grew with action layer wiring:
`vikunja_setup_action`, `contacts_action`, `settings_action`, `weather_action`,
`admin_action`). Four files are in the 400-799 LOC range (`caldav.py` 489,
`briefing.py` 461, `notion_embeddings.py` 410, `user_pool.py` 366).

**Why 8.5 and not lower:**

- NilesAgent split into 3 focused modules: `core.py` (orchestration, ~486 LOC
  class + 340 LOC TOOLS constant), `context.py` (context assembly, user/resource
  resolution), `text_tool_parser.py` (pure functions for JSON tool-call detection)
- 94% of files under 400 LOC, 74% under 200 LOC (improved from 90%/73%)
- Web modules slimmed: 5 route files reduced by action extraction
  (`_contacts.py` 176, `_vikunja.py` 116, `_settings.py` 168, `_weather.py` 131,
  `_admin.py` 155). Max web module 388 LOC (`_notion.py`)

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
`_NilesTemplates` class (`web/_core.py:31-37`) injects a CSP nonce into every
template context, which the base template uses for inline scripts.

CSP policy (`main.py:577-586`):

```text
default-src 'self';
script-src 'nonce-{nonce}' 'strict-dynamic' 'self';
style-src 'self';
img-src 'self' data: https://*.googleusercontent.com;
font-src 'self';
connect-src 'self';
base-uri 'self';
form-action 'self';
report-uri /csp-report
```

No `'unsafe-inline'` for scripts. `'strict-dynamic'` allows nonce-approved
scripts to load dependencies. `base-uri 'self'` and `form-action 'self'`
restrict base tag hijacking and form target manipulation.

**CSRF — double-submit with timing-safe comparison:**

`_verify_csrf()` at `web/_core.py:116-122` compares header `x-csrf-token`
against cookie value using `hmac.compare_digest()`, preventing timing attacks.
CSRF token generated via `secrets.token_urlsafe(32)`. Cookie uses
`samesite="strict"`. Applied to all POST/DELETE/PATCH handlers via
`_require_auth_and_csrf()`.

**Authentication:**

- Argon2 password hashing (`_auth.py:102,112,144`)
- Timing defense: dummy hash on failed lookup (`_auth.py:112`) prevents
  user enumeration via response time
- Password policy: minimum 8 characters enforced (`_auth.py:72-80`)
- Session cookies: `httponly=True` (`_core.py:106-113`), `secure` based on
  `_is_secure_context()` (`_core.py:65-70`), `samesite=lax` (`_core.py:112`)
- Cookie size guard: rejects tokens > 4096 bytes (`_core.py`)
- OAuth state cookie: 600s max_age, httponly=True, signed (`_auth.py:165-172`)

**Rate limiting:**

- Global: `RateLimitMiddleware` at `main.py`, 60 req/min per IP,
  10,000 IP limit with eviction, pruning of expired entries
- Login: 5 attempts per 5 minutes per IP (`_auth.py:36-56`), with cleanup
  of expired entries to prevent memory leak
- Exempt: `/health`, `/ready`, `/static` skip rate limiting

**Security headers** (`main.py:563-588`):

```text
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: camera=(), microphone=(), geolocation=()
X-Request-ID: <per-request UUID>
```

Middleware execution order: RequestIdMiddleware → RateLimitMiddleware →
SecurityHeadersMiddleware → MetricsMiddleware.

**CSP violation reporting** (`main.py:765-784`):

`report-uri /csp-report` directive in CSP header. The `POST /csp-report`
endpoint logs violations at WARNING level and returns 204. Gracefully handles
malformed JSON. Rate limiting applies via existing middleware.

**Dependency vulnerability scanning:**

`pip-audit --desc --skip-editable` runs in CI (`dependency-audit` job).
Fails the pipeline on any known vulnerability (one documented exception:
CVE-2025-69872, diskcache pickle deserialization — transitive via trafilatura,
no upstream fix available). Runs independently of lint/test.

**Input validation at system boundaries:**

- Settings store validates: key format (regex `^[a-z][a-z0-9_]{1,63}$`),
  value length (max 4096), timezone (IANA), time format (HH:MM regex),
  coordinates (lat -90..90, lon -180..180), URLs (scheme validation)
- API key: HMAC timing-safe comparison, length guard (max 256 chars)

**Why 9.5 and not 10:**

- HSTS handled by Caddy reverse proxy, not at app level (single point of failure
  if Caddy is bypassed)
- No SBOM generation for supply chain transparency

**Score change (Phase 2):** +0.5 from 9.0 — CSP violation reports and pip-audit
close the two gaps identified in the initial assessment.

---

## 3. Architecture — 9.0/10

**Layer separation verified by import graph:**

```text
Routes (web/_*.py) — 13 feature modules
  imports from: _core (auth guards), actions/*
  does NOT import from: agent/core, stores directly
  5 routes fully delegate to action layer (no store access)
  5 routes still access stores via app.state (see below)

Agent (agent/core.py, agent/context.py)
  imports from: agent/tools/*, actions/*, config, memory/*
  does NOT import from: web/*, main

Actions (actions/*.py) — 12 modules (was 7)
  imports from: config, stores, external SDKs (httpx, openai)
  does NOT import from: web/*, agent/*

Stores (*_store.py, memory/store.py) — 7 stores
  imports from: asyncpg only
  does NOT import from: anything in niles.*
```

No circular imports detected. Dependency arrows point strictly downward.
`TYPE_CHECKING` blocks in `types.py` prevent runtime cycles. Agent accesses
web via `app.state`, not imports.

**Action layer (Phase 3 + Phase 4a):**

12 action modules (2,157 LOC total) mediate between routes and stores:

| Module             | LOC | Purpose                                  |
|--------------------|-----|------------------------------------------|
| `briefing.py`      | 461 | Daily/weekly briefing generation         |
| `notion.py`        | 319 | Notion RAG retrieval                     |
| `whatsapp.py`      | 299 | Evolution API operations                 |
| `contacts.py`      | 229 | Contact search + CardDAV connect/disconnect |
| `calendar.py`      | 229 | Event queries                            |
| `tasks.py`         | 197 | Vikunja task CRUD (agent-facing)         |
| `vikunja_setup.py` | 128 | Vikunja credential management (UI-facing)|
| `signal.py`        | 116 | Signal API operations                    |
| `weather.py`       | 67  | Location search + coordinate persistence |
| `admin.py`         | 63  | User CRUD with password hashing          |
| `settings.py`      | 49  | Setting validation + persistence         |

**Route → Action delegation status:**

| Route file      | Store access | Status                              |
|-----------------|-------------|-------------------------------------|
| `_settings.py`  | None        | Fully delegates to `SettingsAction`  |
| `_weather.py`   | None        | Fully delegates to `WeatherAction`   |
| `_admin.py`     | None        | Fully delegates to `AdminAction`     |
| `_contacts.py`  | None        | Fully delegates to `ContactsAction`  |
| `_vikunja.py`   | None        | Fully delegates to `VikunjaSetupAction` |
| `_whatsapp.py`  | `wa_store` ×4 | Planned for Phase 4b              |
| `_signal.py`    | `settings_store` ×4 | Planned for Phase 4b        |
| `_notion.py`    | `settings_store` ×2, `notion_store` ×2 | Deferred (complex pipeline) |
| `_auth.py`      | `user_store` ×2 | Deferred (auth IS the route)     |
| `_calendar.py`  | `google_token_store` ×1 | Deferred (minimal, 15 LOC) |

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

13 tool handlers auto-registered across 7 modules via side-effect imports:
`find_contact`, `send_whatsapp`, `get_whatsapp_messages`, `find_event`,
`create_event`, `remember`, `recall`, `search_notion`, `send_signal`,
`get_signal_messages`, `list_tasks`, `create_task`, `complete_task`.

**Web feature modules** (`web/__init__.py`):
13 modules register routes on shared `router` via side-effect imports:
`_admin`, `_auth`, `_briefing`, `_calendar`, `_chat`, `_contacts`, `_legal`,
`_notion`, `_settings`, `_signal`, `_vikunja`, `_weather`, `_whatsapp`.

**Type safety:** `AppState` Protocol (`types.py:36-62`) provides typed access
to `app.state` attributes, replacing untyped `request.app.state.X` patterns
in web routes.

**Why 9.0 and not higher:**

- `main.py` lifespan handler initializes 34 app.state attributes —
  a factory or builder pattern would be cleaner
- 5 of 13 route files still access stores via `app.state` (WhatsApp, Signal,
  Notion, Auth, Calendar) — planned for Phase 4b or deferred

**Why 9.0 and not lower:**

- Clean Routes → Actions → Stores layering for 8 of 13 feature routes
  (5 fully delegated + 3 thin wrappers like `_chat`, `_briefing`, `_legal`)
- 12 action modules with explicit interfaces, testable in isolation
- No circular imports, strict downward dependency arrows
- Action constructors use keyword-only DI with optional params for
  backward compatibility

**Score change (Phase 3 + 4a):** +0.5 from 8.5 — action layer extraction
eliminates direct store access in 5 route files. Routes now contain only HTTP
concerns (templates, cookies, redirects, scheduler jobs).

---

## 4. DevOps — 9.5/10

**Docker** (`docker/Dockerfile.niles`):

- Multi-stage (3 stages): Builder (compiles Tailwind + installs deps),
  gws-downloader (fetches gws binary with SHA256 verification), runtime
- Base image pinned with SHA256 digest: `python:3.14-slim@sha256:...`
- Non-root user: `useradd --uid 1000 niles`, `USER niles`
- HEALTHCHECK: `curl -f http://localhost:8000/health` (30s interval, 5s
  timeout, 15s start period, 3 retries)
- Tailwind binary SHA256-verified

**CI** (`.github/workflows/ci.yml`):

4 jobs, all action versions pinned with SHA256 digest:
1. `lint-and-test`: Ruff lint → Ruff format → mypy → pytest + coverage
2. `dependency-audit`: pip-audit (CVE-2025-69872 explicitly ignored)
3. `secret-scan`: gitleaks (pre-commit + CI)
4. `trivy-scan`: Container scan (CRITICAL/HIGH exit-code 1, depends on
   lint-and-test)

**Pre-commit** (`.pre-commit-config.yaml`):

10 hooks: gitleaks (secret scan), trailing-whitespace, end-of-file-fixer,
check-json/yaml/toml, check-merge-conflict, check-added-large-files,
no-commit-to-branch, PII check (custom script), bandit (SAST), detect-secrets
(baseline), Ruff (lint + format), semgrep (OWASP top 10), mypy (type check).
Run on every commit.

**Migrations** (`migrate.py` + `entrypoint.sh`):

Alembic migrations run via `entrypoint.sh` before uvicorn starts. 6 migration
versions: `001_baseline` through `006_notion_metadata_columns`. Detects 3
states (fresh DB, existing without alembic_version, managed). App crashes on
schema mismatch at startup.

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

**Responsive design present** — 32 Tailwind breakpoint instances across 7
template files. Mobile-first layout:

```text
base.html        flex items-center gap-2 sm:gap-4
settings.html    15 breakpoint classes (most responsive page)
carddav_status   5 breakpoint classes
```

Viewport meta tag present (`base.html:6`). Mobile-first layout.

**HTMX integration well-structured** — 19 templates (6 full pages, 12
fragments, 1 macro) with 121 HTMX attributes across 13 files. Fragment
templates (`fragments/*.html`) return partial HTML for HTMX swaps. No
full-page reloads for interactive actions. Confirmation dialogs
(`hx-confirm`) used for destructive operations.

**Accessibility (Phase 1, PR #45):**

- 32 `<label>` elements across 9 template files (login, settings, admin,
  weather, CalDAV, Vikunja, Notion). Many use `sr-only` class for visually
  hidden labels on inputs that already have placeholders.
- 18 ARIA attributes total:
  - 6 `aria-label` (theme toggle, web search, Notion search, send button)
  - 2 `aria-live` (chat container, polite mode)
  - 1 `aria-expanded` (weather location combobox)
  - 1 `aria-pressed` (chat toggle button)
  - 1 `aria-autocomplete` (weather search)
- `role` attributes: `role="alert"` on error messages, `role="status"` on
  success messages, `role="combobox"` on autocomplete.
- Skip-to-content link in `base.html:21`: visually hidden, visible on focus,
  links to `#main-content`. German text: "Zum Hauptinhalt springen".
- 7 `scope="col"` on admin table headers.
- 16 `sr-only` instances across 7 files for screen-reader content.
- Focus-visible ring styles (`focus-visible:ring-2`) on form inputs.
- Dark mode support throughout (Tailwind `dark:` prefixes).

**Why 8.0 and not higher:**

- No automated accessibility testing (axe-core not in CI)
- No focus management after HTMX content swaps (`hx-on::after-settle` not used)
- `aria-live` only on chat container — HTMX toast notifications may not be
  announced to screen readers
- No `aria-describedby` for complex forms with helper text

**Why 8.0 and not lower:**

Semantic HTML, form labels, ARIA attributes, skip-link, table scopes, and
proper focus-visible styles cover the fundamental accessibility requirements.
Weather location implements full combobox pattern. The remaining gaps are in
dynamic content announcement and automated testing.

**Score change (Phase 1):** +1.0 from 7.0 — comprehensive accessibility
pass addresses BFSG/EU Accessibility Act basics.

---

## 6. Maintainability — 8.5/10

**Test suite:**

- 914 test functions across 45 test files (+ 3 E2E)
- Code-to-test ratio: 13,483 LOC source / ~15,400 LOC tests = 1:1.14
- Coverage threshold: 65% minimum enforced in CI (`pyproject.toml`)
- Test categories: unit tests for stores, agent core, security, calendar sync,
  web routes, signal integration, migrations, Notion RAG (5 test files),
  Google MCP pool, action layer (5 test files), integration tests
  (multi-component), E2E tests (Docker-based, LLM judge)

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
| Settings action        | test_settings_action         | ~10   |
| Admin action           | test_admin_action            | ~10   |
| Contacts action setup  | test_contacts_action_setup   | ~3    |
| Vikunja setup action   | test_vikunja_setup_action    | ~16   |
| Docker deployment      | tests/e2e/ (3 files)         | ~48   |

**Documentation:**

Architecture documentation exists for the RAG pipeline (`docs/RAG.md`, ~580
lines) covering fundamentals, Niles implementation details, design decisions,
and troubleshooting. Additional docs: `API.md`, `Deployment.md`,
`Development.md`, `Niles-Core-Spec.md`, `LEGAL.md`.

**Structured logging** (`logging_config.py`):
structlog configured with JSON renderer, context variable merging, and
request ID injection. UTC ISO timestamps. Third-party loggers (httpx,
httpcore) silenced at WARNING level. All app code uses
`logging.getLogger(__name__)` which routes through structlog processors.

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
- 65% coverage threshold is modest (CLAUDE.md spec: 70-80%)
- No formal ADRs (Architecture Decision Records)

**Why 8.5 and not lower:**

- ~1000+ tests across 47 unit test files with behavior-oriented style
- Test LOC exceeds source LOC
- Integration tests and E2E tests add multi-layer coverage
- structlog JSON logging is production-ready
- AppState Protocol and removal of `web.*` overrides show type safety
  trend is improving
- RAG architecture documentation addresses the biggest documentation gap
- MCP, Notion, and embedding components all have dedicated test coverage

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

Metrics endpoint at `/metrics` (API-key protected). HTTP middleware records
request count and latency for every request. Path normalization replaces
numeric/UUID segments with `:id` to prevent label cardinality explosion.
LLM metrics recorded in agent core after each inference call.

**Health endpoints:**

- `/health`: Returns DB pool stats (size, free, min, max). No external service
  dependency — appropriate for liveness probe.
- `/ready`: Checks DB connectivity (SELECT 1) + Alembic migration version.
  Returns 503 with error list if not ready.
- Both exempt from rate limiting and metrics recording.

**Logging:**

Structured JSON to stdout via structlog. Request ID generated per request
(`RequestIdMiddleware`), added as `X-Request-ID` response header.

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

| Service           | Timeout   | Location                          |
|-------------------|-----------|-----------------------------------|
| Ollama LLM        | ~120s     | agent/core.py (OpenAI SDK)        |
| Ollama Embedding   | 30s       | sync/ollama_embedder.py           |
| Ollama Summarizer  | 60s       | sync/notion_summarizer.py         |
| Evolution API     | 30s       | http_clients.py (shared client)   |
| Signal API        | 10-30s    | actions/signal.py                 |
| CalDAV servers    | 30-60s    | sync/caldav.py                    |
| CardDAV servers   | 30s       | sync/carddav.py                   |
| Google OAuth      | 30s       | http_clients.py (shared client)   |
| MCP subprocesses  | 30s       | mcp/client.py                     |
| MCP user pool     | 15s       | mcp/user_pool.py                  |
| Weather API       | 10s       | http_clients.py (shared client)   |
| Geocoding API     | 5s        | http_clients.py (shared client)   |
| Vikunja API       | 10s       | actions/tasks.py                  |
| ICS downloads     | 60s       | sync/manager.py                   |
| Web fetch (MCP)   | 15s       | mcp/fetch/server.py               |
| DB startup wait   | 60s       | migrate.py (env configurable)     |

Every external HTTP call has an explicit timeout. No unbounded waits.

**Retry logic (Phase 1, PR #45):**

`@retry_http` decorator (`http_retry.py`) using tenacity:
- Retries on: `ConnectError`, `ConnectTimeout`, `ReadTimeout`, `WriteTimeout`,
  `PoolTimeout`, and `HTTPStatusError` with status >= 500
- Strategy: exponential jitter (initial=1s, max=10s, jitter=2s), max 3 attempts
- Does NOT retry 4xx errors

Applied to 8 callables across 5 modules:

| Module                | Decorated methods                         |
|-----------------------|-------------------------------------------|
| sync/carddav.py       | 2 methods (propfind + vCard fetch)         |
| sync/caldav.py        | 2 methods (REPORT + propfind)             |
| sync/manager.py       | 1 method (ICS fetch)                      |
| actions/briefing.py   | 2 methods (weather + Vikunja tasks fetch) |
| mcp/weather/server.py | 1 function (Open-Meteo data fetch)        |

**Graceful shutdown** (`main.py:482-514`):

`shutdown_event` is an `asyncio.Event` set during lifespan teardown. Shutdown
sequence: set event → 0.5s SSE drain → cancel Signal WebSocket → close Signal
HTTP client → close Ollama embedder + summarizer → stop UserMCPPool → stop
MCP servers → shutdown scheduler → close HTTP clients → close DB pool.

All long-running tasks (Signal listener, SSE streams) check `shutdown_event`
between iterations and exit cleanly.

**Signal WebSocket reconnection** (`sources/signal.py`):

Exponential backoff (5s initial, 60s max) with `asyncio.wait_for(
shutdown_event.wait(), timeout=backoff)` — interruptible during shutdown.

**Why 8.0 and not higher:**

- No circuit breakers — a consistently failing CalDAV server gets hammered
  on every sync cycle with no backoff beyond the per-request retry
- Ollama has no retry — a transient LLM timeout is an immediate error
- No bulkhead: one slow external call can't exhaust the event loop but
  there's no isolation between service call paths

**Why 8.0 and not lower:**

Timeouts are comprehensive (16 distinct timeout configurations), retry logic
covers 5 of the 6 external service integration modules, graceful shutdown is
thorough with ordered resource cleanup, and Signal reconnection demonstrates
the right pattern. For a self-hosted single-user app, the remaining gaps are
low-probability scenarios.

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

**Caching (6 patterns identified):**

| Cache                    | TTL    | Location            | Purpose                       |
|--------------------------|--------|---------------------|-------------------------------|
| Calendar source names    | 300s   | agent/context.py    | Reduce DB queries per chat    |
| CalDAV collection list   | 60s    | sync/caldav.py      | Avoid PROPFIND on page load   |
| MCP tool definitions     | —      | mcp/client.py       | Discover once per server      |
| Vikunja default project  | —      | actions/tasks.py    | Avoid repeated API call       |
| Echo guard               | 10s    | sources/echo_guard  | Prevent echo-loop             |
| MCP user pool idle       | 1800s  | mcp/user_pool.py    | Cleanup unused instances      |

**SSE streaming** (`web/_chat.py`):

Proper async generator with gauge tracking. Shutdown event checked between
chunks. StreamingResponse with `X-Accel-Buffering: no` for reverse proxy
compatibility.

**Why 8.5 and not higher:**

- No caching for settings, user lookups, or contact lists
- Ollama model list fetched on every request
- No performance regression tests

**Why 8.5 and not lower:**

Async is correct and consistent. DB pooling is properly configured. 5 shared
HTTP clients eliminate per-request TCP overhead for all main request paths.
SSE streaming is well-implemented with backpressure awareness. 6 caching
patterns cover the most frequent hot paths.

**Score change (Phase 1):** +1.0 from 7.5 — shared httpx clients eliminate
the 15+ per-request client instances that were creating and destroying TCP
connections on every external API call.

---

## 10. API Design — 8.0/10

**REST conventions followed for internal API:**

54 routes total (33 POST, 18 GET, 2 DELETE, 1 core redirect). URL structure
consistently uses `/ui/api/{resource}` for HTMX API endpoints and
`/{resource}` for external-facing endpoints.

```text
GET  /ui/chat              → chat page
GET  /ui/api/chat/history   → paginated history (offset, channel)
POST /ui/api/chat           → send message (non-streaming)
POST /ui/api/chat/stream    → send message (SSE)
POST /ui/api/chat/clear     → clear history

GET  /ui/api/calendar/sources → list sources
POST /ui/api/calendar/sources → add source
DELETE /ui/api/calendar/sources/{id} → remove source

GET  /ui/api/admin/users    → user list page
POST /ui/api/admin/users    → create user
DELETE /ui/api/admin/users/{id} → delete user

POST /chat                  → direct chat API (API key auth)
GET  /health                → liveness probe
GET  /ready                 → readiness probe
GET  /metrics               → Prometheus metrics (API key auth)
```

Consistent URL structure. Resources are nouns, actions are HTTP verbs.

**Pagination** implemented on:

- Chat history: `offset` + `limit=20` (`web/_chat.py`), `has_more` flag
- User list: `limit=100, offset=0` (`user_store.py`)
- Memory store: `limit=200, offset=0` (`memory/store.py`)

**Unified error format (Phase 2, PR #46):**

JSON API error paths use the CLAUDE.md-specified envelope (`errors.py`):

```json
{"error": {"code": 429, "message": "Too many requests", "details": null}}
```

Applied to: `_api_exception_handler` (all HTTPExceptions), `RateLimitMiddleware`
(429), webhook auth (401). Helper function `error_response()` prevents format
drift. No sensitive data in error responses.

HTMX endpoints correctly return template fragments (toast, redirect headers) —
these are the right format for HTMX interactions, not API responses.

**Why 8.0 and not higher:**

- No OpenAPI schema curation (auto-generated by FastAPI, but not documented
  or versioned)
- HTMX endpoints use different error patterns by design, but this creates
  two "styles" of error handling in the same codebase
- Limited Pydantic BaseModel usage for request validation (only 1 model:
  `ChatRequest`); most routes use manual Form validation

**Why 8.0 and not lower:**

- REST conventions are correct where used
- Pagination implemented on all list endpoints
- Unified JSON error envelope per CLAUDE.md spec on all API error paths
- URL structure is consistent and predictable
- Input validation comprehensive at data layer (SettingsStore)

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

### Phase 3 — Action Layer: Settings, Weather, Admin (done, PR #59)

| #   | Dimension    | Before | After | Measure                                                            |
|-----|--------------|--------|-------|--------------------------------------------------------------------|
| 9   | Architecture | 8.5    | —     | `SettingsAction`, `WeatherAction`, `AdminAction` extracted from routes |

Intermediate step — score change deferred to Phase 4a (combined impact).

### Phase 4a — Action Layer: Contacts, Vikunja (done, PR #60)

| #   | Dimension    | Before | After | Measure                                                                      |
|-----|--------------|--------|-------|------------------------------------------------------------------------------|
| 10  | Architecture | 8.5    | 9.0   | `ContactsAction` expanded, `VikunjaSetupAction` created. 5/13 routes clean   |

### Phase 5 — Long-term (7.0-8.5 → ~9.0 avg)

| #   | Dimension       | Score | Measure                                                                | Effort |
|-----|-----------------|-------|------------------------------------------------------------------------|--------|
| 11  | Observability   | 7.0   | Error tracking (Sentry/GlitchTip self-hosted), consistent request IDs  | Large  |
| 12  | Architecture    | 9.0   | Extract `main.py` lifespan into builder/factory pattern                | Medium |
| 13  | Maintainability | 8.5   | Reduce remaining 10 mypy overrides, raise coverage to 70%              | Medium |
| 14  | UI/UX           | 8.0   | axe-core in CI, HTMX focus management, aria-live on toasts             | Small  |
| 15  | Performance     | 8.5   | Settings/contact caching, Ollama model list caching                    | Small  |
| 16  | Resilience      | 8.0   | Circuit breakers for CalDAV, Ollama retry with backoff                 | Medium |

### Phase 4b — Action Layer: WhatsApp, Signal (planned)

| Route file     | Store access             | Action module  | Status  |
|----------------|--------------------------|----------------|---------|
| `_whatsapp.py` | `wa_store` ×4            | `whatsapp.py`  | Planned |
| `_signal.py`   | `settings_store` ×4      | `signal.py`    | Planned |

---

## Methodology

- **Data source:** Automated codebase analysis (grep for patterns, line counts,
  import graph traversal) combined with manual code review of critical paths.
  File paths cited for every claim.
- **Scoring:** 1-10 scale per dimension. Weighted average uses 1.3x multiplier
  for Security, Architecture, Maintainability (highest impact on project
  longevity); 0.8x for UI/UX (lower weight for backend-focused project);
  1.0x for all others.
- **Trend:** Delta compared to previous assessment (2026-03-12). Dimensions
  unchanged since that assessment show "=".
- **Bias disclosure:** This assessment was performed by the same tool that
  implemented PRs #43-#60. Findings should be validated independently.
  Scores may be biased toward overvaluing recent improvements.
