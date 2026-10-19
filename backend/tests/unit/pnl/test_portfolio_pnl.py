"""Portfolio P&L aggregation (spec §8.1, §8.3, §13 items 5 and 8; OQ-4, OQ-10).

Per asset first, then summed over **every expected asset**; a missing expected asset makes the
portfolio figure null, never a sum of the available ones. cumulative = previous + daily, and it
stays null from the first gap onward.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from uuid import UUID

import pytest

from di1.modules.pnl.domain.portfolio_pnl import PortfolioPnLCalculator
from di1.modules.pnl.domain.results import (
    AssetPnLResult,
    CalculationCompleteness,
    MissingReferencePrice,
    PortfolioPnLResult,
)

D = Decimal
ASSET_A = UUID("00000000-0000-0000-0000-00000000000a")
ASSET_B = UUID("00000000-0000-0000-0000-00000000000b")
ASSET_C = UUID("00000000-0000-0000-0000-00000000000c")


def complete(position: str, trades: str) -> AssetPnLResult:
    return AssetPnLResult(
        position_pnl=D(position),
        trades_pnl=D(trades),
        daily_pnl=D(position) + D(trades),
        status=CalculationCompleteness.COMPLETE,
        missing_prices=frozenset(),
    )


MISSING_CURRENT = AssetPnLResult(
    position_pnl=None,
    trades_pnl=None,
    daily_pnl=None,
    status=CalculationCompleteness.MISSING,
    missing_prices=frozenset({MissingReferencePrice.CURRENT}),
)


def aggregate(
    expected: set[UUID],
    results: Mapping[UUID, AssetPnLResult],
    previous_cumulative: str | None,
) -> PortfolioPnLResult:
    return PortfolioPnLCalculator().aggregate(
        expected_assets=expected,
        asset_results=results,
        previous_cumulative=None if previous_cumulative is None else D(previous_cumulative),
    )


def test_complete_assets_are_summed_per_component_and_accumulated() -> None:
    # A: 1000 + 400; B: −500 + 0. position 500, trades 400, daily 900; cumulative 100 + 900.
    result = aggregate(
        {ASSET_A, ASSET_B},
        {ASSET_A: complete("1000", "400"), ASSET_B: complete("-500", "0")},
        "100",
    )
    assert result.status is CalculationCompleteness.COMPLETE
    assert result.cumulative_status is CalculationCompleteness.COMPLETE
    assert result.incomplete_assets == frozenset()
    assert (result.position_pnl, result.trades_pnl, result.daily_pnl) == (
        D("500"),
        D("400"),
        D("900"),
    )
    assert result.cumulative_pnl == D("1000")


def test_first_day_with_no_expected_asset_starts_cumulative_at_zero() -> None:
    # OQ-4: cumulative P&L starts at 0 before the first entry.
    result = aggregate(set(), {}, "0")
    assert result.status is CalculationCompleteness.COMPLETE
    assert (result.position_pnl, result.trades_pnl, result.daily_pnl) == (D("0"), D("0"), D("0"))
    assert result.cumulative_pnl == D("0")


def test_incomplete_asset_makes_the_portfolio_total_null_not_a_partial_sum() -> None:
    result = aggregate(
        {ASSET_A, ASSET_B},
        {ASSET_A: complete("1000", "400"), ASSET_B: MISSING_CURRENT},
        "100",
    )
    assert result.status is CalculationCompleteness.MISSING
    assert result.incomplete_assets == frozenset({ASSET_B})
    assert (result.position_pnl, result.trades_pnl, result.daily_pnl) == (None, None, None)
    assert result.cumulative_pnl is None
    assert result.cumulative_status is CalculationCompleteness.MISSING


def test_expected_asset_without_a_result_is_incomplete() -> None:
    result = aggregate({ASSET_A, ASSET_C}, {ASSET_A: complete("1000", "0")}, "0")
    assert result.status is CalculationCompleteness.MISSING
    assert result.incomplete_assets == frozenset({ASSET_C})
    assert result.daily_pnl is None
    assert result.cumulative_pnl is None


def test_component_available_on_every_expected_asset_is_still_summed() -> None:
    # B misses only its D-1 price: its trades_pnl (200) is known, its position_pnl is not.
    missing_previous = AssetPnLResult(
        position_pnl=None,
        trades_pnl=D("200"),
        daily_pnl=None,
        status=CalculationCompleteness.MISSING,
        missing_prices=frozenset({MissingReferencePrice.PREVIOUS}),
    )
    result = aggregate(
        {ASSET_A, ASSET_B}, {ASSET_A: complete("1000", "400"), ASSET_B: missing_previous}, "0"
    )
    assert result.status is CalculationCompleteness.MISSING
    assert result.incomplete_assets == frozenset({ASSET_B})
    assert result.position_pnl is None
    assert result.trades_pnl == D("600")
    assert result.daily_pnl is None
    assert result.cumulative_pnl is None


def test_broken_chain_keeps_cumulative_null_even_on_a_complete_day() -> None:
    # §8.3: cumulative unavailable from the first gap onward; the day's own P&L is still valid.
    result = aggregate({ASSET_A}, {ASSET_A: complete("1000", "0")}, None)
    assert result.status is CalculationCompleteness.COMPLETE
    assert result.daily_pnl == D("1000")
    assert result.cumulative_pnl is None
    assert result.cumulative_status is CalculationCompleteness.MISSING


def test_zero_quantity_expected_asset_is_part_of_the_total() -> None:
    # OQ-10: a same-day round trip leaves Q = 0 but the asset is expected; its 2000 counts.
    result = aggregate(
        {ASSET_A, ASSET_B},
        {ASSET_A: complete("1000", "0"), ASSET_B: complete("0", "2000")},
        "0",
    )
    assert result.status is CalculationCompleteness.COMPLETE
    assert result.daily_pnl == D("3000")
    assert result.cumulative_pnl == D("3000")


def test_post_maturity_open_position_flows_into_the_portfolio() -> None:
    # OQ-1: 10 × (0 − 99990) = −999900 on the day after maturity.
    result = aggregate({ASSET_A}, {ASSET_A: complete("-999900", "0")}, "5000")
    assert result.daily_pnl == D("-999900")
    assert result.cumulative_pnl == D("-994900")


def test_result_for_an_asset_that_is_not_expected_is_rejected() -> None:
    # OQ-10: results exist exactly for expected assets; anything else is a caller bug.
    with pytest.raises(ValueError, match="not expected"):
        aggregate({ASSET_A}, {ASSET_A: complete("0", "0"), ASSET_B: complete("1", "0")}, "0")
