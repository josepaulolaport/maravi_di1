"""Revision 0007: an optional description on cash entries (OQ-51).

The catalog equivalence with `docs/schema.sql` is in `test_migrations_match_schema.py`. Here: a
cash entry takes a description of up to 200 characters or none, a trade takes none, existing
entries get NULL, and the downgrade drops the column.
"""

from __future__ import annotations

import psycopg
import pytest
from alembic import command

from tests.support.builders import DI1F27
from tests.support.db import alembic_config, catalogue_sql, execute, fetch

AN_INSTRUMENT = catalogue_sql((DI1F27,))
A_DEPOSIT = (
    "INSERT INTO ledger.entries (type, entry_date, entry_time, cash_amount{columns})"
    " VALUES ('CASH', '2026-10-01', '10:00', 1000{values})"
)
A_TRADE = (
    "INSERT INTO ledger.entries (type, entry_date, entry_time, asset_id, signed_quantity,"
    " execution_pu, execution_rate, input_kind{columns}) VALUES ('TRADE', '2026-10-01', '10:00',"
    f" '{DI1F27.id}', 1, 90000, 0.1, 'PU'{{values}})"
)
COLUMN = (
    "SELECT column_name FROM information_schema.columns WHERE table_schema = 'ledger'"
    " AND table_name = 'entries' AND column_name = 'description'"
)


def test_a_cash_entry_takes_a_description_of_up_to_200_characters_or_none(
    database_url: str,
) -> None:
    command.upgrade(alembic_config(database_url), "0007")
    execute(database_url, A_DEPOSIT.format(columns=", description", values=", 'Aporte inicial'"))
    execute(database_url, A_DEPOSIT.format(columns=", description", values=f", '{'a' * 200}'"))
    execute(database_url, A_DEPOSIT.format(columns="", values=""))

    assert fetch(database_url, "SELECT description FROM ledger.entries ORDER BY seq") == [
        ("Aporte inicial",),
        ("a" * 200,),
        (None,),
    ]


def test_a_description_longer_than_200_characters_is_refused(database_url: str) -> None:
    command.upgrade(alembic_config(database_url), "0007")

    with pytest.raises(psycopg.errors.StringDataRightTruncation):
        execute(database_url, A_DEPOSIT.format(columns=", description", values=f", '{'a' * 201}'"))


def test_a_trade_takes_no_description(database_url: str) -> None:
    command.upgrade(alembic_config(database_url), "0007")
    execute(database_url, AN_INSTRUMENT)
    execute(database_url, A_TRADE.format(columns="", values=""))

    with pytest.raises(psycopg.errors.CheckViolation):
        execute(database_url, A_TRADE.format(columns=", description", values=", 'Compra'"))


def test_existing_entries_get_no_description(database_url: str) -> None:
    command.upgrade(alembic_config(database_url), "0006")
    execute(database_url, A_DEPOSIT.format(columns="", values=""))

    command.upgrade(alembic_config(database_url), "0007")

    assert fetch(database_url, "SELECT description FROM ledger.entries") == [(None,)]


def test_downgrade_drops_the_column(database_url: str) -> None:
    command.upgrade(alembic_config(database_url), "0007")
    execute(database_url, A_DEPOSIT.format(columns=", description", values=", 'Aporte inicial'"))

    command.downgrade(alembic_config(database_url), "0006")

    assert fetch(database_url, COLUMN) == []
    assert fetch(database_url, "SELECT cash_amount::text FROM ledger.entries") == [("1000.00",)]
