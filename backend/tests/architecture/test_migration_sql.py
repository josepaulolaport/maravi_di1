"""The reviewed SQL of the Alembic revisions (skill `db-migration`; plan §3).

Released revisions never change, so the SQL of 0001 to 0006 is pinned here by hash.
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
    "0004_no_reference_copy.sql": (
        "83a5a462c086d1fc2d90487102fdf994f20c82fa76ad12c205a8eb9f4e84efd4"
    ),
    "0004_no_reference_copy_downgrade.sql": (
        "983e8f0fd1c1b145f27f28cf103d616b6a0137238786502a488d937c68d88d2c"
    ),
    "0004_no_staleness.sql": "b9b4e9a1ba0c33b293ea3d3c1caa8ff2f9239ef96b8e0885d5bcc9c392bcc3fb",
    "0004_no_staleness_downgrade.sql": (
        "355a6566ed7716131299e88535c3c3d33f20fb0cd2a9745f81a3326f6b62e430"
    ),
    "0005_hard_delete.sql": "200bc793e884ac332c3299990a94cbd306a4e2494cabe97d359c094c5062acd0",
    "0005_hard_delete_downgrade.sql": (
        "cafabdaedbc1b5c126b299c8db9b0fdd903f3093a01d69c5b57578de4652cbf3"
    ),
    "0006_failed_chain.sql": "2fe06af71e184b0c6e8b8ac698da05f296f4c0225b9231c832f167c68fb7bdfe",
    "0006_failed_chain_downgrade.sql": (
        "1e9a381f5ea9a62df8df4fbad1c72ed9433f4e46c76c25ad5fb5c7c96561bbc4"
    ),
}


def test_released_revision_sql_is_never_edited() -> None:
    for name, expected in RELEASED_SHA256.items():
        assert hashlib.sha256((SQL / name).read_bytes()).hexdigest() == expected, name


def test_every_revision_sql_runs_inside_alembics_transaction() -> None:
    for path in sorted(SQL.glob("*.sql")):
        lines = {line.strip().upper() for line in path.read_text().splitlines()}
        assert not lines & {"BEGIN;", "COMMIT;"}, path.name
