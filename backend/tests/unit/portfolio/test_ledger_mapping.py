"""Ledger's public records onto Portfolio's domain inputs (ports and adapters; OQ-24)."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal
from uuid import UUID

import pytest

from di1.modules.ledger.public import CashMovementRecord, TradeRecord
from di1.modules.portfolio.application.services.ledger_mapping import (
    daily_cash_totals,
    trade_of,
)
from di1.modules.portfolio.domain.errors import AccountingError
from di1.modules.portfolio.domain.trade import Trade
from di1.shared.input_kind import InputKind
from tests.unit.portfolio.factories import DI1F27

CREATED = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
MONDAY, TUESDAY = date(2027, 1, 4), date(2027, 1, 5)


def _movement(on: date, amount: str, seq: int) -> CashMovementRecord:
    return CashMovementRecord(UUID(int=seq), on, time(9), seq, Decimal(amount), CREATED)


def test_a_trade_record_maps_onto_the_accounting_trade() -> None:
    record = TradeRecord(
        id=UUID(int=1),
        asset_id=DI1F27,
        trade_date=MONDAY,
        trade_time=time(10, 30),
        seq=7,
        signed_quantity=-3,
        execution_pu=Decimal("95000.1234567890"),
        execution_rate=Decimal("0.105"),
        input_kind=InputKind.RATE,
        created_at=CREATED,
    )

    assert trade_of(record) == Trade(
        asset_id=DI1F27,
        trade_date=MONDAY,
        trade_time=time(10, 30),
        seq=7,
        signed_quantity=-3,
        execution_pu=Decimal("95000.1234567890"),
        execution_rate=Decimal("0.105"),
    )


def test_signed_cash_amounts_become_daily_deposit_and_withdrawal_totals() -> None:
    # OQ-24: a positive amount is an aporte, a negative one a retirada.
    # Monday: deposits 1000.50 + 200, withdrawal 300; Tuesday: withdrawal 0.01.
    deposits, withdrawals = daily_cash_totals(
        [
            _movement(MONDAY, "1000.50", 1),
            _movement(MONDAY, "-300.00", 2),
            _movement(MONDAY, "200", 3),
            _movement(TUESDAY, "-0.01", 4),
        ]
    )

    assert deposits == {MONDAY: Decimal("1200.50")}
    assert withdrawals == {MONDAY: Decimal("300.00"), TUESDAY: Decimal("0.01")}


def test_no_movement_gives_no_totals() -> None:
    assert daily_cash_totals([]) == ({}, {})


def test_a_zero_amount_is_rejected() -> None:
    # OQ-24: a cash amount is never 0 (schema CHECK); it is neither an aporte nor a retirada.
    with pytest.raises(AccountingError):
        daily_cash_totals([_movement(MONDAY, "0", 1)])
