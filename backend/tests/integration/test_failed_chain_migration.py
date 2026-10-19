"""Revision 0006: a run records where it first failed (OQ-40).

The catalog equivalence with `docs/schema.sql` is in `test_migrations_match_schema.py`. Here: the
two columns accept a chain failure and a run-wide failure, refuse a chain without a date, an
unknown chain or a date outside the run, and the downgrade drops them.
"""

from __future__ import annotations

import psycopg
import pytest
from alembic import command

from tests.integration.test_initial_migration import _alembic
from tests.integration.test_migrations_match_schema import database_url, execute, fetch

__all__ = ["database_url"]

A_RUN = (
    "INSERT INTO processing.requests (id, scope, start_date, end_date, status, failed_date,"
    " failed_chain) VALUES"
)
COLUMNS = (
    "SELECT column_name FROM information_schema.columns WHERE table_schema = 'processing'"
    " AND table_name = 'requests' AND column_name LIKE 'failed%' ORDER BY 1"
)


def test_a_run_records_its_first_failure(database_url: str) -> None:
    command.upgrade(_alembic(database_url), "0006")
    execute(
        database_url,
        A_RUN + " (gen_random_uuid(), 'ALL', '2026-10-01', '2026-10-10', 'COMPLETED_WITH_ISSUES',"
        " '2026-10-03', 'POSITIONS'),"
        " (gen_random_uuid(), 'ALL', '2026-10-01', '2026-10-10', 'FAILED', '2026-10-02', NULL),"
        " (gen_random_uuid(), 'CASH', '2026-10-01', '2026-10-10', 'COMPLETED', NULL, NULL)",
    )

    assert fetch(
        database_url,
        "SELECT failed_date::text, failed_chain FROM processing.requests ORDER BY failed_date",
    ) == [("2026-10-02", None), ("2026-10-03", "POSITIONS"), (None, None)]


@pytest.mark.parametrize(
    "values",
    [
        "(gen_random_uuid(), 'ALL', '2026-10-01', '2026-10-10', 'FAILED', NULL, 'CASH')",
        "(gen_random_uuid(), 'ALL', '2026-10-01', '2026-10-10', 'FAILED', '2026-10-02', 'BOTH')",
        "(gen_random_uuid(), 'ALL', '2026-10-01', '2026-10-10', 'FAILED', '2026-10-11', 'CASH')",
    ],
    ids=["chain-without-date", "unknown-chain", "date-outside-run"],
)
def test_an_inconsistent_failure_is_refused(database_url: str, values: str) -> None:
    command.upgrade(_alembic(database_url), "0006")

    with pytest.raises(psycopg.errors.CheckViolation):
        execute(database_url, A_RUN + " " + values)


def test_downgrade_drops_the_columns(database_url: str) -> None:
    command.upgrade(_alembic(database_url), "0006")

    command.downgrade(_alembic(database_url), "0005")

    assert fetch(database_url, COLUMNS) == []
