# ADR-0001: Single-worker process model

**Status:** Accepted · **Date:** 2026-06-16
**Driver:** Arch + App review LOW (single worker as a scaling ceiling) — a deliberate constraint, documented rather than "fixed"

## Context

Niles keeps several pieces of coordination state **in-process memory**:

- the login/request rate limiter (`OrderedDict` in `RateLimitMiddleware`, `main.py`),
- pending confirmations and phone-number choices (`_pending_confirmations` /
  `_pending_phone_choices` in `agent/context.py`),
- per-source echo-loop guards (`sources/echo_guard.py`),
- active SSE connection bookkeeping (the `ACTIVE_SSE` gauge).

None of this is shared across processes. Running more than one uvicorn worker would
split this state per worker: rate limits would be undercounted, a confirmation issued
on worker A could be replayed against worker B, and echo guards would miss duplicates.
For a self-hosted single-user-household butler the throughput of one worker is ample.

## Decision

- Run Niles as a **single uvicorn worker**. The app fails fast if misconfigured:
  `main.py` reads `WEB_CONCURRENCY` and errors when it is `> 1`.
- Treat horizontal scaling as **out of scope** for the current deployment target
  (one household on one Mac Mini), not as a defect.

## Consequences

- Simplicity: no Redis/shared-store dependency, no sticky-session requirement at the
  reverse proxy, straightforward local reasoning about state.
- Hard ceiling: throughput and availability are bounded by one process; a crash drops
  all in-flight SSE streams and transient state.
- If multi-worker / multi-instance is ever required, the in-memory structures above
  must first move to a shared backend (e.g. Redis) and the `WEB_CONCURRENCY` guard
  relaxed — a deliberate, separate migration.
