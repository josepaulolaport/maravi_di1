"""Initial schema: `docs/schema.sql` exactly as reviewed (plan §3, Wave 0).

The SQL is read from `migrations/sql/0001_initial.sql`, a copy of `docs/schema.sql` without its own
``BEGIN;``/``COMMIT;`` (Alembic owns the transaction). A test keeps the two files identical.

Revision ID: 0001
Revises:
Create Date: 2026-10-18
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from alembic import context, op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SQL = Path(__file__).resolve().parents[1] / "sql" / "0001_initial.sql"

# Reverse dependency order. CASCADE also removes the cross-schema foreign keys.
SCHEMAS = ("platform", "portfolio", "processing", "prices", "ledger", "asset")

# Downgrade is for fresh or throwaway databases only (plan §3: "only where safe and documented").
# It refuses while any of these holds rows, unless `-x allow_data_loss=true` is given.
BUSINESS_TABLES = (
    "ledger.trades",
    "ledger.cash_movements",
    "prices.reference_prices",
    "processing.requests",
    "asset.instruments",
)


def upgrade() -> None:
    sql = SQL.read_text()
    if context.is_offline_mode():
        # `alembic upgrade --sql`: emit the reviewed SQL as written.
        op.execute(sql)
    else:
        # Driver-level execution: the reviewed SQL runs as written, with no bind-parameter parsing.
        op.get_bind().exec_driver_sql(sql)


def downgrade() -> None:
    allowed = context.get_x_argument(as_dictionary=True).get("allow_data_loss") == "true"
    if not allowed and not context.is_offline_mode():
        bind = op.get_bind()
        holding = [
            table
            for table in BUSINESS_TABLES
            if bind.exec_driver_sql(f"SELECT EXISTS (SELECT 1 FROM {table})").scalar()
        ]
        if holding:
            raise RuntimeError(
                "Refusing to drop a database that holds data in "
                f"{', '.join(holding)}; rerun with `-x allow_data_loss=true` if this database "
                "is disposable."
            )
    for schema in SCHEMAS:
        op.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
