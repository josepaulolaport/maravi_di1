"""Cash and positions as two separately processable chains (OQ-21, OQ-22).

Upgrade and downgrade run the reviewed SQL in ``migrations/sql/0002_cash_chain*.sql``.
`tests/integration/test_migrations_match_schema.py` checks that 0001 + 0002 produce exactly the
database `docs/schema.sql` produces; `test_cash_chain_migration.py` how existing rows are
carried over.

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

# Both directions discard staged rows, which belong to the active job.
ACTIVE_JOB = (
    "SELECT EXISTS (SELECT 1 FROM processing.requests"
    " WHERE status IN ('DISPATCHED', 'RUNNING', 'CANCELLING'))"
)

# The downgrade cannot keep these: 0001 has no cash table, no request scope and no issue chain.
LOSSY_ROWS = {
    table: f"SELECT EXISTS (SELECT 1 FROM {table})"
    for table in (
        "portfolio.cash_balances",
        "portfolio.staged_cash_balances",
        "portfolio.portfolio_metrics",
        "portfolio.staged_positions",
        "portfolio.staged_portfolio_metrics",
    )
} | {
    "processing.requests (scope CASH/POSITIONS)": (
        "SELECT EXISTS (SELECT 1 FROM processing.requests WHERE scope <> 'ALL')"
    ),
    "processing.issues (chain CASH)": (
        "SELECT EXISTS (SELECT 1 FROM processing.issues WHERE chain = 'CASH')"
    ),
}


def _run(path: Path) -> None:
    sql = path.read_text()
    if context.is_offline_mode():
        op.execute(sql)
    else:
        op.get_bind().exec_driver_sql(sql)


def _data_loss_allowed() -> bool:
    return context.get_x_argument(as_dictionary=True).get("allow_data_loss") == "true"


def _refuse_while_a_job_is_active() -> None:
    if context.is_offline_mode() or _data_loss_allowed():
        return
    if op.get_bind().exec_driver_sql(ACTIVE_JOB).scalar():
        raise RuntimeError(
            "Refusing to migrate 0002 while a processing job is active (its staged rows would be "
            "lost); cancel it first, or rerun with `-x allow_data_loss=true`."
        )


def upgrade() -> None:
    _refuse_while_a_job_is_active()
    _run(UPGRADE)


def downgrade() -> None:
    _refuse_while_a_job_is_active()
    if not _data_loss_allowed() and not context.is_offline_mode():
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
