"""The reviewed SQL of the Alembic revisions (skill `db-migration`; plan §3).

`migrations/sql/0001_initial.sql` is the initial schema as reviewed and applied: a released
revision never changes, so its content is pinned here. Since 0002, `docs/schema.sql` is the
result of all revisions, not the text of one; `tests/integration/test_cash_chain_migration.py`
checks on PostgreSQL that 0001 + 0002 build exactly what `docs/schema.sql` builds. No database
is needed here, so this runs in the pre-commit hook.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
SQL = BACKEND / "migrations" / "sql"
INITIAL_SHA256 = "302d46335f931f92ead97da292e9858bd5be9b6a4d9cecbd93bf9f714dbb849f"


def test_the_initial_revision_sql_is_never_edited() -> None:
    digest = hashlib.sha256((SQL / "0001_initial.sql").read_bytes()).hexdigest()
    assert digest == INITIAL_SHA256


def test_every_revision_sql_runs_inside_alembics_transaction() -> None:
    for path in sorted(SQL.glob("*.sql")):
        lines = {line.strip().upper() for line in path.read_text().splitlines()}
        assert not lines & {"BEGIN;", "COMMIT;"}, path.name
