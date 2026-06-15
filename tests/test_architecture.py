"""Architecture fitness functions — enforce layer boundaries structurally."""

import pathlib

_ACTIONS_DIR = pathlib.Path(__file__).resolve().parents[1] / "src" / "niles" / "actions"

# Raw asyncpg query calls — the marker of data access done in the wrong layer.
_QUERY_CALLS = (".fetch(", ".fetchrow(", ".fetchval(", ".execute(", ".executemany(")

# Pre-existing offenders not yet migrated (tracked debt, out of scope for the
# contacts/calendar/briefing migration). notion.py should move to NotionStore.
_KNOWN_OFFENDERS = {"notion.py"}


def test_actions_do_not_run_sql_directly():
    """The service/action layer must go through Stores, never raw asyncpg queries.

    Data access lives in `*_store.py`; an action running SQL is a layering
    violation (Arch review HIGH #2). New offenders fail this test.
    """
    offenders = {path.name for path in _ACTIONS_DIR.glob("*.py") if any(c in path.read_text() for c in _QUERY_CALLS)}
    new_offenders = offenders - _KNOWN_OFFENDERS
    assert new_offenders == set(), (
        f"actions/ must use Stores, not raw asyncpg queries: {sorted(new_offenders)}. Move the SQL into a *_store.py."
    )
