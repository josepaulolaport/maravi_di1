"""One status per date and chain, day-by-day publication, one ledger entry table, reference prices
without revisions (OQ-23, OQ-24, OQ-25).

Upgrade and downgrade run the reviewed SQL in ``migrations/sql/0003_one_status_per_date*.sql``.
`tests/integration/test_migrations_match_schema.py` checks that the revisions build exactly what
`docs/schema.sql` builds; `test_one_status_per_date_migration.py` how rows are carried over.
The downgrade rebuilds the 0002 structure empty, on a database without business data only.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-18
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from alembic import context, op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SQL = Path(__file__).resolve().parents[1] / "sql"
UPGRADE = SQL / "0003_one_status_per_date.sql"
DOWNGRADE = SQL / "0003_one_status_per_date_downgrade.sql"

# Both directions rewrite what a running job reads and writes.
ACTIVE_JOB = (
    "SELECT EXISTS (SELECT 1 FROM processing.requests"
    " WHERE status IN ('DISPATCHED', 'RUNNING', 'CANCELLING'))"
)

# The rollback carries nothing back: it runs only on a database without business data.
BUSINESS_TABLES = (
    "ledger.entries",
    "prices.reference_prices",
    "processing.requests",
    "processing.date_status",
    "portfolio.positions",
    "portfolio.portfolio_metrics",
    "portfolio.cash_balances",
)


def _run(path: Path) -> None:
    sql = path.read_text()
    if context.is_offline_mode():
        op.execute(sql)
    else:
        op.get_bind().exec_driver_sql(sql)


def _data_loss_allowed() -> bool:
    return context.get_x_argument(as_dictionary=True).get("allow_data_loss") == "true"


def _refuse_while_a_job_is_active() -> None:
    # Not bypassed by allow_data_loss: that option only accepts losing rows on a downgrade.
    if context.is_offline_mode():
        return
    if op.get_bind().exec_driver_sql(ACTIVE_JOB).scalar():
        raise RuntimeError(
            "Refusing to migrate 0003 while a processing job is active; cancel it first."
        )


def upgrade() -> None:
    _refuse_while_a_job_is_active()
    _run(UPGRADE)


def downgrade() -> None:
    _refuse_while_a_job_is_active()
    if not _data_loss_allowed() and not context.is_offline_mode():
        bind = op.get_bind()
        holding = [
            table
            for table in BUSINESS_TABLES
            if bind.exec_driver_sql(f"SELECT EXISTS (SELECT 1 FROM {table})").scalar()
        ]
        if holding:
            raise RuntimeError(
                "Refusing to downgrade 0003 on a database with data in "
                f"{', '.join(holding)}: the rollback carries nothing back. Rerun with "
                "`-x allow_data_loss=true` if this database is disposable."
            )
    _run(DOWNGRADE)
