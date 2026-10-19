"""Ledger entries are hard-deleted: the deletion columns go (OQ-32).

Upgrade and downgrade run the reviewed SQL in ``migrations/sql/0005_hard_delete*.sql``.
`tests/integration/test_migrations_match_schema.py` checks that the revisions build exactly what
`docs/schema.sql` builds. The upgrade deletes the entries already soft-deleted; the downgrade
restores the columns empty and does not rebuild them.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-19
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from alembic import context, op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SQL = Path(__file__).resolve().parents[1] / "sql"
UPGRADE = SQL / "0005_hard_delete.sql"
DOWNGRADE = SQL / "0005_hard_delete_downgrade.sql"


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
