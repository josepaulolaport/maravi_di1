"""The shared trade value (spec §6.1, §7.3; OQ-13, OQ-14)."""

from __future__ import annotations

import dataclasses
from datetime import date, time
from decimal import Decimal
from uuid import UUID

import pytest

from di1.shared.trades import Trade

ASSET = UUID("00000000-0000-0000-0000-000000000027")


def _trade(*, on: date, at: time, seq: int, quantity: int = 1) -> Trade:
    return Trade(
        asset_id=ASSET,
        trade_date=on,
        trade_time=at,
        seq=seq,
        signed_quantity=quantity,
        execution_pu=Decimal("95000"),
        execution_rate=Decimal("0.1"),
    )


def test_trades_order_by_date_then_time_then_seq() -> None:
    late_seq_early_time = _trade(on=date(2027, 1, 4), at=time(9), seq=9)
    early_seq_late_time = _trade(on=date(2027, 1, 4), at=time(11), seq=1)
    same_time_next_seq = _trade(on=date(2027, 1, 4), at=time(9), seq=10)
    previous_day = _trade(on=date(2027, 1, 3), at=time(18), seq=20)

    ordered = sorted(
        [early_seq_late_time, same_time_next_seq, late_seq_early_time, previous_day],
        key=lambda t: t.order_key,
    )

    assert ordered == [previous_day, late_seq_early_time, same_time_next_seq, early_seq_late_time]


def test_a_zero_quantity_is_rejected() -> None:
    # Schema CHECK trades_qty_nonzero (OQ-14).
    with pytest.raises(ValueError):
        _trade(on=date(2027, 1, 4), at=time(9), seq=1, quantity=0)


def test_a_trade_is_immutable() -> None:
    trade = _trade(on=date(2027, 1, 4), at=time(9), seq=1)

    with pytest.raises(dataclasses.FrozenInstanceError):
        trade.signed_quantity = 2  # type: ignore[misc]
