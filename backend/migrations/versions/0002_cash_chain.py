"""Cash and positions as two separately processable chains (OQ-21).

Upgrade and downgrade run the reviewed SQL in ``migrations/sql/0002_cash_chain*.sql``.
`tests/integration/test_cash_chain_migration.py` checks that 0001 + 0002 produce exactly the
database `docs/schema.sql` produces, and how existing rows are carried over.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-18
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from alembic import context, op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SQL = Path(__file__).resolve().parents[1] / "sql"
UPGRADE = SQL / "0002_cash_chain.sql"
DOWNGRADE = SQL / "0002_cash_chain_downgrade.sql"

# The downgrade cannot keep these: 0001 has no cash table and no request scope.
LOSSY_ROWS = {
    table: f"SELECT EXISTS (SELECT 1 FROM {table})"
    for table in (
        "portfolio.cash_balances",
        "portfolio.staged_cash_balances",
        "portfolio.portfolio_metrics",
    )
} | {
    "processing.requests (scope CASH/POSITIONS)": (
        "SELECT EXISTS (SELECT 1 FROM processing.requests WHERE scope <> 'ALL')"
    ),
}


def _run(path: Path) -> None:
    sql = path.read_text()
    if context.is_offline_mode():
        op.execute(sql)
    else:
        op.get_bind().exec_driver_sql(sql)


def upgrade() -> None:
    _run(UPGRADE)


def downgrade() -> None:
    allowed = context.get_x_argument(as_dictionary=True).get("allow_data_loss") == "true"
    if not allowed and not context.is_offline_mode():
        bind = op.get_bind()
        holding = [
            name for name, query in LOSSY_ROWS.items() if bind.exec_driver_sql(query).scalar()
        ]
        if holding:
            raise RuntimeError(
                "Refusing to downgrade 0002 while it would lose rows in "
                f"{', '.join(holding)}; rerun with `-x allow_data_loss=true` if they may go."
            )
    _run(DOWNGRADE)
