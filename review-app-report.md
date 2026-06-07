# Niles App Evaluation Report

**Datum:** 2026-06-07
**Stack:** Python 3.12 + FastAPI + Jinja2/htmx/Tailwind | PostgreSQL 15 + pgvector | Docker multi-container | Caddy
**ASVS-Level:** L2 | **Team:** Solo | **Regelquelle:** dev-best-practices Plugin Rule-Files

---

## Ampel-Uebersicht

| Achse | Ampel | #Critical | #High | Wichtigste verletzte Regel |
|---|---|---|---|---|
| Architektur & 12-Factor | :yellow_circle: Gelb | 0 | 0 | architecture-rules -> Docker (keine Resource Limits, Bind Mount) |
| Security (ASVS L2) | :yellow_circle: Gelb | 0 | 0 | essential-rules -> Security Assessment (bandit + semgrep fehlen) |
| Code-Qualitaet | :red_circle: Rot | 1 | 5 | Code-Qualitaet -> Datei/Funktion LOC (main.py, agent/core.py) |
| Tests & Zuverlaessigkeit | :red_circle: Rot | 2 | 5 | architecture-rules -> Testing (Auth-Pfade ungetestet, Coverage 65%) |
| CI/CD & Delivery | :red_circle: Rot | 1 | 2 | github-rules -> Branch Protection (nicht aktiv, GitHub Free) |
| Observability & Betrieb | :yellow_circle: Gelb | 0 | 1 | app-rules -> Monitoring (kein Sentry) |

---

## Konsolidierte Befundliste (nach Severity)

### CRITICAL

| # | Achse | Titel | Datei:Zeile | Confidence | Verletzte Regel | Fix | Aufwand |
|---|---|---|---|---|---|---|---|
| 1 | CI/CD | Branch Protection nicht aktiv (GitHub Free + privates Repo) | Repository-Settings | 8 | github-rules -> Branch Protection | GitHub Pro/Team upgraden oder Repo public machen; dann Require PR + Status Checks + No Force Push aktivieren | M |
| 2 | Tests | UserStore hat keine Unit-Tests | `src/niles/user_store.py` | 10 | architecture-rules -> Testing ("Kritische Pfade ~100%") | Tests fuer create_password_user, get_with_hash, create_or_update, auto-promote; asyncpg.Pool mocken | M |
| 3 | Tests | Google OAuth Callback nicht getestet | `sources/web/_auth.py:179-343` | 10 | architecture-rules -> Testing ("Kritische Pfade ~100%") | Tests fuer State-CSRF-Validation, Token-Exchange-Fehler, Email-Whitelist, deaktivierter User | M |
| 4 | Code | `lifespan()` ist 465 LOC | `main.py:83` | 10 | Code-Qualitaet -> Funktion >50 LOC | Startup in `_init_database()`, `_init_stores()`, `_init_scheduler()`, `_wire_app_state()` extrahieren | L |

### HIGH

| # | Achse | Titel | Datei:Zeile | Confidence | Verletzte Regel | Fix | Aufwand |
|---|---|---|---|---|---|---|---|
| 5 | CI/CD | Semgrep fehlt vollstaendig in CI | `.github/workflows/ci.yml` | 10 | github-rules -> CI Pipeline / Security Scanning (SAST: Semgrep) | `semgrep scan --config=auto --error src/` als CI-Step oder `semgrep/semgrep-action@v1` | S |
| 6 | CI/CD | Keine required status checks definierbar | Repository-Settings | 8 | github-rules -> Branch Protection (Require status checks) | Konsequenz von #1 -- gleiche Loesung (Plan-Upgrade) | M |
| 7 | Observ. | Kein Sentry Error Tracking | projekt-weit | 10 | app-rules -> Monitoring ("Sentry als Minimum") | `sentry-sdk[fastapi]` installieren, `SENTRY_DSN` in Config, `sentry_sdk.init()` in Lifespan | M |
| 8 | Tests | Google OAuth Login-Redirect nicht getestet | `sources/web/_auth.py:147-176` | 10 | architecture-rules -> Testing (Kritische Pfade) | Test: Redirect-URL korrekt, State-Cookie gesetzt | S |
| 9 | Tests | Web-UI Route-Handler fuer Calendar/Contacts/Signal/WhatsApp nicht getestet | `sources/web/_calendar.py` u.a. | 9 | architecture-rules -> Testing Prioritaet 1 (API Endpoints) | Route-Handler-Tests mit Auth-Guards + Verhalten | L |
| 10 | Tests | Coverage IST 65% vs. SOLL 70-80% | `pyproject.toml:161` | 10 | architecture-rules -> Testing (Coverage 70-80%) | `fail_under` auf 70 erhoehen, Luecken schliessen | L |
| 11 | Tests | signal_listener nicht getestet | `sources/signal.py:21-50+` | 9 | architecture-rules -> Testing (Integration) | Gemockter websockets.connect: Envelope-Parsing, Reconnect, Shutdown | M |
| 12 | Tests | Integration-Tests laufen nicht in CI (kein Docker Compose) | `tests/integration/`, `.github/workflows/ci.yml` | 10 | architecture-rules -> Testing + github-rules -> CI | PostgreSQL-Service-Container in CI aktivieren oder testcontainers-python | L |
| 13 | Code | `agent/core.py` ist 957 LOC | `agent/core.py` | 10 | Code-Qualitaet -> Datei >400 LOC | TOOLS (339 LOC) in `tool_definitions.py` auslagern; process_event als Wrapper ueber process_event_stream | L |
| 14 | Code | `main.py` ist 839 LOC | `main.py` | 10 | Code-Qualitaet -> Datei >400 LOC | Lifespan aufteilen (s. #4), Middleware in `middleware.py` | L |
| 15 | Code | `process_event_stream()` ist 250 LOC | `agent/core.py:468` | 10 | Code-Qualitaet -> Funktion >50 LOC | Stream-Accumulation, Tool-Execution-Loop, Fallback-Handling extrahieren | L |
| 16 | Code | `process_event()` ist 182 LOC + Duplikation | `agent/core.py:720` | 10 | Code-Qualitaet -> Funktion >50 LOC + Duplikation >3% | Als Non-Streaming-Wrapper ueber `process_event_stream()` implementieren (~61 duplizierte LOC = 6.4%) | M |
| 17 | Code | TOOLS-Konstante 339 LOC Dict-Literal inline | `agent/core.py:37-376` | 10 | Code-Qualitaet -> Separation of Concerns | In `agent/tool_definitions.py` oder YAML/JSON auslagern | S |
| 18 | Code | mypy override `agent/core.py` unterdrueckt 5 Error-Codes | `pyproject.toml:132-133` | 9 | Code-Qualitaet -> mypy Overrides | Typisierte Dataclasses fuer Tool-Call-Daten; SimpleNamespace ersetzen | L |

### MEDIUM

| # | Achse | Titel | Datei:Zeile | Confidence | Verletzte Regel | Fix | Aufwand |
|---|---|---|---|---|---|---|---|
| 19 | Security | SSRF via `llm_base_url` (nur Admin) | `sources/web/_settings.py:125-129` | 8 | essential-rules -> Input validieren an System-Grenze | URL-Schema-Pruefung + optional `is_private_host()` in `SettingsStore.set()` | S |
| 20 | Security | bandit + semgrep weder in pre-commit noch CI (SAST fehlt) | `.pre-commit-config.yaml` + CI | 10 | essential-rules -> Security Assessment (SAST) | bandit als pre-commit-Hook, semgrep in CI (s. auch #5) | S |
| 21 | Security | `CREDENTIAL_ENCRYPTION_KEY` optional -- Klartext-Credentials moeglich | `config.py:106`, `main.py:151-160` | 9 | ASVS 5.0 V8 (Data Protection) | In Produktion Start verweigern wenn Key leer | S |
| 22 | Arch. | Keine Resource Limits in Docker | `docker-compose.yml` (alle Services) | 10 | architecture-rules -> Docker (Resource Limits) | `deploy.resources.limits` (mem_limit + cpus) pro Service | S |
| 23 | Arch. | SearXNG ohne Health Check | `docker-compose.yml:156-177` | 10 | architecture-rules -> Docker (Health Checks) | `healthcheck: wget -q --spider http://localhost:8080/` | S |
| 24 | Arch. | Evolution API: Bind Mount statt Named Volume | `docker-compose.yml:63` | 10 | architecture-rules -> Docker (Named Volumes fuer Prod) | Bind Mount durch Named Volume `evolution_instances` ersetzen | S |
| 25 | CI/CD | Pre-commit nutzt TruffleHog statt gitleaks | `.pre-commit-config.yaml:4-11` | 9 | github-rules -> Pre-Commit (gitleaks als Schritt 1) | TruffleHog durch gitleaks ersetzen, oder Regel anpassen | S |
| 26 | CI/CD | CI nutzt `uv sync --extra dev` statt `--frozen` | `.github/workflows/ci.yml:31+70` | 10 | github-rules -> CI Pipeline (uv sync --frozen) | `uv sync --frozen --extra dev` | S |
| 27 | CI/CD | CI Secret-Scan nutzt TruffleHog statt gitleaks-action | `.github/workflows/ci.yml:86-89` | 9 | github-rules -> Secret Scanning (3-Schichten) | gitleaks-action@v2 ergaenzen oder ersetzen | S |
| 28 | Observ. | Timestamps nicht explizit UTC in structlog | `logging_config.py:20` | 8 | app-rules -> Logging (Timestamps in UTC) | `structlog.processors.TimeStamper(fmt="iso", utc=True)` | S |
| 29 | Observ. | Kein OpenTelemetry | projekt-weit | 10 | app-rules -> Observability (OTel Standard) | `opentelemetry-instrumentation-fastapi` installieren; Prio niedrig fuer Solo | L |
| 30 | Observ. | Saturation-Signal fehlt in Prometheus Metrics | `metrics.py` | 9 | app-rules -> Observability (4 goldene Signale) | `process_resident_memory_bytes` Gauge oder `prometheus_client.platform_collector` | S |
| 31 | Observ. | Kein Uptime Monitoring | projekt-weit | 9 | app-rules -> Monitoring (UptimeRobot) | UptimeRobot Free (50 Monitors) auf `/health` konfigurieren | S |
| 32 | Observ. | Kein Log-Aggregationsdienst | projekt-weit | 8 | app-rules -> Logging (Better Stack / Axiom) | Better Stack (1GB/mo free) oder Axiom anbinden | M |
| 33 | Observ. | `/health` prueft keine DB-Konnektivitaet | `main.py:758` | 9 | app-rules -> Deployment (Readiness = Backing Services) | In `/ready` einen `SELECT 1` gegen PostgreSQL ausfuehren | S |
| 34 | Observ. | pip-audit: 3 bekannte CVEs in Dependencies | CI known-ignores | 10 | github-rules -> Security Scanning (SCA) | CVEs evaluieren: genutzter Code-Pfad? Wenn ja, patchen; wenn nicht, Ignore dokumentiert lassen | S |
| 35 | Tests | main.py Lifespan nicht getestet | `main.py` | 8 | architecture-rules -> Testing (Endpoints) | Startup/Shutdown mit gemockten Stores testen | M |
| 36 | Tests | ContextBuilder.build_messages nur indirekt getestet | `agent/context.py` | 7 | architecture-rules -> Testing (Data Transformationen) | Unit-Tests fuer Memory-Injection, Calendar-Source, Prompt-Assembly | M |
| 37 | Tests | E2E-Tests laufen nicht in CI | `tests/e2e/` | 10 | architecture-rules -> Testing (E2E Smoke Test) | PostgreSQL-Service in CI (zusammen mit #12) | L |
| 38 | Tests | Keine Branch-Coverage konfiguriert | `pyproject.toml:155-166` | 10 | architecture-rules -> Testing (60-70% Branches) | `[tool.coverage.run] branch = true` setzen | S |
| 39 | Tests | Admin-Routes nur teilweise getestet | `sources/web/_admin.py` u.a. | 8 | architecture-rules -> Testing (Endpoints) | admin_users_page, admin_hard_delete, legal pages | M |
| 40 | Tests | Keine Tests fuer WhatsApp/Signal-Typ-Events in process_event_stream | `agent/core.py` | 8 | architecture-rules -> Testing (Verhalten) | Tests mit `type: "whatsapp"` und `type: "signal"` Events | S |
| 41 | Tests | Kein Test fuer Crypto Key-Rotation | `crypto.py` | 7 | architecture-rules -> Testing (Kritische Pfade) | Key-Rotation, Edge-Cases (leerer String, None) | S |
| 42 | Code | `sync/caldav.py` ist 489 LOC | `sync/caldav.py` | 10 | Code-Qualitaet -> Datei >400 LOC | iCal-Erzeugung in `ical_parser.py` extrahieren | M |
| 43 | Code | `actions/briefing.py` ist 464 LOC | `actions/briefing.py` | 10 | Code-Qualitaet -> Datei >400 LOC | Wetter-Logik in `actions/weather_forecast.py` | M |
| 44 | Code | Duplikation: `_is_private_host()` in carddav_manager.py | `sync/carddav_manager.py:19` | 10 | Code-Qualitaet -> Duplikation | `from niles.network import is_private_host` nutzen | S |
| 45 | Code | mypy global: `check_untyped_defs = false` | `pyproject.toml:108` | 10 | Code-Qualitaet -> Typisierung | Schrittweise auf `true` setzen | L |
| 46 | Code | `__getattr__` Magic in NilesAgent delegiert an _ctx | `agent/core.py:443-456` | 9 | Code-Qualitaet -> Code-Klarheit | Explizite Properties oder `self._ctx.X` direkt nutzen | M |
| 47 | Code | `event: dict` ohne TypedDict | `agent/core.py:468+720` | 9 | Code-Qualitaet -> Typisierung | `TypedDict` oder `dataclass` fuer Event-Daten | S |
| 48 | Code | `parse_icalendar()` Return-Type ist `dict | None` | `sync/ical_parser.py:157` | 9 | Code-Qualitaet -> Typisierung | `TypedDict CalendarEvent` oder Dataclass | M |
| 49 | Code | SignalAction erstellt eigenen httpx.AsyncClient | `actions/signal.py:18` | 9 | Code-Qualitaet -> Architecture (Connection Pooling) | Geteilten `HttpClients`-Client nutzen wie andere Actions | S |
| 50 | Code | Verschachtelung >4 in embed_pending() | `sync/notion_embeddings.py:131-233` | 9 | Code-Qualitaet -> Verschachtelung >4 | `_embed_summary()` extrahieren | S |
| 51 | Code | Verschachtelung >4 in process_event_stream() | `agent/core.py:551-601` | 9 | Code-Qualitaet -> Verschachtelung >4 | `_accumulate_stream_deltas()` extrahieren | M |
| 52 | Code | `notion_retriever` als `object | None` typisiert | `agent/core.py:420` | 10 | Code-Qualitaet -> Typisierung | `NotionRetriever | None` mit TYPE_CHECKING-Import | S |
| 53 | Code | mypy override `ical_parser.py` unterdrueckt 4 Codes | `pyproject.toml:124-125` | 9 | Code-Qualitaet -> mypy Overrides | TypedDict statt `dict | None` als Return-Type | M |
| 54 | Code | Funktionen >50 LOC: embed_pending (155), find_by_name (145), notion_connect (148), chat_stream (125), callback_google (164), search (124), fetch_messages (110), expand_recurring_event (111), prepare_messages (106) | diverse | 9-10 | Code-Qualitaet -> Funktion >50 LOC | Innere Logik in Hilfsmethoden extrahieren | M-L |

### LOW

| # | Achse | Titel | Datei:Zeile | Confidence | Verletzte Regel | Fix | Aufwand |
|---|---|---|---|---|---|---|---|
| 55 | Security | Login Rate-Limiter In-Memory, kein Eviction-Limit | `sources/web/_auth.py:38-57` | 8 | essential-rules -> Rate Limiting auf Login | Eviction analog zu RateLimitMiddleware.MAX_TRACKED_IPS | S |
| 56 | Security | Fehlende Audit-Logs (Compliance) | `_admin.py`, `_auth.py`, `_settings.py` | 9 | ASVS 5.0 V7 (Security Logging) | Dedizierte Audit-Log-Funktion: `{audit, actor, action, target, result, ip}` | M |
| 57 | Security | CSP `report-uri` deprecated, `report-to` fehlt | `main.py:623` | 8 | essential-rules -> Security Headers | `report-to` + `Reporting-Endpoints` Header ergaenzen | S |
| 58 | Security | `vikunja_api_url` Setting ohne SSRF-Pruefung | `sources/web/_vikunja.py:46-47` | 7 | essential-rules -> Input validieren | URL-Schema-Check + optional `is_private_host()` | S |
| 59 | Security | `searxng_url` ohne `is_private_host()` | `settings_store.py:139-144` | 7 | essential-rules -> Input validieren | Dokumentieren als bewusst erlaubt (interner Service) | S |
| 60 | Arch. | Port hardcoded in entrypoint.sh | `docker/entrypoint.sh:8` | 9 | architecture-rules -> 12-Factor (Port Binding) | `--port "${PORT:-8000}"` | S |
| 61 | Arch. | Rate Limiter In-Memory (12-Factor VI) | `main.py:551-593` | 8 | architecture-rules -> 12-Factor (Stateless) | Fuer Solo OK; bei Skalierung Redis-Backend | M |
| 62 | Arch. | Tote Env-Vars: FEATURE_SIGNAL, FEATURE_CARDDAV_SYNC | `docker-compose.yml:198,214` | 10 | architecture-rules -> 12-Factor (Config) | In config.py aufnehmen oder aus compose entfernen | S |
| 63 | Arch. | Tests nicht neben dem Code (top-level `tests/`) | `tests/` | 9 | architecture-rules -> Projekt-Struktur | Bewusste Abweichung: top-level tests/ ist Python-Konvention, dokumentieren | S |
| 64 | Arch. | Kein shared/ Ordner fuer cross-cutting Utilities | `src/niles/` | 7 | architecture-rules -> Projekt-Struktur | crypto, errors, http_clients etc. in `shared/` buendeln; bei aktuellem Umfang optional | M |
| 65 | Arch. | Migrations im Entrypoint statt eigener Container | `docker/entrypoint.sh:5` | 8 | architecture-rules -> 12-Factor XII (Admin Processes) | Separater `docker compose run` Command; fuer Solo OK | M |
| 66 | Arch. | Kein expliziter SIGTERM-Timeout | `docker/entrypoint.sh:8` | 7 | architecture-rules -> 12-Factor IX (Disposability) | `--timeout-graceful-shutdown 30` an Uvicorn | S |
| 67 | CI/CD | Renovate devDeps Automerge greift nicht bei Python | `renovate.json:5-9` | 8 | github-rules -> Dependency Management | `matchDepTypes: ["optionalDependencies"]` statt `devDependencies` | S |
| 68 | CI/CD | Coverage-Schwelle 65% statt 70% | `pyproject.toml:161` | 10 | github-rules -> Testing (70-80%) | `fail_under = 70` (zusammen mit #10) | S |
| 69 | CI/CD | mypy `check_untyped_defs = false` schwaecht Type-Checking | `pyproject.toml:108` | 7 | github-rules -> Type Check Qualitaet | Schrittweise verschaerfen (zusammen mit #45) | L |
| 70 | Observ. | pip in Builder-Stage nicht gepinnt | `Dockerfile.niles:8` | 7 | github-rules -> Docker (Digest pinnen) | `pip==XX.Y.Z` pinnen | S |
| 71 | Code | `weekdays_de` dreifach definiert | `prompts.py:45+123`, `briefing.py:297` | 10 | Code-Qualitaet -> Duplikation | `WEEKDAYS_DE` als exportierte Konstante | S |
| 72 | Code | Diverse fehlende Type-Hints | `briefing.py:62`, `manager.py:52`, `_core.py:307`, `contacts.py:68` | 8-10 | Code-Qualitaet -> Typisierung | Type-Hints ergaenzen | S |
| 73 | Code | `_state()` Funktion in `_core.py` moeglicherweise toter Code | `sources/web/_core.py:23-25` | 8 | Code-Qualitaet -> Toter Code | Konsistent nutzen oder entfernen | S |
| 74 | Code | Backward-Compat-Aliase in `context.py` | `agent/context.py:400-405` | 9 | Code-Qualitaet -> Toter Code | Pruefen ob noch genutzt, sonst entfernen | S |
| 75 | Code | Private Funktionen mit `_` werden oeffentlich importiert | `sources/web/_core.py:23-284` | 7 | Code-Qualitaet -> Naming | Underscores entfernen oder in `auth.py` verschieben | M |
| 76 | Code | Inkonsistente Error-Response-Patterns in Tool-Handlern | `agent/tools/*.py` | 8 | Code-Qualitaet -> Naming / API Design | `ToolResult` TypedDict einfuehren | M |

---

## Empfohlene Fix-Reihenfolge

### Phase 1: Security & Shared Utilities (Quick Wins)

1. **#21** `CREDENTIAL_ENCRYPTION_KEY` in Produktion erzwingen (S)
2. **#5 + #20** Semgrep in CI + bandit in pre-commit (S)
3. **#19** SSRF-Schutz fuer `llm_base_url` (S)
4. **#44** Duplizierte `_is_private_host()` durch `network.is_private_host` ersetzen (S)
5. **#26** CI: `uv sync --frozen --extra dev` (S)

### Phase 2: CI/CD & Branch Protection

6. **#1** GitHub Pro/Team oder Repo public -- Branch Protection aktivieren (M)
7. **#25 + #27** gitleaks vs. TruffleHog Entscheidung konsolidieren (S)
8. **#67** Renovate-Config fuer Python anpassen (S)

### Phase 3: Observability

9. **#7** Sentry installieren und konfigurieren (M)
10. **#33** `/health` mit DB-Check erweitern (S)
11. **#31** UptimeRobot konfigurieren (S)
12. **#28** structlog UTC explizit setzen (S)
13. **#30** Saturation-Metrik in Prometheus (S)

### Phase 4: Refactoring (groesste LOC-Reduktion)

14. **#17** TOOLS in `agent/tool_definitions.py` auslagern (S, reduziert core.py um 339 LOC)
15. **#4 + #14** `main.py` Lifespan + Middleware aufteilen (L)
16. **#16** `process_event()` als Wrapper ueber `process_event_stream()` (M)
17. **#46** `__getattr__` Magic durch explizite Delegation ersetzen (M)
18. **#43** Wetter-Logik aus briefing.py extrahieren (M)

### Phase 5: Tests

19. **#2** UserStore Unit-Tests (M)
20. **#3** OAuth Callback Tests (M)
21. **#12 + #37** PostgreSQL-Service in CI fuer Integration/E2E (L)
22. **#10 + #68** Coverage auf 70% erhoehen (L)
23. **#38** Branch-Coverage aktivieren (S)

### Phase 6: Kosmetik & Typisierung

24. **#47** `event: dict` durch TypedDict ersetzen (S)
25. **#48** `parse_icalendar()` Return als TypedDict (M)
26. **#45** mypy `check_untyped_defs = true` schrittweise (L)
27. **#71-76** Kleinere Code-Qualitaet-Findings (S-M)

---

## DORA-Metriken [Schaetzung]

| Metrik | Schaetzung | Bewertung |
|---|---|---|
| Deployment Frequency | Bei Bedarf / wenige Male pro Woche (manuell via docker compose) | Low-Medium |
| Lead Time for Changes | Minuten bis Stunden (Solo, kein Approval-Gate, CI ~3-5 Min) | Medium-High |
| Change Failure Rate | Nicht messbar (kein Prod-Monitoring) | n/a |
| Mean Time to Recovery | Nicht messbar (kein Auto-Rollback, manuelles Docker-Tag-Rollback) | n/a |

---

## Positive Befunde (kein Handlungsbedarf)

- **Strukturiertes JSON-Logging** via structlog korrekt konfiguriert
- **Correlation IDs** (Request-ID) sauber implementiert via `RequestIdMiddleware`
- **Keine Secrets in Logs** (Passwoerter, API-Keys, Tokens werden nirgends geloggt)
- **Prometheus Metrics** vorhanden: HTTP Requests/Duration, LLM Duration/Tokens, Tool Calls, Active SSE
- **`/health` und `/ready` Endpoints** vorhanden
- **Dockerfile:** Multi-Stage Build, Digest-pinned Base Images, Non-root User, HEALTHCHECK
- **`.dockerignore`** vollstaendig
- **Log-Rotation** in docker-compose fuer alle Container (`max-size: 10m, max-file: 3`)
- **Exponentielles Backoff** mit Jitter via tenacity
- **Metrics-Endpoint** API-Key-geschuetzt
- **Argon2id** Passwort-Hashing korrekt implementiert
- **Fernet-Verschluesselung** fuer Drittanbieter-Credentials
- **CSP nonce-basiert** mit `'strict-dynamic'` korrekt umgesetzt
- **Session Cookies** mit httpOnly, secure, sameSite=Lax
- **SSRF-Schutz** via `is_private_host()` fuer Calendar-Sources vorhanden
- **Alembic Migrations** korrekt konfiguriert
- **Renovate** fuer Dependency-Updates aktiv
- **Feature-basierte Ordnerstruktur** weitgehend eingehalten
- **Monolith-Architektur** als Solo-Projekt korrekt gewaehlt
- **Prepared Statements** durchgaengig via SQLAlchemy
- **Pre-commit Hooks** vorhanden (Secret Scan, PII, Lint, Format, Type Check)
- **CI-Pipeline** deckt Lint, Format, Type Check, Tests, Dependency Audit, Container Scan ab

---

*Erstellt mit KI-Unterstuetzung (Claude Code + dev-best-practices Plugin).
Findings sind zu verifizieren -- kein Ersatz fuer manuelle Penetrationstests.*
