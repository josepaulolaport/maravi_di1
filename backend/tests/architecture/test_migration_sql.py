"""The reviewed SQL of the Alembic revisions (skill `db-migration`; plan §3).

Released revisions never change, so the SQL of 0001, 0002 and 0003 is pinned here by hash.
`docs/schema.sql` is the result of all revisions, not the text of one;
`tests/integration/test_migrations_match_schema.py` checks on PostgreSQL that the revisions build
exactly what `docs/schema.sql` builds. No database is needed here, so this runs in the pre-commit
hook.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
SQL = BACKEND / "migrations" / "sql"
RELEASED_SHA256 = {
    "0001_initial.sql": "302d46335f931f92ead97da292e9858bd5be9b6a4d9cecbd93bf9f714dbb849f",
    "0002_cash_chain.sql": "24e558e4eff422e63debecdd3c6111d2a5c30147858dc6c7f81829bcb00e640f",
    "0002_cash_chain_downgrade.sql": (
        "9b0c987dc9b14df71d99339207c43ce6460a0757bd8ef7cce15b9a4a7712737b"
    ),
    "0003_one_status_per_date.sql": (
        "205546ae1cc21738293e3a944a1c55bd01f43ab42a3f35db9a53152ae5715f38"
    ),
    "0003_one_status_per_date_downgrade.sql": (
        "89afdaf018799d5bcd9f424913fb175381a17200de8cfc48201b5e05a91c48a7"
    ),
}


def test_released_revision_sql_is_never_edited() -> None:
    for name, expected in RELEASED_SHA256.items():
        assert hashlib.sha256((SQL / name).read_bytes()).hexdigest() == expected, name


def test_every_revision_sql_runs_inside_alembics_transaction() -> None:
    for path in sorted(SQL.glob("*.sql")):
        lines = {line.strip().upper() for line in path.read_text().splitlines()}
        assert not lines & {"BEGIN;", "COMMIT;"}, path.name
