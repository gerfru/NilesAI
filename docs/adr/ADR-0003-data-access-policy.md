# ADR-0003: Data access via Stores, never raw SQL in the action layer

**Status:** Accepted · **Date:** 2026-06-16
**Driver:** Arch review HIGH #2 (data-access bypass — raw `asyncpg` queries scattered through the action/service layer)

## Context

Database access used to be spread across the action layer: actions ran `asyncpg`
queries (`fetch`/`fetchrow`/`fetchval`/`execute`) directly. That made the data-access
boundary invisible, duplicated query logic, and — most importantly — pushed per-user
scoping into ad-hoc call sites, where a missing `WHERE user_id = …` is a cross-tenant
leak (the same root cause as the W2 fail-closed isolation fix).

## Decision

- All persistence lives in dedicated **Store classes** (`*_store.py`): `ContactStore`,
  `EventStore`, plus the existing `WhatsAppSessionStore`, `VikunjaCredentialStore`,
  `SignalMessageStore`, `MemoryStore`, `UserStore`, `SettingsStore`.
- The **action/service layer never imports `asyncpg`** and never runs SQL directly —
  it goes through a Store.
- **Per-user scoping is enforced inside the Stores** and fails closed: a query without
  a resolved `user_id` returns nothing rather than spanning all tenants.
- This is enforced **structurally** by an architecture fitness test
  (`tests/test_architecture.py::test_actions_do_not_run_sql_directly`): any new
  `actions/*.py` running raw queries fails CI. One tracked offender remains
  (`actions/notion.py` → should move to a `NotionStore`), recorded as known debt.

## Consequences

- Clear, testable data-access boundary; query logic and scoping live in one place.
- Tests inject fake Stores instead of mocking a database.
- New offenders are caught automatically by the fitness test.
- Migration is not 100 % complete: `actions/notion.py` still issues queries and is
  whitelisted in the fitness test until it is moved to a Store.
