"""Trades P&L: Σ q_i × (PU_D − PU_exec_i) (spec §8.1, §8.3).

``None`` when the day has trades and PU_D is missing; the empty sum, 0, needs no price.
"""

from __future__ import annotations

from decimal import Decimal

from di1.modules.pnl.domain.trade import PnLTrade
from di1.modules.pnl.domain.trades_pnl import calculate_trades_pnl

D = Decimal


def trades(*legs: tuple[int, str]) -> list[PnLTrade]:
    return [PnLTrade(signed_quantity=q, execution_pu=D(pu)) for q, pu in legs]


def test_each_trade_is_marked_against_the_day_reference() -> None:
    # 5 × (90100 − 90050) + (−3) × (90100 − 90150) = 250 + 150 = 400.
    assert calculate_trades_pnl(trades((5, "90050"), (-3, "90150")), D("90100")) == D("400")


def test_same_day_round_trip() -> None:
    # 10 × (90100 − 90000) + (−10) × (90100 − 90200) = 2000.
    assert calculate_trades_pnl(trades((10, "90000"), (-10, "90200")), D("90100")) == D("2000")


def test_no_trades_is_zero_without_a_price() -> None:
    result = calculate_trades_pnl([], None)
    assert result == D("0")
    assert result is not None and not result.is_signed()


def test_trades_without_the_day_reference_are_none() -> None:
    assert calculate_trades_pnl(trades((10, "90000")), None) is None


def test_trade_at_the_reference_is_unsigned_zero() -> None:
    result = calculate_trades_pnl(trades((-1, "90000")), D("90000"))
    assert result is not None and result == 0 and not result.is_signed()
