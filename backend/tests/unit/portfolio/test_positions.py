"""The positions chain: signed quantities, intraday order, expected assets (spec §7.2, §8.3).

Spec §13 items 2 and 7; OQ-10 (expected assets), OQ-13 (order). This chain computes no cash.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from di1.modules.portfolio.domain.errors import PortfolioError
from di1.modules.portfolio.domain.positions import (
    OpenPosition,
    PositionDay,
    PositionState,
    calculate_positions_day,
)
from di1.modules.portfolio.domain.trade import Trade
from tests.unit.portfolio.factories import DAY, DI1F27, DI1F28, DI1F29, position, trade

YESTERDAY = DAY - timedelta(days=1)


def _state(*positions: OpenPosition) -> PositionState:
    return PositionState(as_of=YESTERDAY, positions=positions)


def _only_position(state: PositionState, *trades: Trade) -> PositionDay:
    day = calculate_positions_day(state, trades, DAY)
    assert len(day.positions) == 1
    return day.positions[0]


def test_a_buy_from_flat_opens_a_long_at_the_trade_pu_and_rate() -> None:
    result = _only_position(PositionState.zero(YESTERDAY), trade(10, "95000", "0.105"))

    assert result.asset_id == DI1F27
    assert result.previous_quantity == 0
    assert result.quantity == 10
    assert result.average_entry_pu == Decimal("95000")
    assert result.average_entry_rate == Decimal("0.105")


def test_an_untraded_position_is_carried_unchanged() -> None:
    result = _only_position(_state(position(-20, "95500", "0.1")))

    assert result.previous_quantity == -20
    assert result.quantity == -20
    assert result.average_entry_pu == Decimal("95500")
    assert result.average_entry_rate == Decimal("0.1")
    assert result.trades == ()


def test_same_day_trades_apply_in_time_then_seq_order_never_netted() -> None:
    # Order (trade_time, seq): buy 10 @ 95000, sell 10 @ 96000 (flat), buy 4 @ 97000 → 4 @ 97000.
    # By seq alone it would be 4 @ 95571.43; netted first, +4 at a blended price. Both are wrong.
    late_buy = trade(4, "97000", "0.08", at="11:00", seq=1)
    first_buy = trade(10, "95000", "0.105", at="09:00", seq=3)
    sell = trade(-10, "96000", "0.095", at="09:00", seq=4)

    result = _only_position(PositionState.zero(YESTERDAY), late_buy, sell, first_buy)

    assert result.quantity == 4
    assert result.average_entry_pu == Decimal("97000")
    assert result.average_entry_rate == Decimal("0.08")
    assert result.trades == (first_buy, sell, late_buy)


def test_a_same_day_round_trip_leaves_a_zero_quantity_row() -> None:
    result = _only_position(
        PositionState.zero(YESTERDAY),
        trade(10, "95000", at="09:00", seq=1),
        trade(-10, "95100", at="15:00", seq=2),
    )

    assert result.previous_quantity == 0
    assert result.quantity == 0
    assert result.average_entry_pu is None
    assert result.average_entry_rate is None


def test_expected_assets_are_those_held_yesterday_or_traded_today() -> None:
    # DI1F27 held, not traded; DI1F28 opened today; DI1F29 closed before yesterday (absent).
    state = _state(position(3, "95000", "0.1"))

    day = calculate_positions_day(state, [trade(1, "91000", asset_id=DI1F28)], DAY)

    assert [p.asset_id for p in day.positions] == [DI1F27, DI1F28]
    assert DI1F29 not in {p.asset_id for p in day.positions}


def test_a_position_closed_today_keeps_its_row_today_and_leaves_tomorrow() -> None:
    state = _state(position(3, "95000", "0.1"))

    today = calculate_positions_day(state, [trade(-3, "96000")], DAY)
    tomorrow = calculate_positions_day(today.closing_state(), [], DAY + timedelta(days=1))

    assert [(p.asset_id, p.quantity) for p in today.positions] == [(DI1F27, 0)]
    assert today.closing_state().positions == ()
    assert tomorrow.positions == ()


def test_positions_are_listed_in_asset_id_order() -> None:
    day = calculate_positions_day(
        PositionState.zero(YESTERDAY),
        [
            trade(1, "90000", asset_id=DI1F29, seq=1),
            trade(1, "91000", asset_id=DI1F27, seq=2),
            trade(1, "92000", asset_id=DI1F28, seq=3),
        ],
        DAY,
    )

    assert [p.asset_id for p in day.positions] == [DI1F27, DI1F28, DI1F29]


def test_trades_of_different_assets_do_not_mix_averages() -> None:
    day = calculate_positions_day(
        PositionState.zero(YESTERDAY),
        [trade(1, "90000", asset_id=DI1F28, seq=1), trade(1, "95000", asset_id=DI1F27, seq=2)],
        DAY,
    )

    assert [p.average_entry_pu for p in day.positions] == [Decimal("95000"), Decimal("90000")]


def test_a_flat_position_is_never_carried() -> None:
    # The next day's state holds open positions only; flat assets are not expected (OQ-10).
    with pytest.raises(PortfolioError):
        position(0, "95000", "0.1")


def test_a_state_holding_the_same_asset_twice_is_rejected() -> None:
    with pytest.raises(PortfolioError):
        _state(position(1, "95000", "0.1"), position(2, "95000", "0.1"))


@pytest.mark.parametrize("gap", [2, 0])
def test_a_day_cannot_be_skipped_or_repeated(gap: int) -> None:
    # Every calendar day is processed (spec §7.1): a day starts from the day before.
    with pytest.raises(PortfolioError, match="previous state must be"):
        calculate_positions_day(PositionState.zero(DAY - timedelta(days=gap)), [], DAY)
