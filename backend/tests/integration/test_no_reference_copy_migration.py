"""Revision 0004: the reference PU and source leave position_metrics (OQ-30).

The catalog equivalence with `docs/schema.sql` is in `test_migrations_match_schema.py`. Here: the
published metrics survive the upgrade without the two columns, and the downgrade brings the
columns back empty.
"""

from __future__ import annotations

from decimal import Decimal

from alembic import command

from tests.support.builders import DI1F27
from tests.support.db import alembic_config, catalogue_sql, execute, fetch

INSTRUMENT = str(DI1F27.id)
A_PUBLISHED_ROW = (
    catalogue_sql((DI1F27,)) + "INSERT INTO portfolio.positions (asset_id, position_date, quantity)"
    f" VALUES ('{INSTRUMENT}', '2026-10-01', 10);"
)
COLUMNS = (
    "SELECT column_name FROM information_schema.columns WHERE table_schema = 'portfolio'"
    " AND table_name = 'position_metrics' AND column_name LIKE 'reference%' ORDER BY 1"
)


def test_upgrade_keeps_the_published_figures_without_the_price_copy(database_url: str) -> None:
    command.upgrade(alembic_config(database_url), "0003")
    execute(
        database_url,
        A_PUBLISHED_ROW
        + "INSERT INTO portfolio.position_metrics (asset_id, metric_date, reference_pu,"
        " reference_source, financial_total, valuation_status, pnl_status)"
        f" VALUES ('{INSTRUMENT}', '2026-10-01', 90000, 'MANUAL', 900000, 'COMPLETE',"
        " 'COMPLETE')",
    )

    command.upgrade(alembic_config(database_url), "0004")

    assert fetch(database_url, COLUMNS) == []
    assert fetch(database_url, "SELECT financial_total FROM portfolio.position_metrics") == [
        (Decimal("900000"),)
    ]


def test_downgrade_brings_the_columns_back_empty(database_url: str) -> None:
    command.upgrade(alembic_config(database_url), "0004")
    execute(
        database_url,
        A_PUBLISHED_ROW
        + "INSERT INTO portfolio.position_metrics (asset_id, metric_date, financial_total,"
        f" valuation_status, pnl_status) VALUES ('{INSTRUMENT}', '2026-10-01', 900000,"
        " 'COMPLETE', 'COMPLETE')",
    )

    command.downgrade(alembic_config(database_url), "0003")

    assert fetch(database_url, COLUMNS) == [("reference_pu",), ("reference_source",)]
    assert fetch(
        database_url, "SELECT reference_pu, reference_source FROM portfolio.position_metrics"
    ) == [(None, None)]
