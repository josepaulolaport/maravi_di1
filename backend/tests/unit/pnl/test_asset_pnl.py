"""Per-asset daily P&L attribution (spec §8.1, §8.3, §13 items 5 and 7; OQ-1, OQ-2, OQ-4).

position_pnl = Q[D-1] × (PU_D − PU_{D-1})
trades_pnl   = Σ q_i × (PU_D − PU_exec_i)
daily_pnl    = position_pnl + trades_pnl

Expected values are worked by hand from those formulas; the multiplier is not applied (OQ-2).
"""

from __future__ import annotations

from decimal import Decimal

from di1.modules.pnl.domain.asset_pnl import AssetPnLCalculator
from di1.modules.pnl.domain.results import (
    AssetPnLResult,
    CalculationCompleteness,
    MissingReferencePrice,
)
from di1.modules.pnl.domain.trade import PnLTrade

D = Decimal


def calculate(
    previous_quantity: str,
    trades: list[tuple[str, str]],
    previous_reference_pu: str | None,
    current_reference_pu: str | None,
) -> AssetPnLResult:
    return AssetPnLCalculator().calculate(
        previous_position=int(previous_quantity),
        day_trades=[PnLTrade(signed_quantity=int(q), execution_pu=D(pu)) for q, pu in trades],
        previous_reference_pu=None if previous_reference_pu is None else D(previous_reference_pu),
        current_reference_pu=None if current_reference_pu is None else D(current_reference_pu),
    )


def assert_complete(result: AssetPnLResult, position: str, trades: str, daily: str) -> None:
    assert result.status is CalculationCompleteness.COMPLETE
    assert result.missing_prices == frozenset()
    assert (result.position_pnl, result.trades_pnl, result.daily_pnl) == (
        D(position),
        D(trades),
        D(daily),
    )


# --- complete days -----------------------------------------------------------------------------


def test_long_position_held_gains_when_pu_rises() -> None:
    # 10 × (90100 − 90000) = 1000; no trades.
    result = calculate("10", [], "90000", "90100")
    assert_complete(result, position="1000", trades="0", daily="1000")


def test_short_position_held_loses_when_pu_rises() -> None:
    # −5 × (90100 − 90000) = −500.
    result = calculate("-5", [], "90000", "90100")
    assert_complete(result, position="-500", trades="0", daily="-500")


def test_first_day_buy_needs_no_previous_price_and_position_pnl_is_exactly_zero() -> None:
    # OQ-4: Q[D-1] = 0 → position_pnl = 0 (not null), no D-1 price.
    # trades: 10 × (90050 − 90000) = 500.
    result = calculate("0", [("10", "90000")], None, "90050")
    assert_complete(result, position="0", trades="500", daily="500")
    assert result.position_pnl is not None


def test_challenge_example_bought_at_the_reference_pu_has_zero_pnl() -> None:
    # Challenge §5 with D2: 1 DI1F28 at 10% (PU 90909.0909090909), reference at the same 10%.
    result = calculate("0", [("1", "90909.0909090909")], None, "90909.0909090909")
    assert_complete(result, position="0", trades="0", daily="0")


def test_same_day_round_trip_attributes_both_legs_against_the_reference() -> None:
    # Buy 10 @ 90000, sell 10 @ 90200, PU_D 90100:
    # 10 × (90100 − 90000) + (−10) × (90100 − 90200) = 1000 + 1000 = 2000 (= 10 × 200 realised).
    result = calculate("0", [("10", "90000"), ("-10", "90200")], None, "90100")
    assert_complete(result, position="0", trades="2000", daily="2000")


def test_increase_and_partial_reduction_on_the_same_day() -> None:
    # Held 10, PU 90000 → 90100: position 1000.
    # Buy 5 @ 90050: 5 × 50 = 250. Sell 3 @ 90150: −3 × (−50) = 150. trades 400.
    result = calculate("10", [("5", "90050"), ("-3", "90150")], "90000", "90100")
    assert_complete(result, position="1000", trades="400", daily="1400")


def test_reversal_is_one_trade_attributed_once() -> None:
    # Held 10, PU 90000 → 89900: position −1000. Sell 15 @ 89950 (crosses zero, not split):
    # −15 × (89900 − 89950) = 750. daily −250.
    result = calculate("10", [("-15", "89950")], "90000", "89900")
    assert_complete(result, position="-1000", trades="750", daily="-250")


def test_short_reversed_into_a_long_when_pu_falls() -> None:
    # Held −10, PU 90000 → 89900: −10 × (−100) = 1000. Buy 15 @ 89950 (crosses zero, not split):
    # 15 × (89900 − 89950) = −750. daily 250.
    result = calculate("-10", [("15", "89950")], "90000", "89900")
    assert_complete(result, position="1000", trades="-750", daily="250")


def test_short_partially_bought_back() -> None:
    # Held −10, PU 90000 → 90100: −1000. Buy 4 @ 90050: 4 × 50 = 200. daily −800.
    result = calculate("-10", [("4", "90050")], "90000", "90100")
    assert_complete(result, position="-1000", trades="200", daily="-800")


def test_short_with_unchanged_pu_has_no_negative_zero() -> None:
    # −5 × (90000 − 90000) is −0 in Decimal; stored and serialised values never carry the sign.
    result = calculate("-5", [("-1", "90000")], "90000", "90000")
    assert_complete(result, position="0", trades="0", daily="0")
    for value in (result.position_pnl, result.trades_pnl, result.daily_pnl):
        assert value is not None and not value.is_signed()


def test_arithmetic_is_exact_at_stored_pu_precision() -> None:
    # 3 × (90909.1000000001 − 90909.0909090909) = 3 × 0.0090909092 = 0.0272727276; never rounded.
    result = calculate("3", [], "90909.0909090909", "90909.1000000001")
    assert_complete(result, position="0.0272727276", trades="0", daily="0.0272727276")


def test_no_position_and_no_trades_needs_no_price() -> None:
    result = calculate("0", [], None, None)
    assert_complete(result, position="0", trades="0", daily="0")


# --- missing prices: null, never zero (§8.3) -------------------------------------------------


def test_missing_current_pu_with_open_position_nulls_every_figure() -> None:
    result = calculate("10", [("2", "90000")], "90000", None)
    assert result.status is CalculationCompleteness.MISSING
    assert result.missing_prices == frozenset({MissingReferencePrice.CURRENT})
    assert (result.position_pnl, result.trades_pnl, result.daily_pnl) == (None, None, None)


def test_missing_previous_pu_with_open_position_nulls_position_and_daily_only() -> None:
    # trades_pnl depends only on PU_D: 2 × (90100 − 90000) = 200.
    result = calculate("10", [("2", "90000")], None, "90100")
    assert result.status is CalculationCompleteness.MISSING
    assert result.missing_prices == frozenset({MissingReferencePrice.PREVIOUS})
    assert result.position_pnl is None
    assert result.trades_pnl == D("200")
    assert result.daily_pnl is None


def test_missing_both_prices_reports_both() -> None:
    # No trades: trades_pnl is the empty sum, 0, and depends on no price.
    result = calculate("-4", [], None, None)
    assert result.status is CalculationCompleteness.MISSING
    assert result.missing_prices == frozenset(
        {MissingReferencePrice.PREVIOUS, MissingReferencePrice.CURRENT}
    )
    assert (result.position_pnl, result.trades_pnl, result.daily_pnl) == (None, D("0"), None)


def test_same_day_round_trip_without_current_pu_is_missing_even_though_flat() -> None:
    # §8.3: flat market value is 0, but the day's trades still need PU_D.
    result = calculate("0", [("10", "90000"), ("-10", "90200")], None, None)
    assert result.status is CalculationCompleteness.MISSING
    assert result.missing_prices == frozenset({MissingReferencePrice.CURRENT})
    assert result.position_pnl == D("0")
    assert result.trades_pnl is None
    assert result.daily_pnl is None


def test_first_day_without_current_pu_keeps_position_pnl_zero() -> None:
    result = calculate("0", [("10", "90000")], None, None)
    assert result.status is CalculationCompleteness.MISSING
    assert result.missing_prices == frozenset({MissingReferencePrice.CURRENT})
    assert result.position_pnl == D("0")
    assert (result.trades_pnl, result.daily_pnl) == (None, None)


# --- maturity (OQ-1) ---------------------------------------------------------------------------


def test_position_open_after_maturity_is_valued_at_zero() -> None:
    # Day after maturity: reference PU = 0 by definition. 10 × (0 − 99990) = −999900.
    result = calculate("10", [], "99990", "0")
    assert_complete(result, position="-999900", trades="0", daily="-999900")


def test_position_still_open_two_days_after_maturity_has_no_further_pnl() -> None:
    result = calculate("10", [], "0", "0")
    assert_complete(result, position="0", trades="0", daily="0")
