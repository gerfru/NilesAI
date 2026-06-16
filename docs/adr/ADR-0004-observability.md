# ADR-0004: Observability via the homelab stack, not external SaaS

**Status:** Accepted · **Date:** 2026-06-16
**Driver:** App review L5–L8 (no external uptime ping, no alert thresholds, no log aggregation backend, OpenTelemetry absent)

## Context

The app already emits the raw signals — opt-in Sentry error tracking, Prometheus
metrics at `/metrics` (`niles_*`), structlog JSON to stdout with `X-Request-ID`
correlation, and `/health` + `/ready` probes. What was missing was the *glue*:
nothing external pinged the probes, there were no alert thresholds, logs lived only
in container stdout, and there was no distributed tracing. The original review
suggested external SaaS (UptimeRobot, Better Stack, Axiom). However, the deployment
already runs a full **homelab-gateway** observability stack: `gateway-prometheus`,
`gateway-loki` + `gateway-promtail`, `gateway-grafana`, `gateway-uptime`
(Uptime-Kuma), and `gateway-tempo`.

## Decision

- **Reuse the homelab stack instead of SaaS** — no new external services, no data
  egress, no subscription.
- **Uptime:** Uptime-Kuma monitors `https://niles.example.local/health` and `/ready`.
- **Metrics:** `gateway-prometheus` scrapes `/metrics` through the gateway; since the
  endpoint is `X-API-Key`-protected, **Caddy injects the key** for the scrape route
  so the secret stays out of the Prometheus config.
- **Alerts:** ship `docker/monitoring/niles-alerts.yml` (error rate > 1%, p95 > 2s,
  DB pool exhaustion, tool-repair rate, target down; plus host CPU/mem > 80% via
  node-exporter) into Prometheus + Alertmanager.
- **Logs:** `gateway-promtail` tails `niles_core` stdout (already JSON) → `gateway-loki`,
  correlate in Grafana by `request_id`. No app change needed.
- **OpenTelemetry:** deferred. Acceptable for a single-process monolith
  ([ADR-0001](ADR-0001-single-worker.md)); `gateway-tempo` is available as an OTLP
  backend if tracing is added later.

## Consequences

- No SaaS cost or third-party data sharing; everything stays on owned hardware.
- The wiring is split across repos: the alert rules + this documentation live in the
  Niles repo; the Prometheus scrape config, Caddy header injection, Promtail labels,
  and Uptime-Kuma monitors live in the **homelab-gateway** repo.
- Some setup is manual (Uptime-Kuma monitors are configured in its UI).
- Distributed tracing remains a future option, not a current capability.
