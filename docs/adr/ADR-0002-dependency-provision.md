# ADR-0002: Dependency provision via `Depends()` + typed `StartupContext`

**Status:** Accepted (incremental rollout) · **Date:** 2026-06-15
**Driver:** Arch review HIGH #1 (service-locator `app.state`) + MED #6 (`StartupContext` defined but unused)

## Context

Every collaborator (agent, stores, actions, managers) was attached to the mutable
`app.state` at startup, and each route handler pulled what it needed out of it by
attribute name (`request.app.state.x`, often via `getattr(..., None)`). This is the
Service Locator anti-pattern: a handler's signature reveals nothing about what it
touches, coupling is invisible, and every test must build/mocked a fat `app.state`.
A typed `StartupContext` dataclass existed but was never constructed (dead code);
the `setup_*` functions returned untyped `dict[str, Any]`.

## Decision

- Build a single **typed `StartupContext`** during startup and expose it as
  `app.state.ctx` — the source of truth for dependency injection.
- Provide dependencies to route handlers via FastAPI **`Depends()`** provider
  functions (`sources/web/_deps.py`) that read from `app.state.ctx`, so each
  handler **declares** its dependencies in its signature.
- Roll out **incrementally**, one router at a time. `sources/web/_vikunja.py` is
  the pilot (`get_vikunja_setup`). The individual `app.state.*` attributes remain
  for not-yet-migrated routers and are removed as each router migrates.

## Consequences

- Handlers declare dependencies explicitly; tests inject fakes directly instead
  of mocking `app.state`.
- `StartupContext` is now used (typed container), resolving the dead-abstraction.
- Transitional duplication: collaborators live both on `app.state.ctx` and as
  individual `app.state.*` until migration completes — accepted, tracked here.
