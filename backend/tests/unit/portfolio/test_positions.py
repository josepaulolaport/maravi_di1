"""The positions chain: signed quantities, average entry PU and rate, intraday order, expected
assets (spec §7.2, §8.3; §13 items 2, 3 and 7; OQ-3, OQ-10, OQ-13). This chain computes no cash.

Expected averages are worked by hand from the §7.2 rules: each average is weighted by absolute
quantity, and the average rate is weighted on its own.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal

import pytest

from di1.modules.portfolio.domain.average_cost import next_average
from di1.modules.portfolio.domain.errors import PortfolioError
from di1.modules.portfolio.domain.positions import (
    OpenPosition,
    PositionState,
    calculate_positions_day,
)
from di1.modules.portfolio.domain.trade import Trade
from tests.support.builders import DAY, DI1F27, DI1F28, DI1F29, open_position, portfolio_trade

YESTERDAY = DAY - timedelta(days=1)


def _state(*positions: OpenPosition) -> PositionState:
    return PositionState(as_of=YESTERDAY, positions=positions)


@pytest.mark.parametrize(
    ("held", "trades", "previous_quantity", "quantity", "average_pu", "average_rate"),
    [
        pytest.param(
            (),
            (portfolio_trade(10, "95000", "0.105"),),
            0,
            10,
            "95000",
            "0.105",
            id="buy-from-flat",
        ),
        pytest.param(
            (open_position(-20, "95500", "0.1"),),
            (),
            -20,
            -20,
            "95500",
            "0.1",
            id="untraded-carried",
        ),
        # PU: (10 × 95000 + 30 × 96000) / 40 = 95750; rate: (10 × 0.105 + 30 × 0.095) / 40 = 0.0975.
        # 0.0975 is not the rate implied by PU 95750: the average rate is not derived from the PU.
        pytest.param(
            (open_position(10, "95000", "0.105"),),
            (portfolio_trade(30, "96000", "0.095"),),
            10,
            40,
            "95750",
            "0.0975",
            id="increase-weights-pu-and-rate-separately",
        ),
        # (1 × 90909.0909090909 + 2 × 91000) / 3 = 90969.69696969696666…, stored at 10 places.
        pytest.param(
            (),
            (
                portfolio_trade(1, "90909.0909090909", "0.1", at="09:00", seq=1),
                portfolio_trade(2, "91000", "0.1", at="09:30", seq=2),
            ),
            0,
            3,
            "90969.6969696970",
            "0.1",
            id="non-terminating-average-rounded-half-up-at-close",
        ),
        # PU: (10 × 96000 + 10 × 95000) / 20 = 95500; rate: (10 × 0.095 + 10 × 0.105) / 20 = 0.1.
        pytest.param(
            (),
            (
                portfolio_trade(-10, "96000", "0.095", at="09:00", seq=1),
                portfolio_trade(-10, "95000", "0.105", at="11:00", seq=2),
            ),
            0,
            -20,
            "95500",
            "0.1",
            id="short-opened-and-increased",
        ),
        pytest.param(
            (open_position(40, "95750", "0.0975"),),
            (portfolio_trade(-15, "97000", "0.08"),),
            40,
            25,
            "95750",
            "0.0975",
            id="partial-close-keeps-the-average",
        ),
        pytest.param(
            (open_position(-20, "95500", "0.1"),),
            (portfolio_trade(5, "94000", "0.12"),),
            -20,
            -15,
            "95500",
            "0.1",
            id="partial-cover-keeps-the-average",
        ),
        # A flat position has no entry price; position_metrics stores NULL.
        pytest.param(
            (open_position(25, "95750", "0.0975"),),
            (portfolio_trade(-25, "97000", "0.08"),),
            25,
            0,
            None,
            None,
            id="full-close-leaves-no-average",
        ),
        pytest.param(
            (),
            (
                portfolio_trade(10, "95000", at="09:00", seq=1),
                portfolio_trade(-10, "95100", at="15:00", seq=2),
            ),
            0,
            0,
            None,
            None,
            id="same-day-round-trip-leaves-a-zero-row",
        ),
        # Crossing zero opens the remainder at the trade's PU and rate; the row is never split.
        pytest.param(
            (open_position(10, "95000", "0.105"),),
            (portfolio_trade(-25, "96000", "0.095"),),
            10,
            -15,
            "96000",
            "0.095",
            id="sell-crossing-zero",
        ),
        pytest.param(
            (open_position(-10, "96000", "0.095"),),
            (portfolio_trade(25, "95500", "0.1"),),
            -10,
            15,
            "95500",
            "0.1",
            id="buy-crossing-zero",
        ),
    ],
)
def test_the_closing_quantity_and_averages_follow_the_day_trades(
    held: tuple[OpenPosition, ...],
    trades: tuple[Trade, ...],
    previous_quantity: int,
    quantity: int,
    average_pu: str | None,
    average_rate: str | None,
) -> None:
    day = calculate_positions_day(_state(*held), trades, DAY)

    (result,) = day.positions
    assert result.asset_id == DI1F27.id
    assert (result.previous_quantity, result.quantity) == (previous_quantity, quantity)
    assert result.average_entry_pu == (None if average_pu is None else Decimal(average_pu))
    assert result.average_entry_rate == (None if average_rate is None else Decimal(average_rate))
    assert result.trades == trades  # applied whole, in order


def test_same_day_trades_apply_in_time_then_seq_order_never_netted() -> None:
    # Order (trade_time, seq): buy 10 @ 95000, sell 10 @ 96000 (flat), buy 4 @ 97000 → 4 @ 97000.
    # By seq alone it would be 4 @ 95571.43; netted first, +4 at a blended price. Both are wrong.
    late_buy = portfolio_trade(4, "97000", "0.08", at="11:00", seq=1)
    first_buy = portfolio_trade(10, "95000", "0.105", at="09:00", seq=3)
    sell = portfolio_trade(-10, "96000", "0.095", at="09:00", seq=4)

    (result,) = calculate_positions_day(
        PositionState.zero(YESTERDAY), [late_buy, sell, first_buy], DAY
    ).positions

    assert result.quantity == 4
    assert result.average_entry_pu == Decimal("97000")
    assert result.average_entry_rate == Decimal("0.08")
    assert result.trades == (first_buy, sell, late_buy)


def test_expected_assets_are_those_held_yesterday_or_traded_today() -> None:
    # DI1F27 held, not traded; DI1F28 opened today; DI1F29 closed before yesterday (absent).
    state = _state(open_position(3, "95000", "0.1"))

    day = calculate_positions_day(state, [portfolio_trade(1, "91000", asset_id=DI1F28.id)], DAY)

    assert [p.asset_id for p in day.positions] == [DI1F27.id, DI1F28.id]
    assert DI1F29.id not in {p.asset_id for p in day.positions}


def test_a_position_closed_today_keeps_its_row_today_and_leaves_tomorrow() -> None:
    state = _state(open_position(3, "95000", "0.1"))

    today = calculate_positions_day(state, [portfolio_trade(-3, "96000")], DAY)
    tomorrow = calculate_positions_day(today.closing_state(), [], DAY + timedelta(days=1))

    assert [(p.asset_id, p.quantity) for p in today.positions] == [(DI1F27.id, 0)]
    assert today.closing_state().positions == ()
    assert tomorrow.positions == ()


def test_two_sells_that_reach_zero_close_the_position_without_an_average() -> None:
    # Spec §7.2: a partial reduction keeps the average; the trade that reaches 0 closes it.
    day = calculate_positions_day(
        _state(open_position(4, "90000", "0.11")),
        [
            portfolio_trade(-1, "90500", "0.10", at="10:00", seq=2),
            portfolio_trade(-3, "90600", "0.10", at="15:00", seq=3),
        ],
        DAY,
    )

    closed = day.positions[0]
    assert (closed.previous_quantity, closed.quantity) == (4, 0)
    assert (closed.average_entry_pu, closed.average_entry_rate) == (None, None)
    assert len(closed.trades) == 2


def test_assets_are_listed_in_id_order_and_never_mix_averages() -> None:
    day = calculate_positions_day(
        PositionState.zero(YESTERDAY),
        [
            portfolio_trade(1, "90000", asset_id=DI1F29.id, seq=1),
            portfolio_trade(1, "95000", asset_id=DI1F27.id, seq=2),
            portfolio_trade(1, "92000", asset_id=DI1F28.id, seq=3),
        ],
        DAY,
    )

    assert [(p.asset_id, p.average_entry_pu) for p in day.positions] == [
        (DI1F27.id, Decimal("95000")),
        (DI1F28.id, Decimal("92000")),
        (DI1F29.id, Decimal("90000")),
    ]


def _flat_carried() -> object:
    # The next day's state holds open positions only; flat assets are not expected (OQ-10).
    return open_position(0, "95000", "0.1")


def _same_asset_twice() -> object:
    return _state(open_position(1, "95000", "0.1"), open_position(2, "95000", "0.1"))


def _held_without_average() -> object:
    # A held position always carries an average; a missing one is a broken state, not an opening.
    return next_average(5, None, 1, Decimal("95000"))


def _zero_quantity_trade() -> object:
    # Schema CHECK trades_qty_nonzero (OQ-14).
    return portfolio_trade(0, "95000")


def _misdated_trade() -> object:
    # A chain day reads only its own date's trades (spec §7.2).
    return calculate_positions_day(
        PositionState.zero(YESTERDAY), [portfolio_trade(1, "95000", on=YESTERDAY)], DAY
    )


@pytest.mark.parametrize(
    "build",
    [
        pytest.param(_flat_carried, id="flat-position-carried"),
        pytest.param(_same_asset_twice, id="same-asset-twice-in-a-state"),
        pytest.param(_held_without_average, id="held-quantity-without-an-average"),
        pytest.param(_zero_quantity_trade, id="zero-quantity-trade"),
        pytest.param(_misdated_trade, id="trade-of-another-date"),
    ],
)
def test_an_impossible_input_is_rejected(build: Callable[[], object]) -> None:
    with pytest.raises(PortfolioError):
        build()


@pytest.mark.parametrize("gap", [2, 0])
def test_a_day_cannot_be_skipped_or_repeated(gap: int) -> None:
    # Every calendar day is processed (spec §7.1): a day starts from the day before.
    # The full message names both dates, so a wrong day in it fails the test too.
    expected = f"the previous state must be of {YESTERDAY}, not {DAY - timedelta(days=gap)}"
    with pytest.raises(PortfolioError, match=re.escape(expected)):
        calculate_positions_day(PositionState.zero(DAY - timedelta(days=gap)), [], DAY)
