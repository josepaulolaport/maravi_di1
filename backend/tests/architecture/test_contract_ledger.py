"""Ledger's frozen public contract (plan §3, W0.3b; interfaces.md "Ledger")."""

from __future__ import annotations

import dataclasses
import inspect
import typing
from datetime import date, datetime, time
from decimal import Decimal
from uuid import uuid4

import pytest

from di1.modules.ledger.public import CashMovementRecord, EntryType, LedgerReader, TradeRecord
from di1.shared.clock import SAO_PAULO
from di1.shared.input_kind import InputKind

CREATED = datetime(2026, 10, 16, 18, 0, tzinfo=SAO_PAULO)


def _trade(trade_date: date, trade_time: time, seq: int) -> TradeRecord:
    return TradeRecord(
        id=uuid4(),
        asset_id=uuid4(),
        trade_date=trade_date,
        trade_time=trade_time,
        seq=seq,
        signed_quantity=-10,
        execution_pu=Decimal("98765.4321000000"),
        execution_rate=Decimal("0.135000000000"),
        input_kind=InputKind.RATE,
        created_at=CREATED,
    )


def _cash(movement_date: date, movement_time: time, seq: int) -> CashMovementRecord:
    return CashMovementRecord(
        id=uuid4(),
        movement_date=movement_date,
        movement_time=movement_time,
        seq=seq,
        amount=Decimal("-2500.50"),
        created_at=CREATED,
    )


def test_trades_order_by_date_then_time_then_seq() -> None:
    late_seq_first_time = _trade(date(2026, 10, 1), time(9, 0), 7)
    early_seq_later_time = _trade(date(2026, 10, 1), time(10, 0), 3)
    same_time_lower_seq = _trade(date(2026, 10, 1), time(9, 0), 5)
    previous_day = _trade(date(2026, 9, 30), time(17, 0), 9)

    ordered = sorted(
        [late_seq_first_time, early_seq_later_time, same_time_lower_seq, previous_day],
        key=lambda trade: trade.order_key,
    )

    assert ordered == [previous_day, same_time_lower_seq, late_seq_first_time, early_seq_later_time]


def test_trades_and_cash_share_one_order() -> None:
    trade = _trade(date(2026, 10, 1), time(10, 0), 7)
    withdrawal = _cash(date(2026, 10, 1), time(10, 0), 6)
    deposit = _cash(date(2026, 10, 1), time(9, 0), 8)

    entries: list[TradeRecord | CashMovementRecord] = [trade, withdrawal, deposit]
    ordered = sorted(entries, key=lambda entry: entry.order_key)

    assert ordered == [deposit, withdrawal, trade]


def test_records_are_frozen() -> None:
    trade = _trade(date(2026, 10, 1), time(9, 0), 1)
    movement = _cash(date(2026, 10, 1), time(9, 0), 2)

    with pytest.raises(dataclasses.FrozenInstanceError):
        trade.signed_quantity = 5  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        movement.amount = Decimal("1")  # type: ignore[misc]


def test_entry_type_names_the_schema_types() -> None:
    assert {entry_type.value for entry_type in EntryType} == {"TRADE", "CASH"}


def test_the_reader_answers_whether_entries_exist_up_to_a_day() -> None:
    # OQ-31 zero state, OQ-37: positions ask for TRADE, cash for any type.
    signature = inspect.signature(LedgerReader.has_entries_on_or_before)
    assert list(signature.parameters) == ["self", "day", "entry_type"]
    assert signature.parameters["entry_type"].kind is inspect.Parameter.KEYWORD_ONLY
    assert signature.parameters["entry_type"].default is None
    hints = typing.get_type_hints(LedgerReader.has_entries_on_or_before)
    assert hints["entry_type"] == EntryType | None  # the public EntryType, not a domain copy
    assert hints["day"] is date
    assert hints["return"] is bool
