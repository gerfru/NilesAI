# Niles AI — App Evaluation Report

**Datum:** 2026-06-08
**Stack:** FastAPI 0.129 + Python 3.14 | PostgreSQL 15 (pgvector) | SQLAlchemy Core + AsyncPG | Alembic | Docker Compose + Caddy
**ASVS-Level:** L2 (Auth, Credential Encryption, PII: Kalender, Kontakte, Nachrichten)
**Team:** Solo | **Regelquelle:** dev-best-practices Rule-Files (essential/app/github/architecture)

---

## Ampel-Übersicht

| Achse | Ampel | #Critical | #High | Wichtigste verletzte Regel |
|---|---|---|---|---|
| **Architektur & 12-Factor** | 🟢 | 0 | 0 | architecture-rules → Docker: Resource Limits |
| **Security (ASVS L2)** | 🟡 | 0 | 0 | app-rules → Auth: Data Access Layer Scoping |
| **Code-Qualität** | 🔴 | 3 | 10 | Complexity >20 (lifespan CC=32, process_event_stream CC=27, fetch_url CC=25) |
| **Tests & Zuverlässigkeit** | 🔴 | 2 | 1 | essential-rules → Testing: Kritische Pfade ~100% (UserStore 0%, OAuth 0%) |
| **CI/CD & Delivery** | 🟡 | 0 | 2 | github-rules → Docker: `--frozen` in Build; Branch Protection |
| **Observability & Betrieb** | 🟡 | 0 | 2 | app-rules → Monitoring: Sentry + Alert-Schwellen fehlen |

---

## Alle Befunde nach Severity

### 🔴 CRITICAL (5)

| # | Titel | Datei:Zeile | Achse | Conf. | Verletzte Regel | Fix | Aufwand |
|---|---|---|---|---|---|---|---|
| C1 | `lifespan()` God Function (CC=32, 454 Zeilen) | `src/niles/main.py:83` | Code-Qualität | 10 | Complexity >20 Fail | In ~5 Init-Helfer extrahieren (`_init_database()`, `_init_notion()`, etc.) | L |
| C2 | `process_event_stream()` CC=27 | `src/niles/agent/core.py:445` | Code-Qualität | 10 | Complexity >20 Fail | Stream-Akkumulation, Tool-Execution, Buffering in Helfer extrahieren | L |
| C3 | `fetch_url()` CC=25 | `src/niles/mcp/fetch/server.py:44` | Code-Qualität | 10 | Complexity >20 Fail | URL-Validierung, Redirect-Loop, Text-Extraktion extrahieren | M |
| C4 | `UserStore` hat null Tests | `src/niles/user_store.py` | Tests | 10 | essential-rules → Testing: Kritische Pfade Auth ~100% | Unit-Tests für alle UserStore-Methoden (get_by_email, create_password_user, etc.) | M |
| C5 | Google OAuth Callback (`callback_google`) ohne Tests | `src/niles/sources/web/_auth.py:173-331` | Tests | 10 | essential-rules → Testing: Kritische Pfade Auth ~100% | Tests für CSRF-State, Token-Exchange, Email-Whitelist, deaktivierte User | M |

### 🟠 HIGH (15)

| # | Titel | Datei:Zeile | Achse | Conf. | Verletzte Regel | Fix | Aufwand |
|---|---|---|---|---|---|---|---|
| H1 | `process_event()` CC=18 + Duplication mit `process_event_stream()` | `src/niles/agent/core.py:673` | Code-Qualität | 10 | Complexity >10 Warning + Duplication >3% | Shared Logic (Phone-Choice, Confirm, Tool-Loop) in private Methoden | L |
| H2 | `main.py` 812 Zeilen | `src/niles/main.py` | Code-Qualität | 10 | File >400 Zeilen | lifespan() → `startup.py`, Middleware → `middleware.py` | L |
| H3 | `agent/core.py` 894 Zeilen | `src/niles/agent/core.py` | Code-Qualität | 10 | File >400 Zeilen | TOOLS-Definitionen (Z.37-310) → `tool_defs.py`, shared Logic extrahieren | M |
| H4 | Notion-Pipeline-Erstellung dupliziert | `sources/web/_notion.py:128` + `main.py:394` | Code-Qualität | 9 | Duplication >3% | Factory-Funktion `create_notion_pipeline()` in shared Modul | M |
| H5 | `choose_phone`/`confirm` Interception 3× dupliziert | `src/niles/agent/core.py:640,759,817` | Code-Qualität | 9 | Duplication >3% | `_handle_bypass_result()` Helfer extrahieren | S |
| H6 | `SettingsStore.set()` CC=16 | `src/niles/settings_store.py:95` | Code-Qualität | 9 | Complexity >10 | Validator-Registry-Pattern | M |
| H7 | `NotionRetriever.search()` CC=15 | `src/niles/actions/notion.py:195` | Code-Qualität | 9 | Complexity >10 | Scoring + Dedup in eigene Methoden | M |
| H8 | `generate_daily()` CC=15 | `src/niles/actions/briefing.py:310` | Code-Qualität | 9 | Complexity >10 | Task-Filterung + Message-Assembly extrahieren | S |
| H9 | `_parse_date()` CC=15 | `src/niles/actions/calendar.py:125` | Code-Qualität | 9 | Complexity >10 | Weekday- und Relative-Date-Resolution extrahieren | S |
| H10 | `notion_connect()` CC=15 (God Route Handler) | `src/niles/sources/web/_notion.py:72` | Code-Qualität | 9 | Complexity >10 | Pipeline-Erstellung als Factory (→ H4) | M |
| H11 | Web-Route-Handler ohne Tests (calendar, contacts, briefing, vikunja, whatsapp, weather) | `src/niles/sources/web/_calendar.py` u.a. | Tests | 10 | essential-rules → Testing: API Route Handlers Priorität 1 | Auth-Guard, CSRF, Mutations-Tests für jede Route | L |
| H12 | Docker-Build ohne `--frozen` Flag | `docker/Dockerfile.niles:12` | CI/CD | 9 | github-rules → Docker: `--frozen` in Build | `uv sync --frozen --no-dev` statt `uv pip install --system .` | M |
| H13 | Branch Protection nicht verfügbar (GitHub Free Private Repo) | GitHub Settings | CI/CD | 10 | github-rules → Branch Protection auf main | Upgrade GitHub Plan oder Repo public; oder Risiko dokumentieren | S |
| H14 | Kein Sentry Error Tracking | codebase-weit | Observability | 9 | app-rules → Monitoring: Error Tracking: Sentry | `sentry-sdk[fastapi]` + `SENTRY_DSN` in Config | M |
| H15 | Keine Alerting-Regeln definiert | codebase-weit | Observability | 10 | app-rules → Monitoring: Alert-Schwellen (Error Rate >1%, p95 >2s, CPU >80%) | Prometheus Alert Rules oder Sentry Alerts | M |

### 🟡 MEDIUM (17)

| # | Titel | Datei:Zeile | Achse | Conf. | Verletzte Regel | Fix | Aufwand |
|---|---|---|---|---|---|---|---|
| M1 | Keine Docker Resource Limits | `docker/docker-compose.yml` | Architektur | 9 | architecture-rules → Docker: Resource Limits | `deploy.resources.limits` pro Service | S |
| M2 | Evolution API Bind Mount statt Named Volume | `docker/docker-compose.yml:63` | Architektur | 9 | architecture-rules → Docker: Named Volumes für Prod | Named Volume `evolution_instances` | S |
| M3 | `MemoryStore` ohne User-Scoping (globaler Namespace) | `src/niles/memory/store.py:18-74` | Security | 8 | app-rules → Auth: Data Access Layer | `user_id` Column + Scoping in allen Methoden | M |
| M4 | `notion_connect` ohne Admin-Guard | `src/niles/sources/web/_notion.py:71-77` | Security | 9 | app-rules → Auth: Route-Level | `_require_admin` statt `_require_auth_and_csrf` | S |
| M5 | `briefing_test` ohne Admin-Guard | `src/niles/sources/web/_briefing.py:13-14` | Security | 8 | app-rules → Auth: Route-Level | `_require_admin` statt `_require_auth_and_csrf` | S |
| M6 | DNS Rebinding TOCTOU in SSRF-Schutz | `src/niles/network.py:22-37` | Security | 7 | app-rules → Input-Validierung | Resolved IP pinnen und an httpx übergeben | M |
| M7 | `embed_pending()` CC=11, 142 Zeilen, Nesting 5 | `src/niles/sync/notion_embeddings.py:97` | Code-Qualität | 9 | Function >50 Zeilen, Nesting >4 | Summary- und Detail-Embedding in eigene Methoden | M |
| M8 | `chat_stream()` CC=16 | `src/niles/sources/web/_chat.py:228` | Code-Qualität | 8 | Complexity >10 | Notion-Context-Enrichment extrahieren | S |
| M9 | `whatsapp_webhook()` CC=14 | `src/niles/sources/whatsapp.py:24` | Code-Qualität | 8 | Complexity >10 | Self-Chat-Handling extrahieren | S |
| M10 | `fetch_messages()` CC=14 | `src/niles/actions/whatsapp.py:58` | Code-Qualität | 8 | Complexity >10 | Message-Filtering/Formatting extrahieren | S |
| M11 | `parse_icalendar()` CC=20 | `src/niles/sync/ical_parser.py:153` | Code-Qualität | 8 | Complexity >20 (Grenzfall, datengetrieben) | Property-Name → Handler Dispatch Dict | M |
| M12 | Duplicate SQL: INSERT INTO notion_embeddings | `src/niles/sync/notion_embeddings.py:152,188` | Code-Qualität | 8 | Duplication | `_upsert_embedding()` Methode | S |
| M13 | 3 Dateien leicht über 400-Zeilen-Grenze (caldav 470, briefing 458, manager 420) | `src/niles/sync/caldav.py` u.a. | Code-Qualität | 10 | File >400 Zeilen | Geringfügig — prüfen ob Extraktion lohnt | M |
| M14 | `fail_under = 65` unter Regel-Ziel 70-80% | `pyproject.toml:185` | Tests | 10 | essential-rules → Testing: Coverage 70-80% | Auf 70 anheben nach Schließung kritischer Lücken | S |
| M15 | `whatsapp_store.py` ohne Unit-Tests | `src/niles/whatsapp_store.py` | Tests | 9 | essential-rules → Testing: Test-Pyramide | Unit-Tests mit gemocktem Pool | S |
| M16 | `mypy check_untyped_defs = false` | `pyproject.toml:132` | CI/CD | 7 | github-rules → Type Check (implizit) | Inkrementell auf `true` setzen | L |
| M17 | Fehlende Saturation-Metriken (CPU/Memory) | `src/niles/metrics.py` | Observability | 10 | app-rules → Monitoring: CPU/Memory >80% | `process_*` Default-Metriken verifizieren; DB-Pool-Gauge ergänzen | S |

### 🔵 LOW (14)

| # | Titel | Datei:Zeile | Achse | Conf. | Verletzte Regel | Fix | Aufwand |
|---|---|---|---|---|---|---|---|
| L1 | Scattered `*_store.py` am Package-Root | `src/niles/*.py` | Architektur | 7 | architecture-rules → Feature-basierte Struktur | In Feature-Ordner verschieben | M |
| L2 | Port 8000 hardcoded, nicht via Env konfigurierbar | `docker/entrypoint.sh:8` | Architektur | 9 | architecture-rules → 12-Factor: Port Binding | `--port ${PORT:-8000}` | S |
| L3 | In-Memory Rate Limiter (Stateless-Verletzung) | `src/niles/main.py:540-578` | Architektur | 8 | architecture-rules → 12-Factor: Stateless Processes | Für Single-Instance akzeptabel; bei Scale-Out → Caddy/Redis | S-M |
| L4 | Self-signed TLS (Caddy `tls internal`) | homelab-gateway/Caddyfile | Architektur | 8 | architecture-rules → Automatisches HTTPS | Akzeptabel für Tailscale-Homelab; dokumentieren | S |
| L5 | `NotionStore` ohne User-Scoping | `src/niles/notion_store.py` | Security | 7 | app-rules → Auth: Data Access Layer | Für Solo akzeptabel; dokumentieren oder `user_id` ergänzen | S-L |
| L6 | `is_private_host()` returns False bei DNS-Failure | `src/niles/network.py:30-32` | Security | 7 | app-rules → Input-Validierung | Return `True` (block) bei gaierror | S |
| L7 | `except ValueError, IndexError:` Syntax (22×) | Diverse Dateien | Code-Qualität | 10 | Naming/Style | `except (ValueError, IndexError):` Tuple-Form | S |
| L8 | Fehlende Return-Type-Annotations | Diverse Dateien | Code-Qualität | 8 | Type Annotations | `-> None` auf `__init__`, Return-Types auf Utility-Funktionen | S |
| L9 | Fehlender Parametertyp `app_state` | `src/niles/sources/signal.py:70` | Code-Qualität | 8 | Type Annotations | Typisierung ergänzen | S |
| L10 | `signal_store.py` ohne Unit-Tests | `src/niles/signal_store.py` | Tests | 9 | essential-rules → Testing: Test-Pyramide | Unit-Tests mit gemocktem Pool | S |
| L11 | `echo_guard.py` ohne Tests | `src/niles/sources/echo_guard.py` | Tests | 8 | essential-rules → Testing | Unit-Tests ergänzen | S |
| L12 | Fehlende PR-Template | `.github/pull_request_template.md` | CI/CD | 10 | github-rules → PR Template | Template mit Summary/Test Plan/Checklist anlegen | S |
| L13 | Renovate: Docker Digest Updates ohne Monthly Schedule | `renovate.json` | CI/CD | 8 | github-rules → Docker Digest Updates: Monatlich | packageRule mit `schedule` ergänzen | S |
| L14 | Kein OpenTelemetry (Regel: "erst bei Bedarf") | codebase-weit | Observability | 10 | app-rules → Monitoring: OpenTelemetry als Standard | Informativ — ergänzen wenn Distributed Tracing nötig | L |

---

## ⚪ COMPLIANCE (nicht Security-Severity)

| Titel | Achse | Hinweis |
|---|---|---|
| Fehlende Audit-Logs (Tabelle) | Security | ISO 27001 A.8.15 / GDPR Art. 32 — ASVS L2 V7.1.1 empfiehlt dedizierte `audit_log` Tabelle. Aufwand: M |
| GitHub-native Secret Scanning nicht verifizierbar | CI/CD | Private Repo auf GitHub Free — Feature ggf. nicht verfügbar. 2 von 3 Schichten (pre-commit + CI gitleaks) aktiv |
| Uptime Monitoring nicht verifizierbar | Observability | [zu verifizieren] — extern konfiguriert? `/health` + `/ready` Endpoints existieren |
| Referenzierte Regel-Files (`app-rules.md` etc.) nicht im Repo | Tests | CLAUDE.md verweist auf Dateien die im Repo nicht existieren |

---

## Fix-Reihenfolge (Empfehlung)

### Phase 1 — Security & Shared Utilities (Quick Wins)
1. **M4** `notion_connect` → `_require_admin` (S)
2. **M5** `briefing_test` → `_require_admin` (S)
3. **L6** `is_private_host()` → block bei DNS-Failure (S)
4. **H12** Dockerfile `uv sync --frozen` (M)
5. **M1** Docker Resource Limits (S)
6. **M2** Named Volume für Evolution API (S)

### Phase 2 — Refactoring (Komplexität & Duplication)
7. **C1** `lifespan()` aufbrechen → `startup.py` (L)
8. **H4 + H10** Notion-Pipeline-Factory (M)
9. **H5** `choose_phone`/`confirm` Helfer (S)
10. **H1** `process_event()` + `process_event_stream()` Shared Logic (L)
11. **C3** `fetch_url()` aufbrechen (M)

### Phase 3 — Tests (kritische Lücken schließen)
12. **C4** UserStore Tests (M)
13. **C5** OAuth Callback Tests (M)
14. **H11** Web-Route-Handler Tests (L)
15. **M14** `fail_under` auf 70 anheben (S)

### Phase 4 — Observability & Kosmetik
16. **H14** Sentry Integration (M)
17. **H15** Alerting Rules (M — oder Sentry Alerts als Ersatz)
18. **L12** PR-Template (S)
19. **L7** except-Syntax Cleanup (S)

---

## Dokumentierte Ausnahmen (bestehend)

- pip-audit ignoriert CVE-2025-69872, GHSA-pjjw-68hj-v9mw, PYSEC-2026-196
- bandit überspringt B101/B105/B314/B324/B405/B608 (handled by ruff-S)
- mypy Overrides auf 7 Modulen (inkrementelle Adoption)
- Coverage fail_under = 65 (pragmatisch, Ziel: 70)

## Vorgeschlagene neue Ausnahmen für CLAUDE.md

- **L3** In-Memory Rate Limiter: Akzeptabel für Single-Instance Homelab. Dokumentieren: "Rate Limiting in-memory, bei Scale-Out auf Caddy/Redis migrieren."
- **L4** Self-signed TLS: Akzeptabel für Tailscale-basiertes Homelab. Dokumentieren: "TLS via Caddy internal CA (Tailscale Trust)."
- **L5** NotionStore ohne User-Scoping: Akzeptabel für Solo-Deployment mit shared Notion Workspace.
- **L14** OpenTelemetry: Nicht implementiert, da aktuell kein Distributed Tracing nötig (single-service).

---

## DORA-Metriken [Geschätzt]

| Metrik | Schätzung | Bewertung |
|---|---|---|
| Deployment Frequency | ~4-5 Merges/Woche | Elite |
| Lead Time for Changes | <1 Tag | Elite |
| Change Failure Rate | [Geschätzt] <5% | Gut |
| Failed Deployment Recovery | [Geschätzt] <1h | Elite |

**Hinweis:** Basiert auf Git-History (388 Commits, 71 Merge-PRs in 4 Monaten). Echte DORA-Metriken erfordern Production-Deployment-Telemetrie.

---

*Erstellt mit KI-Unterstützung (Claude Code + dev-best-practices Plugin).
Findings sind zu verifizieren — kein Ersatz für manuelle Penetrationstests.*
