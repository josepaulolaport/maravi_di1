"""The reference PU and source leave position_metrics: prices live only in the price table (OQ-30).

Upgrade and downgrade run the reviewed SQL in ``migrations/sql/0004_no_reference_copy*.sql``.
`tests/integration/test_migrations_match_schema.py` checks that the revisions build exactly what
`docs/schema.sql` builds. The downgrade restores the columns empty.

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
UPGRADE = SQL / "0004_no_reference_copy.sql"
DOWNGRADE = SQL / "0004_no_reference_copy_downgrade.sql"


def _run(path: Path) -> None:
    sql = path.read_text()
    if context.is_offline_mode():
        op.execute(sql)
    else:
        op.get_bind().exec_driver_sql(sql)


def upgrade() -> None:
    _run(UPGRADE)


def downgrade() -> None:
    _run(DOWNGRADE)
