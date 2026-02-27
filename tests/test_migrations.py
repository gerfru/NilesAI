"""Tests for Alembic migration chain integrity.

These tests validate the migration files without requiring a live database.
"""

import os

from alembic.config import Config
from alembic.script import ScriptDirectory

_PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
_ALEMBIC_INI = os.path.join(_PROJECT_ROOT, "alembic.ini")


def _get_script_directory() -> ScriptDirectory:
    config = Config(_ALEMBIC_INI)
    config.set_main_option("script_location", os.path.join(_PROJECT_ROOT, "alembic"))
    return ScriptDirectory.from_config(config)


class TestMigrationChain:
    def test_migration_chain_complete(self):
        """All migrations form an unbroken chain from base to head."""
        scripts = _get_script_directory()
        revisions = list(scripts.walk_revisions())
        assert len(revisions) >= 2, (
            f"Expected at least 2 migrations, got {len(revisions)}"
        )

    def test_exactly_one_base_revision(self):
        """Exactly one migration has down_revision = None (the base)."""
        scripts = _get_script_directory()
        revisions = list(scripts.walk_revisions())
        bases = [r for r in revisions if r.down_revision is None]
        assert len(bases) == 1, f"Expected 1 base revision, got {len(bases)}"

    def test_baseline_references_all_tables(self):
        """Baseline migration (001) references all 11 expected table names."""
        scripts = _get_script_directory()
        baseline = scripts.get_revision("001")
        assert baseline is not None, "Baseline revision 001 not found"

        # Read the migration source file
        module_path = baseline.module.__file__
        with open(module_path) as f:
            source = f.read()

        expected_tables = [
            "users",
            "whatsapp_sessions",
            "vikunja_credentials",
            "contacts",
            "contact_phones",
            "calendar_sources",
            "events",
            "memory",
            "conversations",
            "signal_messages",
            "settings_overrides",
        ]
        for table in expected_tables:
            assert table in source, f"Table '{table}' not found in baseline migration"
