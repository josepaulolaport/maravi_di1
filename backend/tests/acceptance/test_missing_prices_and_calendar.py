"""Spec §13 cases 7, 8 and 15, and the cumulative chain (spec §7.1, §8.1, §8.3; OQ-4, OQ-10,
OQ-22): every calendar day, weekends included; a missing exact-date price is null, never zero
and never carried forward; partial P&L never looks complete; a day with no expected asset.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from di1.modules.pnl.public import CalculationCompleteness, MissingReferencePrice
from di1.modules.portfolio.public import (
    CashBalance,
    PositionState,
    ValuationStatus,
    calculate_cash_day,
    calculate_positions_day,
)
from tests.acceptance.harness import DI1F28, DI1F29, Facts, run, run_positions, trade

FRIDAY = date(2027, 1, 8)
SATURDAY = date(2027, 1, 9)
SUNDAY = date(2027, 1, 10)
MONDAY = date(2027, 1, 11)
TUESDAY = date(2027, 1, 12)
WEDNESDAY = date(2027, 1, 13)

# Friday buy 2 @ 90000; reference 90100 Friday, none Saturday, 90300 Sunday, 90400 Monday.
WEEKEND = Facts(
    trades=[trade(DI1F28, FRIDAY, 2, "90000")],
    prices={
        (DI1F28, FRIDAY): Decimal("90100"),
        (DI1F28, SUNDAY): Decimal("90300"),
        (DI1F28, MONDAY): Decimal("90400"),
    },
)


def test_every_calendar_day_is_processed_weekends_included() -> None:
    days = run(WEEKEND, FRIDAY, MONDAY)

    assert list(days) == [FRIDAY, SATURDAY, SUNDAY, MONDAY]
    assert all(d.position(DI1F28).quantity == 2 for d in days.values())


def test_a_day_cannot_be_skipped() -> None:
    # Each chain starts D from the close of D−1: neither accepts Friday's close for Sunday.
    thursday = date(2027, 1, 7)
    positions = calculate_positions_day(PositionState.zero(thursday), [], FRIDAY)
    cash = calculate_cash_day(CashBalance.zero(thursday), [], Decimal(0), Decimal(0), FRIDAY)

    with pytest.raises(ValueError, match="the previous state must be of 2027-01-09"):
        calculate_positions_day(positions.closing_state(), [], SUNDAY)
    with pytest.raises(ValueError, match="the previous state must be of 2027-01-09"):
        calculate_cash_day(cash.closing_balance(), [], Decimal(0), Decimal(0), SUNDAY)


def test_no_price_on_saturday_leaves_dependent_figures_null() -> None:
    saturday = run(WEEKEND, FRIDAY, SATURDAY)[SATURDAY]

    # Quantity, average cost and cash are still computed (§8.3).
    assert saturday.position(DI1F28).quantity == 2
    assert saturday.position(DI1F28).average_entry_pu == Decimal("90000")
    assert saturday.cash.cash_balance == Decimal("-180000")
    # No carry-forward of Friday's 90100: the figures are null, never zero (§5, §8.3).
    assert saturday.valued(DI1F28).reference_pu is None
    assert saturday.valued(DI1F28).financial_total is None
    assert saturday.valued(DI1F28).status is ValuationStatus.MISSING
    assert saturday.valuation.positions_market_value is None
    assert saturday.aum is None
    assert saturday.asset_pnl[DI1F28].position_pnl is None
    assert saturday.asset_pnl[DI1F28].missing_prices == {MissingReferencePrice.CURRENT}
    assert saturday.pnl.daily_pnl is None
    assert saturday.pnl.cumulative_pnl is None
    assert saturday.pnl.status is CalculationCompleteness.MISSING


def test_missing_previous_price_blocks_position_pnl_but_not_market_value() -> None:
    sunday = run(WEEKEND, FRIDAY, SUNDAY)[SUNDAY]

    # Q[D−1] = 2 needs the D−1 (Saturday) price, which does not exist.
    assert sunday.asset_pnl[DI1F28].position_pnl is None
    assert sunday.asset_pnl[DI1F28].missing_prices == {MissingReferencePrice.PREVIOUS}
    # Sunday's own price values the position: 2 × 90300 = 180600; AUM = −180000 + 180600.
    assert sunday.valued(DI1F28).financial_total == Decimal("180600")
    assert sunday.aum == Decimal("600")
    assert sunday.pnl.daily_pnl is None


def test_both_prices_missing() -> None:
    # Only Friday's price: on Sunday both D (Sunday) and D−1 (Saturday) are missing.
    facts = Facts(trades=WEEKEND.trades, prices={(DI1F28, FRIDAY): Decimal("90100")})

    sunday = run(facts, FRIDAY, SUNDAY)[SUNDAY]

    assert sunday.asset_pnl[DI1F28].missing_prices == {
        MissingReferencePrice.PREVIOUS,
        MissingReferencePrice.CURRENT,
    }
    assert sunday.asset_pnl[DI1F28].position_pnl is None
    assert sunday.valued(DI1F28).financial_total is None
    assert sunday.aum is None
    assert sunday.pnl.daily_pnl is None
    assert sunday.position(DI1F28).quantity == 2
    assert sunday.cash.cash_balance == Decimal("-180000")


def test_cumulative_pnl_stays_unavailable_from_the_first_gap() -> None:
    days = run(WEEKEND, FRIDAY, MONDAY)

    assert days[FRIDAY].pnl.cumulative_pnl == Decimal("200")  # 2 × (90100 − 90000)
    # Monday is complete on its own: 2 × (90400 − 90300) = 200 ...
    monday = days[MONDAY].pnl
    assert monday.daily_pnl == Decimal("200")
    assert monday.status is CalculationCompleteness.COMPLETE
    # ... but the cumulative chain broke on Saturday and stays null (§8.3).
    assert monday.cumulative_pnl is None


def test_partial_pnl_never_looks_like_a_complete_portfolio_total() -> None:
    # Two expected assets; only DI1F28 has a price on the day (case 8).
    facts = Facts(
        trades=[
            trade(DI1F28, FRIDAY, 1, "90000", seq=1),
            trade(DI1F29, FRIDAY, 1, "82000", seq=2),
        ],
        prices={(DI1F28, FRIDAY): Decimal("90100")},
    )

    friday = run(facts, FRIDAY, FRIDAY)[FRIDAY]

    assert friday.asset_pnl[DI1F28].daily_pnl == Decimal("100")
    assert friday.asset_pnl[DI1F28].status is CalculationCompleteness.COMPLETE
    assert friday.asset_pnl[DI1F29].trades_pnl is None
    assert friday.pnl.trades_pnl is None  # not 100
    assert friday.pnl.daily_pnl is None
    assert friday.pnl.status is CalculationCompleteness.MISSING
    incomplete = {
        a for a, r in friday.asset_pnl.items() if r.status is not CalculationCompleteness.COMPLETE
    }
    assert incomplete == {DI1F29}
    assert friday.valuation.positions_market_value is None  # not 90100
    assert friday.valuation.status is ValuationStatus.MISSING


def test_same_day_round_trip_needs_the_day_price() -> None:
    round_trip = [
        trade(DI1F28, FRIDAY, 1, "90000", at="10:00", seq=1),
        trade(DI1F28, FRIDAY, -1, "90300", at="11:00", seq=2),
    ]

    without_price = run(Facts(trades=round_trip), FRIDAY, FRIDAY)[FRIDAY]
    with_price = run(
        Facts(trades=round_trip, prices={(DI1F28, FRIDAY): Decimal("90200")}), FRIDAY, FRIDAY
    )[FRIDAY]

    # Flat at the close: the asset is still expected and worth 0 without a price ...
    assert without_price.expected_assets == {DI1F28}
    assert without_price.position(DI1F28).quantity == 0
    assert without_price.valued(DI1F28).financial_total == 0
    assert without_price.valued(DI1F28).status is ValuationStatus.NOT_REQUIRED
    assert without_price.aum == Decimal("300")  # cash 90300 − 90000
    # ... but its trades P&L is not computable without the day's price (§8.3).
    assert without_price.pnl.trades_pnl is None
    assert without_price.pnl.status is CalculationCompleteness.MISSING
    # With it: (90200 − 90000) − (90200 − 90300) = 300.
    assert with_price.pnl.trades_pnl == Decimal("300")
    assert with_price.pnl.daily_pnl == Decimal("300")


def test_day_without_expected_asset() -> None:
    # Monday buy 1 @ 90000 (ref 90100); Tuesday sell 1 @ 90250 (ref 90200); Wednesday nothing.
    facts = Facts(
        trades=[
            trade(DI1F28, MONDAY, 1, "90000"),
            trade(DI1F28, TUESDAY, -1, "90250"),
        ],
        prices={(DI1F28, MONDAY): Decimal("90100"), (DI1F28, TUESDAY): Decimal("90200")},
    )

    days = run(facts, MONDAY, WEDNESDAY)

    # Tuesday: position 1 × 100 + trades −1 × (90200 − 90250) = 150; cumulative 100 + 150.
    assert days[TUESDAY].pnl.daily_pnl == Decimal("150")
    assert days[TUESDAY].pnl.cumulative_pnl == Decimal("250")
    wednesday = days[WEDNESDAY]
    assert wednesday.expected_assets == set()
    assert wednesday.pnl.position_pnl == 0
    assert wednesday.pnl.trades_pnl == 0
    assert wednesday.pnl.daily_pnl == 0
    assert wednesday.pnl.status is CalculationCompleteness.COMPLETE
    assert wednesday.pnl.cumulative_pnl == Decimal("250")  # carried forward (OQ-22)
    assert wednesday.valuation.positions_market_value == 0
    assert wednesday.aum == wednesday.cash.cash_balance == Decimal("250")


def test_aum_is_null_without_a_cash_balance() -> None:
    # The positions chain alone, with the cash chain not processed on the date (OQ-21, OQ-38):
    # the market value is published and AUM is null.
    facts = Facts(
        trades=[trade(DI1F28, FRIDAY, 1, "90000")], prices={(DI1F28, FRIDAY): Decimal("90100")}
    )

    friday = run_positions(facts, FRIDAY, FRIDAY)[FRIDAY]

    assert friday.valuation.positions_market_value == Decimal("90100")
    assert friday.aum is None
