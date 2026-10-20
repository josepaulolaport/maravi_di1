"""Average entry PU and average entry rate (spec §7.2 and §13 item 3; OQ-3).

Expected values are worked by hand from the §7.2 rules: each average is weighted by absolute
quantity, and the average rate is weighted on its own.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from di1.modules.portfolio.domain.average_cost import next_average
from di1.modules.portfolio.domain.errors import PortfolioError
from di1.modules.portfolio.domain.positions import (
    OpenPosition,
    PositionDay,
    PositionState,
    calculate_positions_day,
)
from di1.modules.portfolio.domain.trade import Trade
from tests.unit.portfolio.factories import DAY, position, trade

YESTERDAY = DAY - timedelta(days=1)


def _state(*positions: OpenPosition) -> PositionState:
    return PositionState(as_of=YESTERDAY, positions=positions)


def _only_position(state: PositionState, *trades: Trade) -> PositionDay:
    day = calculate_positions_day(state, trades, DAY)
    assert len(day.positions) == 1
    return day.positions[0]


def test_an_increase_weights_pu_and_rate_separately_by_quantity() -> None:
    # PU: (10 × 95000 + 30 × 96000) / 40 = 95750; rate: (10 × 0.105 + 30 × 0.095) / 40 = 0.0975.
    # 0.0975 is not the rate implied by PU 95750: the average rate is not derived from the PU.
    result = _only_position(_state(position(10, "95000", "0.105")), trade(30, "96000", "0.095"))

    assert result.previous_quantity == 10
    assert result.quantity == 40
    assert result.average_entry_pu == Decimal("95750")
    assert result.average_entry_rate == Decimal("0.0975")


def test_a_non_terminating_average_is_rounded_half_up_at_the_day_close() -> None:
    # (1 × 90909.0909090909 + 2 × 91000) / 3 = 90969.69696969696666…, stored with 10 places (OQ-3).
    result = _only_position(
        PositionState.zero(YESTERDAY),
        trade(1, "90909.0909090909", "0.1", at="09:00", seq=1),
        trade(2, "91000", "0.1", at="09:30", seq=2),
    )

    assert result.quantity == 3
    assert result.average_entry_pu == Decimal("90969.6969696970")
    assert result.average_entry_rate == Decimal("0.1")


def test_a_partial_close_keeps_the_average_pu_and_rate() -> None:
    result = _only_position(_state(position(40, "95750", "0.0975")), trade(-15, "97000", "0.08"))

    assert result.quantity == 25
    assert result.average_entry_pu == Decimal("95750")
    assert result.average_entry_rate == Decimal("0.0975")


def test_a_full_close_leaves_quantity_zero_and_no_average() -> None:
    # A flat position has no entry price; position_metrics stores NULL (average > 0 when set).
    result = _only_position(_state(position(25, "95750", "0.0975")), trade(-25, "97000", "0.08"))

    assert result.previous_quantity == 25
    assert result.quantity == 0
    assert result.average_entry_pu is None
    assert result.average_entry_rate is None


def test_a_sell_crossing_zero_opens_the_short_remainder_at_the_trade_pu() -> None:
    sell = trade(-25, "96000", "0.095")

    result = _only_position(_state(position(10, "95000", "0.105")), sell)

    assert result.quantity == -15
    assert result.average_entry_pu == Decimal("96000")
    assert result.average_entry_rate == Decimal("0.095")
    assert result.trades == (sell,)  # the ledger row is never split


def test_a_buy_crossing_zero_opens_the_long_remainder_at_the_trade_pu() -> None:
    buy = trade(25, "95500", "0.1")

    result = _only_position(_state(position(-10, "96000", "0.095")), buy)

    assert result.quantity == 15
    assert result.average_entry_pu == Decimal("95500")
    assert result.average_entry_rate == Decimal("0.1")
    assert result.trades == (buy,)


def test_a_short_is_opened_and_increased_with_weighted_averages() -> None:
    # PU: (10 × 96000 + 10 × 95000) / 20 = 95500; rate: (10 × 0.095 + 10 × 0.105) / 20 = 0.1.
    result = _only_position(
        PositionState.zero(YESTERDAY),
        trade(-10, "96000", "0.095", at="09:00", seq=1),
        trade(-10, "95000", "0.105", at="11:00", seq=2),
    )

    assert result.quantity == -20
    assert result.average_entry_pu == Decimal("95500")
    assert result.average_entry_rate == Decimal("0.1")


def test_a_partial_cover_of_a_short_keeps_the_average() -> None:
    result = _only_position(_state(position(-20, "95500", "0.1")), trade(5, "94000", "0.12"))

    assert result.quantity == -15
    assert result.average_entry_pu == Decimal("95500")
    assert result.average_entry_rate == Decimal("0.1")


def test_an_open_quantity_without_an_average_is_rejected() -> None:
    # A held position always carries an average; a missing one is a broken state, not an opening.
    with pytest.raises(PortfolioError):
        next_average(5, None, 1, Decimal("95000"))
