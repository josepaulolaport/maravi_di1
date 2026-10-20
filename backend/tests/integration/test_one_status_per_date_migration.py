"""Revision 0003: one status per date and chain, one ledger entry table, prices without revisions
(OQ-23, OQ-24, OQ-25).

The catalog equivalence with `docs/schema.sql` and with 0002 after a downgrade is in
`test_migrations_match_schema.py`. Here:

- upgrade carries rows over: trades keep id and seq, cash movements follow with signed amounts at
  00:00; only current price revisions stay, and the published metrics keep the source of their PU
  (also when it was a superseded revision); each published date gets its chain statuses from the
  old markers and its issues; a SUPERSEDED request becomes FAILED and an unfinished old run loses
  its progress date; the staging tables go;
- downgrade rebuilds the 0002 structure empty: it refuses on business data unless
  ``-x allow_data_loss=true``, and then carries nothing back;
- the new constraints reject malformed rows;
- neither direction runs while a job is active.
"""

from __future__ import annotations

from datetime import date, time
from decimal import Decimal

import psycopg
import pytest
from alembic import command

from tests.integration.alembic_support import alembic_config, database_url, execute, fetch

__all__ = ["database_url"]

INSTRUMENT = "00000000-0000-0000-0000-0000000000a1"
PRODUCT = "00000000-0000-0000-0000-0000000000b1"
OLD_PRICE = "00000000-0000-0000-0000-0000000000c1"
CURRENT_PRICE = "00000000-0000-0000-0000-0000000000c2"
AN_INSTRUMENT = (
    "INSERT INTO asset.instrument_types (id, code, name) VALUES (1, 'FUTURE', 'Futuro');"
    "INSERT INTO asset.asset_classes (id, instrument_type_id, code, name)"
    " VALUES (1, 1, 'INTEREST_RATE_FUTURE', 'Futuro de juros');"
    "INSERT INTO asset.products (id, asset_class_id, code, name)"
    f" VALUES ('{PRODUCT}', 1, 'DI1', 'DI1');"
    "INSERT INTO asset.instruments (id, product_id, code, maturity_date)"
    f" VALUES ('{INSTRUMENT}', '{PRODUCT}', 'DI1F27', '2027-01-01');"
)


def _a_0002_database(database_url: str) -> None:
    command.upgrade(alembic_config(database_url), "0002")
    execute(
        database_url,
        AN_INSTRUMENT
        + "INSERT INTO ledger.trades (id, asset_id, trade_date, trade_time, seq, signed_quantity,"
        " execution_pu, execution_rate, input_kind) VALUES"
        f" ('00000000-0000-0000-0000-000000000011', '{INSTRUMENT}', '2026-10-01', '10:00', 5,"
        " 10, 90000, 0.1, 'RATE'),"
        f" ('00000000-0000-0000-0000-000000000012', '{INSTRUMENT}', '2026-10-02', '11:00', 9,"
        " -4, 90100, 0.099, 'PU');"
        "INSERT INTO ledger.cash_movements (id, movement_date, movement_type, amount) VALUES"
        " ('00000000-0000-0000-0000-000000000021', '2026-10-01', 'DEPOSIT', 1000000),"
        " ('00000000-0000-0000-0000-000000000022', '2026-10-02', 'WITHDRAWAL', 2500.50);"
        "INSERT INTO prices.reference_prices (id, asset_id, reference_date, source, input_kind,"
        " pu, revision, created_at, superseded_at) VALUES"
        f" ('{OLD_PRICE}', '{INSTRUMENT}', '2026-10-01', 'MANUAL', 'PU', 90050, 1,"
        " '2026-10-01 18:00-03', '2026-10-01 19:00-03'),"
        f" ('{CURRENT_PRICE}', '{INSTRUMENT}', '2026-10-01', 'MANUAL', 'PU', 90060, 2,"
        " '2026-10-01 19:00-03', NULL);"
        "INSERT INTO portfolio.positions (asset_id, position_date, quantity)"
        f" VALUES ('{INSTRUMENT}', '2026-10-01', 10);"
        "INSERT INTO portfolio.position_metrics (asset_id, metric_date, reference_price_id,"
        " reference_pu, valuation_status, pnl_status)"
        f" VALUES ('{INSTRUMENT}', '2026-10-01', '{OLD_PRICE}', 90050, 'COMPLETE', 'COMPLETE');"
        "INSERT INTO portfolio.portfolio_metrics (metric_date, positions_market_value,"
        " valuation_status, pnl_status) VALUES"
        " ('2026-10-01', 900600, 'COMPLETE', 'COMPLETE'),"
        " ('2026-10-02', NULL, 'MISSING', 'MISSING'),"
        " ('2026-10-03', 1, 'COMPLETE', 'COMPLETE');"
        "INSERT INTO portfolio.cash_balances VALUES"
        " ('2026-10-01', 100000, -900000, 1000000, 0),"
        " ('2026-10-02', 100000, 0, 0, 0);"
        "UPDATE processing.calculation_state SET cash_dirty_from = '2026-10-02',"
        " positions_dirty_from = '2026-10-03', valuation_dirty_from = '2026-10-05';"
        "INSERT INTO processing.requests (id, scope, requested_start_date, requested_end_date,"
        " status, progress_date) VALUES ('00000000-0000-0000-0000-000000000031', 'ALL',"
        " '2026-10-01', '2026-10-03', 'SUPERSEDED', '2026-10-02');"
        "INSERT INTO processing.requests (id, scope, requested_start_date, requested_end_date,"
        " status, created_at) VALUES"
        " ('00000000-0000-0000-0000-000000000032', 'ALL', '2026-10-01', '2026-10-01',"
        " 'COMPLETED_WITH_ISSUES', '2026-10-05 10:00-03'),"
        " ('00000000-0000-0000-0000-000000000033', 'ALL', '2026-10-01', '2026-10-02',"
        " 'COMPLETED_WITH_ISSUES', '2026-10-06 10:00-03');"
        "INSERT INTO processing.issues (request_id, asset_id, affected_date, issue_type) VALUES"
        f" ('00000000-0000-0000-0000-000000000031', '{INSTRUMENT}', '2026-10-02',"
        " 'MISSING_REFERENCE_PRICE'),"
        f" ('00000000-0000-0000-0000-000000000032', '{INSTRUMENT}', '2026-10-01',"
        " 'MISSING_REFERENCE_PRICE'),"
        f" ('00000000-0000-0000-0000-000000000033', '{INSTRUMENT}', '2026-10-01',"
        " 'EXPIRED_OPEN_POSITION');",
    )


def test_upgrade_carries_existing_rows_over(database_url: str) -> None:
    _a_0002_database(database_url)

    command.upgrade(alembic_config(database_url), "0003")

    entries = fetch(
        database_url,
        "SELECT type, entry_date, entry_time, seq, signed_quantity, cash_amount"
        " FROM ledger.entries ORDER BY entry_date, entry_time, seq",
    )
    prices = fetch(database_url, "SELECT id::text, pu FROM prices.reference_prices")
    source = fetch(database_url, "SELECT reference_source FROM portfolio.position_metrics")
    statuses = fetch(
        database_url, "SELECT date, portfolio, cash FROM processing.date_status ORDER BY date"
    )
    requests = fetch(
        database_url,
        "SELECT start_date, end_date, status, error_code, progress_date FROM processing.requests"
        " WHERE status = 'FAILED'",
    )
    staging = fetch(
        database_url,
        "SELECT count(*) FROM information_schema.tables WHERE table_name LIKE 'staged%'",
    )
    assert entries == [
        ("CASH", date(2026, 10, 1), time(0, 0), 10, None, Decimal("1000000.00")),
        ("TRADE", date(2026, 10, 1), time(10, 0), 5, 10, None),
        ("CASH", date(2026, 10, 2), time(0, 0), 11, None, Decimal("-2500.50")),
        ("TRADE", date(2026, 10, 2), time(11, 0), 9, -4, None),
    ]
    assert prices == [(CURRENT_PRICE, Decimal("90060"))]
    assert source == [("MANUAL",)]
    assert statuses == [
        (date(2026, 10, 1), "FRESH_WITH_ISSUES", "FRESH"),
        (date(2026, 10, 2), "FRESH_WITH_ISSUES", "STALE"),
        (date(2026, 10, 3), "STALE", None),
    ]
    issues = fetch(
        database_url, "SELECT request_id::text, affected_date, issue_type FROM processing.issues"
    )
    assert requests == [(date(2026, 10, 1), date(2026, 10, 3), "FAILED", "SUPERSEDED", None)]
    assert issues == [
        ("00000000-0000-0000-0000-000000000033", date(2026, 10, 1), "EXPIRED_OPEN_POSITION")
    ]
    assert staging == [(0,)]


def test_a_new_entry_follows_the_moved_ones(database_url: str) -> None:
    _a_0002_database(database_url)
    command.upgrade(alembic_config(database_url), "0003")

    execute(
        database_url,
        "INSERT INTO ledger.entries (type, entry_date, entry_time, cash_amount)"
        " VALUES ('CASH', '2026-10-03', '09:00', 10)",
    )

    assert fetch(database_url, "SELECT max(seq) FROM ledger.entries") == [(12,)]


BUSINESS_ROWS = {
    "a ledger entry": "INSERT INTO ledger.entries (type, entry_date, entry_time, cash_amount)"
    " VALUES ('CASH', '2026-10-01', '00:00', 10)",
    "a reference price": AN_INSTRUMENT
    + "INSERT INTO prices.reference_prices (asset_id, reference_date, source, input_kind, pu)"
    f" VALUES ('{INSTRUMENT}', '2026-10-01', 'B3', 'PU', 1)",
    "a request": "INSERT INTO processing.requests (scope, start_date, end_date)"
    " VALUES ('ALL', '2026-10-01', '2026-10-02')",
    "a date status": "INSERT INTO processing.date_status (date, cash)"
    " VALUES ('2026-10-01', 'FRESH')",
    "published cash": "INSERT INTO portfolio.cash_balances VALUES ('2026-10-01', 1, 0, 1, 0)",
}


@pytest.mark.parametrize("rows", BUSINESS_ROWS.values(), ids=BUSINESS_ROWS.keys())
def test_downgrade_refuses_a_database_with_business_data(database_url: str, rows: str) -> None:
    command.upgrade(alembic_config(database_url), "0003")
    execute(database_url, rows)

    with pytest.raises(RuntimeError, match="allow_data_loss"):
        command.downgrade(alembic_config(database_url), "0002")


def test_a_forced_downgrade_carries_nothing_back(database_url: str) -> None:
    _a_0002_database(database_url)
    command.upgrade(alembic_config(database_url), "0003")

    command.downgrade(alembic_config(database_url, "allow_data_loss=true"), "0002")

    counts = fetch(
        database_url,
        "SELECT (SELECT count(*) FROM ledger.trades), (SELECT count(*) FROM ledger.cash_movements),"
        " (SELECT count(*) FROM prices.reference_prices),"
        " (SELECT count(*) FROM processing.requests),"
        " (SELECT count(*) FROM portfolio.portfolio_metrics)",
    )
    instruments = fetch(database_url, "SELECT count(*) FROM asset.instruments")
    assert counts == [(0, 0, 0, 0, 0)]
    assert instruments == [(1,)]


def test_an_empty_database_downgrades_without_force(database_url: str) -> None:
    command.upgrade(alembic_config(database_url), "0003")

    command.downgrade(alembic_config(database_url), "0002")

    revision = fetch(database_url, "SELECT version_num FROM alembic_version")
    assert revision == [("0002",)]


REJECTED = {
    "trade without asset": "INSERT INTO ledger.entries (type, entry_date, entry_time,"
    " signed_quantity, execution_pu, execution_rate, input_kind)"
    " VALUES ('TRADE', '2026-10-01', '10:00', 1, 90000, 0.1, 'PU')",
    "trade with a cash amount": "INSERT INTO ledger.entries (type, entry_date, entry_time,"
    " asset_id, signed_quantity, execution_pu, execution_rate, input_kind, cash_amount)"
    f" VALUES ('TRADE', '2026-10-01', '10:00', '{INSTRUMENT}', 1, 90000, 0.1, 'PU', 5)",
    "cash of zero": "INSERT INTO ledger.entries (type, entry_date, entry_time, cash_amount)"
    " VALUES ('CASH', '2026-10-01', '10:00', 0)",
    "cash with a quantity": "INSERT INTO ledger.entries (type, entry_date, entry_time,"
    " cash_amount, signed_quantity) VALUES ('CASH', '2026-10-01', '10:00', 5, 1)",
    "unknown type": "INSERT INTO ledger.entries (type, entry_date, entry_time, cash_amount)"
    " VALUES ('FEE', '2026-10-01', '10:00', 5)",
    "batch without deletion": "INSERT INTO ledger.entries (type, entry_date, entry_time,"
    " cash_amount, deletion_batch_id) VALUES ('CASH', '2026-10-01', '10:00', 5,"
    " gen_random_uuid())",
    "unknown date status": "INSERT INTO processing.date_status (date, cash)"
    " VALUES ('2026-10-01', 'QUEUED')",
    "empty date status": "INSERT INTO processing.date_status (date) VALUES ('2026-10-01')",
    "previous status while not running": "INSERT INTO processing.date_status"
    " (date, cash, cash_previous) VALUES ('2026-10-01', 'FRESH', 'STALE')",
    "previous status RUNNING": "INSERT INTO processing.date_status"
    " (date, portfolio, portfolio_previous) VALUES ('2026-10-01', 'RUNNING', 'RUNNING')",
    "second price per source": "INSERT INTO prices.reference_prices (asset_id, reference_date,"
    f" source, input_kind, pu) VALUES ('{INSTRUMENT}', '2026-10-01', 'B3', 'PU', 1),"
    f" ('{INSTRUMENT}', '2026-10-01', 'B3', 'PU', 2)",
    "superseded run": "INSERT INTO processing.requests (scope, start_date, end_date, status)"
    " VALUES ('ALL', '2026-10-01', '2026-10-02', 'SUPERSEDED')",
    "progress outside the range": "INSERT INTO processing.requests (scope, start_date, end_date,"
    " progress_date) VALUES ('ALL', '2026-10-01', '2026-10-02', '2026-10-05')",
    "source without a PU": "INSERT INTO portfolio.positions (asset_id, position_date, quantity)"
    f" VALUES ('{INSTRUMENT}', '2026-10-01', 1); INSERT INTO portfolio.position_metrics"
    " (asset_id, metric_date, reference_source, valuation_status, pnl_status)"
    f" VALUES ('{INSTRUMENT}', '2026-10-01', 'B3', 'MISSING', 'MISSING')",
}


@pytest.mark.parametrize("statement", REJECTED.values(), ids=REJECTED.keys())
def test_the_new_constraints_reject_malformed_rows(database_url: str, statement: str) -> None:
    command.upgrade(alembic_config(database_url), "0003")
    execute(database_url, AN_INSTRUMENT)

    with pytest.raises(psycopg.errors.IntegrityError):
        execute(database_url, statement)


@pytest.mark.parametrize("target", ["0003", "0002"])
def test_neither_direction_runs_while_a_job_is_active(database_url: str, target: str) -> None:
    command.upgrade(alembic_config(database_url), "0002" if target == "0003" else "0003")
    dates = (
        "requested_start_date, requested_end_date" if target == "0003" else "start_date, end_date"
    )
    execute(
        database_url,
        f"INSERT INTO processing.requests (scope, {dates}, status)"
        " VALUES ('ALL', '2026-10-01', '2026-10-02', 'RUNNING')",
    )

    migrate = command.upgrade if target == "0003" else command.downgrade
    with pytest.raises(RuntimeError, match="job is active"):
        migrate(alembic_config(database_url), target)


ISSUE_ON_THE_FIRST = (
    "INSERT INTO processing.requests (id, scope, requested_start_date, requested_end_date,"
    " status, created_at) VALUES ('00000000-0000-0000-0000-000000000041', 'ALL',"
    " '2026-10-01', '2026-10-01', 'COMPLETED_WITH_ISSUES', '2026-10-05 10:00-03');"
    "INSERT INTO processing.issues (request_id, asset_id, affected_date, issue_type)"
    f" VALUES ('00000000-0000-0000-0000-000000000041', '{INSTRUMENT}', '2026-10-01',"
    " 'EXPIRED_OPEN_POSITION');"
)


@pytest.mark.parametrize(
    ("later_scope", "kept"), [("CASH", 1), ("POSITIONS", 0), ("ALL", 0)], ids=lambda v: str(v)
)
def test_a_later_run_prunes_only_the_issues_of_its_own_chain(
    database_url: str, later_scope: str, kept: int
) -> None:
    command.upgrade(alembic_config(database_url), "0002")
    execute(
        database_url,
        AN_INSTRUMENT
        + ISSUE_ON_THE_FIRST
        + "INSERT INTO processing.requests (scope, requested_start_date, requested_end_date,"
        f" status, created_at) VALUES ('{later_scope}', '2026-10-01', '2026-10-01', 'COMPLETED',"
        " '2026-10-06 10:00-03');",
    )

    command.upgrade(alembic_config(database_url), "0003")

    assert fetch(database_url, "SELECT count(*) FROM processing.issues") == [(kept,)]


@pytest.mark.parametrize("target", ["0003", "0002"])
def test_allow_data_loss_does_not_bypass_the_active_job_check(
    database_url: str, target: str
) -> None:
    command.upgrade(alembic_config(database_url), "0002" if target == "0003" else "0003")
    dates = (
        "requested_start_date, requested_end_date" if target == "0003" else "start_date, end_date"
    )
    execute(
        database_url,
        f"INSERT INTO processing.requests (scope, {dates}, status)"
        " VALUES ('ALL', '2026-10-01', '2026-10-02', 'RUNNING')",
    )

    migrate = command.upgrade if target == "0003" else command.downgrade
    with pytest.raises(RuntimeError, match="job is active"):
        migrate(alembic_config(database_url, "allow_data_loss=true"), target)
