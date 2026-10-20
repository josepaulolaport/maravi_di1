"""Revision 0004, second part: no staleness (OQ-31).

The catalog equivalence with `docs/schema.sql` is in `test_migrations_match_schema.py`. Here: the
date statuses take their new names (a STALE chain with a published row is processed, with issues
when its figures have them; without one, or computed on a stale predecessor, it failed), each
chain gets its processing time, the STALE_PREDECESSOR issues and the issue chain go, and the
downgrade gives the old names back.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import psycopg
import pytest
from alembic import command

from tests.integration.alembic_support import alembic_config, database_url, execute, fetch
from tests.integration.databases import psycopg_url
from tests.integration.test_no_reference_copy_migration import A_PUBLISHED_ROW, INSTRUMENT

__all__ = ["database_url"]

REQUEST = "00000000-0000-0000-0000-0000000000c1"
PUBLISHED_AT = "2026-10-18 21:30:00+00"
A_RUN = (
    "INSERT INTO processing.requests (id, scope, start_date, end_date,"
    f" status) VALUES ('{REQUEST}', 'ALL', '2026-10-01', '2026-10-04', 'COMPLETED_WITH_ISSUES');"
)
PUBLISHED_DAYS = (
    "INSERT INTO portfolio.portfolio_metrics (metric_date, valuation_status, pnl_status,"
    f" updated_at) VALUES ('2026-10-01', 'COMPLETE', 'COMPLETE', '{PUBLISHED_AT}'),"
    f" ('2026-10-02', 'COMPLETE', 'COMPLETE', '{PUBLISHED_AT}'),"
    f" ('2026-10-03', 'MISSING', 'MISSING', '{PUBLISHED_AT}');"
    "INSERT INTO portfolio.cash_balances (balance_date, cash_balance, trades_cash_flow,"
    f" deposits, withdrawals, updated_at) VALUES ('2026-10-01', 0, 0, 0, 0, '{PUBLISHED_AT}'),"
    f" ('2026-10-02', 0, 0, 0, 0, '{PUBLISHED_AT}'), ('2026-10-03', 0, 0, 0, 0, '{PUBLISHED_AT}');"
)
STATUSES = (
    "INSERT INTO processing.date_status (date, portfolio, cash, portfolio_previous)"
    " VALUES ('2026-10-01', 'FRESH', 'FRESH_WITH_ISSUES', NULL),"
    " ('2026-10-02', 'STALE', 'STALE', NULL),"
    " ('2026-10-03', 'STALE', 'FRESH', NULL),"
    " ('2026-10-04', 'RUNNING', NULL, 'STALE'),"
    " ('2026-10-05', NULL, 'STALE', NULL);"
)
ISSUES = (
    "INSERT INTO processing.issues (request_id, asset_id, affected_date, issue_type, chain)"
    f" VALUES ('{REQUEST}', NULL, '2026-10-02', 'STALE_PREDECESSOR', 'CASH'),"
    f" ('{REQUEST}', '{INSTRUMENT}', '2026-10-03', 'MISSING_REFERENCE_PRICE', NULL);"
)
PUBLISHED = datetime(2026, 10, 18, 21, 30, tzinfo=UTC)
READ_STATUSES = (
    "SELECT date, portfolio, cash, portfolio_previous,"
    " portfolio_processed_at IS NOT NULL, cash_processed_at IS NOT NULL"
    " FROM processing.date_status ORDER BY date"
)


def test_upgrade_renames_the_statuses_and_keeps_each_processing_time(database_url: str) -> None:
    command.upgrade(alembic_config(database_url), "0003")
    execute(database_url, A_PUBLISHED_ROW + A_RUN + PUBLISHED_DAYS + STATUSES + ISSUES)

    command.upgrade(alembic_config(database_url), "0004")

    assert fetch(database_url, READ_STATUSES) == [
        (date(2026, 10, 1), "PROCESSED", "PROCESSED", None, True, True),
        (date(2026, 10, 2), "PROCESSED", "FAILED", None, True, True),
        (date(2026, 10, 3), "PROCESSED_WITH_ISSUES", "PROCESSED", None, True, True),
        (date(2026, 10, 4), "RUNNING", None, "FAILED", False, False),
        (date(2026, 10, 5), None, "FAILED", None, False, False),
    ]
    assert fetch(
        database_url,
        "SELECT DISTINCT portfolio_processed_at, cash_processed_at FROM processing.date_status"
        " WHERE portfolio_processed_at IS NOT NULL",
    ) == [(PUBLISHED, PUBLISHED)]
    assert fetch(database_url, "SELECT issue_type FROM processing.issues") == [
        ("MISSING_REFERENCE_PRICE",)
    ]


def test_a_stale_status_is_refused_after_the_upgrade(database_url: str) -> None:
    command.upgrade(alembic_config(database_url), "0004")

    with pytest.raises(psycopg.errors.CheckViolation):
        execute(
            database_url,
            "INSERT INTO processing.date_status (date, cash) VALUES ('2026-10-01', 'STALE')",
        )


def test_downgrade_gives_the_old_names_back(database_url: str) -> None:
    command.upgrade(alembic_config(database_url), "0004")
    execute(
        database_url,
        "INSERT INTO processing.date_status (date, portfolio, cash, cash_previous) VALUES"
        " ('2026-10-01', 'PROCESSED', 'RUNNING', 'PROCESSED_WITH_ISSUES')",
    )

    command.downgrade(alembic_config(database_url), "0003")

    assert fetch(
        database_url, "SELECT portfolio, cash, cash_previous FROM processing.date_status"
    ) == [("FRESH", "RUNNING", "FRESH_WITH_ISSUES")]
    with psycopg.connect(psycopg_url(database_url)) as connection:
        columns = connection.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = 'processing'"
            " AND table_name = 'issues' AND column_name = 'chain'"
        ).fetchall()
    assert columns == [("chain",)]
