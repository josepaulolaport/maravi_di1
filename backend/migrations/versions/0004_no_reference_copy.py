"""Results without copies or staleness: the reference PU and source leave position_metrics, since
prices live only in the price table (OQ-30); the STALE status, the STALE_PREDECESSOR issue and the
issue chain go, the date statuses are renamed and get processing times (OQ-31).

Upgrade and downgrade run the reviewed SQL in ``migrations/sql/0004_*.sql``, in that order up and
in reverse order down.
`tests/integration/test_migrations_match_schema.py` checks that the revisions build exactly what
`docs/schema.sql` builds. The downgrade restores the dropped columns empty.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-19
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from alembic import context, op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SQL = Path(__file__).resolve().parents[1] / "sql"
UPGRADES = (SQL / "0004_no_reference_copy.sql", SQL / "0004_no_staleness.sql")
DOWNGRADES = (SQL / "0004_no_staleness_downgrade.sql", SQL / "0004_no_reference_copy_downgrade.sql")


def _run(path: Path) -> None:
    sql = path.read_text()
    if context.is_offline_mode():
        op.execute(sql)
    else:
        op.get_bind().exec_driver_sql(sql)


def upgrade() -> None:
    for path in UPGRADES:
        _run(path)


def downgrade() -> None:
    for path in DOWNGRADES:
        _run(path)
