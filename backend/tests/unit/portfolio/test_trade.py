"""Portfolio's trade input: chronological order and immutability (spec §6.1; OQ-13)."""

from __future__ import annotations

import dataclasses
from datetime import date

import pytest

from di1.modules.portfolio.domain.errors import AccountingError
from tests.unit.portfolio.factories import trade


def test_trades_order_by_date_then_time_then_seq() -> None:
    monday = date(2027, 1, 4)
    late_seq_early_time = trade(1, "95000", on=monday, at="09:00", seq=9)
    early_seq_late_time = trade(1, "95000", on=monday, at="11:00", seq=1)
    same_time_next_seq = trade(1, "95000", on=monday, at="09:00", seq=10)
    previous_day = trade(1, "95000", on=date(2027, 1, 3), at="18:00", seq=20)

    ordered = sorted(
        [early_seq_late_time, same_time_next_seq, late_seq_early_time, previous_day],
        key=lambda t: t.order_key,
    )

    assert ordered == [previous_day, late_seq_early_time, same_time_next_seq, early_seq_late_time]


def test_a_trade_is_immutable() -> None:
    executed = trade(1, "95000")

    with pytest.raises(dataclasses.FrozenInstanceError):
        executed.signed_quantity = 2  # type: ignore[misc]


def test_a_zero_quantity_trade_is_rejected() -> None:
    # Schema CHECK trades_qty_nonzero (OQ-14).
    with pytest.raises(AccountingError):
        trade(0, "95000")
