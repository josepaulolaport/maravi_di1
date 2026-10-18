"""The initial revision runs exactly the reviewed schema (skill `db-migration`; plan §3).

`migrations/sql/0001_initial.sql` is `docs/schema.sql` without its own `BEGIN;`/`COMMIT;`, because
Alembic owns the transaction. No database is needed, so this runs in the pre-commit hook and
catches a schema edit that was not copied into the migration.
"""

from __future__ import annotations

from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
SCHEMA_SQL = BACKEND.parent / "docs" / "schema.sql"
MIGRATION_SQL = BACKEND / "migrations" / "sql" / "0001_initial.sql"


def test_migration_sql_is_the_documented_schema_without_its_transaction() -> None:
    documented = [
        line for line in SCHEMA_SQL.read_text().splitlines() if line not in ("BEGIN;", "COMMIT;")
    ]
    assert MIGRATION_SQL.read_text().splitlines() == documented
