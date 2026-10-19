"""A run records where it first failed: failed_date and failed_chain (OQ-40).

Upgrade and downgrade run the reviewed SQL in ``migrations/sql/0006_failed_chain*.sql``.
`tests/integration/test_migrations_match_schema.py` checks that the revisions build exactly what
`docs/schema.sql` builds. The downgrade drops the two columns; a run's failure is not kept.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-19
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from alembic import context, op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SQL = Path(__file__).resolve().parents[1] / "sql"
UPGRADE = SQL / "0006_failed_chain.sql"
DOWNGRADE = SQL / "0006_failed_chain_downgrade.sql"


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
