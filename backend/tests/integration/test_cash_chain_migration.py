"""Revision 0002: cash and positions as two separately processable chains (OQ-21, OQ-22).

The catalog equivalence with `docs/schema.sql` is in `test_migrations_match_schema.py`. Here:

- upgrade carries existing rows over: requests get scope ALL; the ledger revision and the
  accounting marker seed both new revisions and both new markers; published cash, which has no
  components, is dropped, AUM becomes unavailable and cash is stale from the first published day;
  a stale predecessor issue becomes a POSITIONS one; staged rows are cleared;
- downgrade folds them back: revisions summed, the earliest marker kept, CASH issues dropped;
- neither direction runs while a job is active, and downgrade refuses to lose rows unless
  ``-x allow_data_loss=true`` is given;
- an ALL job can record one stale predecessor issue per chain.
"""

from __future__ import annotations

from datetime import date

import psycopg
import pytest
from alembic import command

from tests.support.builders import DI1F27
from tests.support.db import alembic_config, catalogue_sql, execute, fetch

REQUEST = "00000000-0000-0000-0000-000000000001"
INSTRUMENT = str(DI1F27.id)
A_REQUEST = (
    "INSERT INTO processing.requests (id, scope, requested_start_date, requested_end_date)"
    f" VALUES ('{REQUEST}', 'ALL', '2026-10-01', '2026-10-05');"
)
AN_INSTRUMENT = catalogue_sql((DI1F27,))


def test_upgrade_carries_existing_rows_over(database_url: str) -> None:
    command.upgrade(alembic_config(database_url), "0001")
    execute(
        database_url,
        "INSERT INTO processing.requests (requested_start_date, requested_end_date,"
        " ledger_revision_at_start) VALUES ('2026-10-01', '2026-10-05', 7);"
        "UPDATE processing.calculation_state SET ledger_revision = 7,"
        " accounting_dirty_from = '2026-10-10';"
        "INSERT INTO portfolio.portfolio_metrics (metric_date, cash_balance,"
        " positions_market_value, aum, valuation_status, pnl_status)"
        " VALUES ('2026-10-03', 100, 50, 150, 'COMPLETE', 'COMPLETE');"
        "INSERT INTO processing.issues (request_id, affected_date, issue_type)"
        " SELECT id, '2026-10-01', 'STALE_PREDECESSOR' FROM processing.requests;"
        "INSERT INTO portfolio.staged_portfolio_metrics (request_id, metric_date, cash_balance,"
        " valuation_status, pnl_status)"
        " SELECT id, '2026-10-01', 0, 'COMPLETE', 'COMPLETE' FROM processing.requests;",
    )

    command.upgrade(alembic_config(database_url), "0002")

    requests = fetch(
        database_url,
        "SELECT scope, trades_revision_at_start, cash_movements_revision_at_start"
        " FROM processing.requests",
    )
    state = fetch(
        database_url,
        "SELECT trades_revision, cash_movements_revision, cash_dirty_from, positions_dirty_from"
        " FROM processing.calculation_state",
    )
    metrics = fetch(
        database_url, "SELECT positions_market_value, aum FROM portfolio.portfolio_metrics"
    )
    issues = fetch(database_url, "SELECT issue_type, chain FROM processing.issues")
    staged = fetch(database_url, "SELECT count(*) FROM portfolio.staged_portfolio_metrics")
    assert requests == [("ALL", 7, 7)]
    assert issues == [("STALE_PREDECESSOR", "POSITIONS")]
    assert state == [(7, 7, date(2026, 10, 3), date(2026, 10, 10))]
    assert [(str(value), aum) for value, aum in metrics] == [("50", None)]
    assert staged == [(0,)]


def test_upgrade_of_a_clean_database_leaves_no_marker(database_url: str) -> None:
    command.upgrade(alembic_config(database_url), "0002")

    state = fetch(
        database_url,
        "SELECT trades_revision, cash_movements_revision, cash_dirty_from, positions_dirty_from"
        " FROM processing.calculation_state",
    )
    assert state == [(0, 0, None, None)]


def test_downgrade_folds_revisions_and_markers_back(database_url: str) -> None:
    command.upgrade(alembic_config(database_url), "0002")
    execute(
        database_url,
        A_REQUEST + f"UPDATE processing.requests SET trades_revision_at_start = 3,"
        f" cash_movements_revision_at_start = 1 WHERE id = '{REQUEST}';"
        "UPDATE processing.calculation_state SET trades_revision = 5,"
        " cash_movements_revision = 2, cash_dirty_from = '2026-10-08',"
        " positions_dirty_from = '2026-10-04';"
        "INSERT INTO processing.issues (request_id, affected_date, issue_type, chain)"
        f" SELECT '{REQUEST}', '2026-10-01', 'STALE_PREDECESSOR', chain"
        " FROM (VALUES ('CASH'), ('POSITIONS')) AS chains (chain);",
    )

    command.downgrade(alembic_config(database_url, "allow_data_loss=true"), "0001")

    state = fetch(
        database_url,
        "SELECT ledger_revision, accounting_dirty_from FROM processing.calculation_state",
    )
    requests = fetch(database_url, "SELECT ledger_revision_at_start FROM processing.requests")
    issues = fetch(database_url, "SELECT count(*) FROM processing.issues")
    assert state == [(7, date(2026, 10, 4))]
    assert requests == [(4,)]
    assert issues == [(1,)]


LOSSY = {
    "published cash": "INSERT INTO portfolio.cash_balances VALUES ('2026-10-01', 100, 0, 100, 0)",
    "staged cash": A_REQUEST
    + "INSERT INTO portfolio.staged_cash_balances (request_id, balance_date, cash_balance,"
    f" trades_cash_flow, deposits, withdrawals) VALUES ('{REQUEST}', '2026-10-01', 0, 0, 0, 0)",
    "published metrics": "INSERT INTO portfolio.portfolio_metrics (metric_date,"
    " valuation_status, pnl_status) VALUES ('2026-10-01', 'COMPLETE', 'COMPLETE')",
    "staged positions": A_REQUEST
    + AN_INSTRUMENT
    + "INSERT INTO portfolio.staged_positions (request_id, asset_id, position_date, quantity)"
    f" VALUES ('{REQUEST}', '{INSTRUMENT}', '2026-10-01', 5)",
    "staged metrics": A_REQUEST
    + "INSERT INTO portfolio.staged_portfolio_metrics (request_id, metric_date,"
    f" valuation_status, pnl_status) VALUES ('{REQUEST}', '2026-10-01', 'COMPLETE', 'COMPLETE')",
    "a CASH request": "INSERT INTO processing.requests (scope, requested_start_date,"
    " requested_end_date) VALUES ('CASH', '2026-10-01', '2026-10-02')",
    "a CASH issue": A_REQUEST
    + "INSERT INTO processing.issues (request_id, affected_date, issue_type, chain)"
    f" VALUES ('{REQUEST}', '2026-10-01', 'STALE_PREDECESSOR', 'CASH')",
}


@pytest.mark.parametrize("rows", LOSSY.values(), ids=LOSSY.keys())
def test_downgrade_refuses_to_lose_rows(database_url: str, rows: str) -> None:
    command.upgrade(alembic_config(database_url), "0002")
    execute(database_url, rows)

    with pytest.raises(RuntimeError, match="allow_data_loss"):
        command.downgrade(alembic_config(database_url), "0001")
    command.downgrade(alembic_config(database_url, "allow_data_loss=true"), "0001")

    tables = fetch(
        database_url,
        "SELECT count(*) FROM information_schema.tables WHERE table_name = 'cash_balances'",
    )
    assert tables == [(0,)]


def test_an_all_job_records_one_stale_predecessor_per_chain(database_url: str) -> None:
    command.upgrade(alembic_config(database_url), "0002")
    execute(
        database_url,
        A_REQUEST + "INSERT INTO processing.issues (request_id, affected_date, issue_type, chain)"
        f" SELECT '{REQUEST}', '2026-10-05', 'STALE_PREDECESSOR', chain"
        " FROM (VALUES ('CASH'), ('POSITIONS')) AS chains (chain);",
    )

    with pytest.raises(psycopg.errors.CheckViolation):
        execute(
            database_url,
            "INSERT INTO processing.issues (request_id, affected_date, issue_type)"
            f" VALUES ('{REQUEST}', '2026-10-06', 'STALE_PREDECESSOR')",
        )
    with pytest.raises(psycopg.errors.UniqueViolation):
        execute(
            database_url,
            "INSERT INTO processing.issues (request_id, affected_date, issue_type, chain)"
            f" VALUES ('{REQUEST}', '2026-10-05', 'STALE_PREDECESSOR', 'CASH')",
        )


CHECKS = {
    "no scope": "INSERT INTO processing.requests (requested_start_date, requested_end_date)"
    " VALUES ('2026-10-01', '2026-10-02')",
    "unknown scope": "INSERT INTO processing.requests (scope, requested_start_date,"
    " requested_end_date) VALUES ('BOTH', '2026-10-01', '2026-10-02')",
    "aum without market value": "INSERT INTO portfolio.portfolio_metrics (metric_date, aum,"
    " valuation_status, pnl_status) VALUES ('2026-10-01', 1, 'COMPLETE', 'COMPLETE')",
    "negative withdrawals": "INSERT INTO portfolio.cash_balances"
    " VALUES ('2026-10-01', 100, 0, 100, -1)",
}


@pytest.mark.parametrize("statement", CHECKS.values(), ids=CHECKS.keys())
def test_the_new_constraints_reject_invalid_rows(database_url: str, statement: str) -> None:
    command.upgrade(alembic_config(database_url), "0002")

    with pytest.raises(psycopg.errors.IntegrityError):
        execute(database_url, statement)


@pytest.mark.parametrize("target", ["0002", "0001"])
def test_neither_direction_runs_while_a_job_is_active(database_url: str, target: str) -> None:
    command.upgrade(alembic_config(database_url), "0001" if target == "0002" else "0002")
    scope = "" if target == "0002" else "scope, "
    value = "" if target == "0002" else "'ALL', "
    execute(
        database_url,
        f"INSERT INTO processing.requests ({scope}requested_start_date, requested_end_date,"
        f" status) VALUES ({value}'2026-10-01', '2026-10-02', 'RUNNING')",
    )

    migrate = command.upgrade if target == "0002" else command.downgrade
    with pytest.raises(RuntimeError, match="job is active"):
        migrate(alembic_config(database_url), target)
