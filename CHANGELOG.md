# Changelog

All notable changes to this project will be documented in this file.

## [0.2.0](https://github.com/gerfru/NilesAI/releases/tag/v0.2.0) (2026-06-12)

First public release. Major security hardening, infrastructure improvements, and
preparation for open-source publication since the initial private baseline.

### Security

* Replace `xml.etree` with `defusedxml` for CalDAV XML parsing (XXE protection)
* Add SSRF protection for CardDAV `test_connection` endpoint
* Fail-closed SSRF check on DNS resolution failure
* Enforce single Uvicorn worker process at startup (prevents shared state across forks)
* Protect LLM hot-reload and Vikunja `_in_flight` set with `asyncio.Lock`
* Cap login rate limiter with `OrderedDict` to prevent memory exhaustion
* Remove PostgreSQL pool stats from unauthenticated `/health` endpoint
* Scope contact lookups and memory store to authenticated `user_id`
* Add user context and message length limit to `/chat` endpoint
* Decouple credential encryption gate from `LOG_LEVEL`
* Require admin auth for `notion_connect` and `briefing_test` endpoints
* OAuth hardening: error sanitization, credential encryption docs, `/ready` endpoint

### Features

* Conversation history pruning to prevent unbounded memory growth
* Per-user memory store scoping
* Opt-in Sentry error tracking (`SENTRY_DSN` env var)
* DB connection pool saturation metrics
* Configurable phone country code (`PHONE_COUNTRY_CODE`)
* Static asset cache-busting and search toggle visual feedback

### Infrastructure

* Upgrade Python runtime to **3.14**
* Modernize Dockerfile to `uv sync --frozen` with venv
* Add Docker resource limits and named volumes
* Set up Release Please (automated changelog + GitHub Releases)
* Add tag-triggered SBOM generation as release asset
* Branch protection on `main` (CI gate, linear history, enforce admins)
* Pin all Docker base images and GitHub Actions to exact SHAs
* Monthly Renovate schedule for Docker digest updates

### Refactoring

* Extract God Functions across agent core, web routes, and sync layer
* Reduce cyclomatic complexity in calendar, context, and briefing modules
* Extract `SettingsStore` validator registry
* Add `AppState` Protocol and `TypedDict` types throughout
* Add tuple-form `except` clauses replacing Python-2-style comma syntax

### Tests

* Add auth-guard tests for all 28 web route handlers
* Add `UserStore` unit tests (25 tests, all public methods)
* Add OAuth callback branch coverage (13 tests)
* Add `WhatsAppStore` + `EchoGuard` tests; raise `fail_under` to 70%
* Add round-trip encryption tests for credential and settings stores

### Chore

* Replace internal hostnames with `example.local` for public release
* Harden repo settings, README, and documentation
* Enable `check_untyped_defs` in mypy

## [0.1.0](https://github.com/gerfru/NilesAI/releases/tag/v0.1.0) (2026-03-13)

Initial private baseline. Core agent loop, WhatsApp/Signal integration, CalDAV/CardDAV
sync, Notion RAG, Vikunja task management, and web UI.
