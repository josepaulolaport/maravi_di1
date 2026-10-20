"""Portfolio P&L aggregation (spec §8.1, §8.3, §13 items 5 and 8; OQ-1, OQ-4, OQ-10).

Per asset first, then summed over **every expected asset**; a missing expected asset makes the
portfolio figure null, never a sum of the available ones. cumulative = previous + daily, and it
stays null from the first gap onward.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from uuid import UUID

import pytest

from di1.modules.pnl.domain.portfolio_pnl import aggregate_pnl
from di1.modules.pnl.domain.results import (
    AssetPnLResult,
    CalculationCompleteness,
    MissingReferencePrice,
)

D = Decimal
COMPLETE = CalculationCompleteness.COMPLETE
MISSING = CalculationCompleteness.MISSING
ASSET_A = UUID("00000000-0000-0000-0000-00000000000a")
ASSET_B = UUID("00000000-0000-0000-0000-00000000000b")
ASSET_C = UUID("00000000-0000-0000-0000-00000000000c")


def complete(position: str, trades: str) -> AssetPnLResult:
    return AssetPnLResult(
        position_pnl=D(position),
        trades_pnl=D(trades),
        daily_pnl=D(position) + D(trades),
        status=COMPLETE,
        missing_prices=frozenset(),
    )


MISSING_CURRENT = AssetPnLResult(
    position_pnl=None,
    trades_pnl=None,
    daily_pnl=None,
    status=MISSING,
    missing_prices=frozenset({MissingReferencePrice.CURRENT}),
)
# Only the D-1 price is missing: trades_pnl (200) is known, position_pnl is not.
MISSING_PREVIOUS = AssetPnLResult(
    position_pnl=None,
    trades_pnl=D("200"),
    daily_pnl=None,
    status=MISSING,
    missing_prices=frozenset({MissingReferencePrice.PREVIOUS}),
)

Figures = tuple[str | None, str | None, str | None, str | None]


@pytest.mark.parametrize(
    ("expected", "results", "previous_cumulative", "status", "figures"),
    [
        # A: 1000 + 400; B: −500 + 0 → position 500, trades 400, daily 900; cumulative 100 + 900.
        pytest.param(
            {ASSET_A, ASSET_B},
            {ASSET_A: complete("1000", "400"), ASSET_B: complete("-500", "0")},
            "100",
            COMPLETE,
            ("500", "400", "900", "1000"),
            id="summed-per-component-and-accumulated",
        ),
        # OQ-4: cumulative P&L starts at 0 before the first entry.
        pytest.param(set(), {}, "0", COMPLETE, ("0", "0", "0", "0"), id="no-expected-asset"),
        pytest.param(
            {ASSET_A, ASSET_B},
            {ASSET_A: complete("1000", "400"), ASSET_B: MISSING_CURRENT},
            "100",
            MISSING,
            (None, None, None, None),
            id="incomplete-asset-nulls-the-total-not-a-partial-sum",
        ),
        pytest.param(
            {ASSET_A, ASSET_C},
            {ASSET_A: complete("1000", "0")},
            "0",
            MISSING,
            (None, None, None, None),
            id="expected-asset-without-a-result",
        ),
        # B's trades_pnl is known on every expected asset: 400 + 200 = 600.
        pytest.param(
            {ASSET_A, ASSET_B},
            {ASSET_A: complete("1000", "400"), ASSET_B: MISSING_PREVIOUS},
            "0",
            MISSING,
            (None, "600", None, None),
            id="component-known-on-every-asset-is-summed",
        ),
        # §8.3: cumulative unavailable from the first gap onward; the day's own P&L is still valid.
        pytest.param(
            {ASSET_A},
            {ASSET_A: complete("1000", "0")},
            None,
            COMPLETE,
            ("1000", "0", "1000", None),
            id="broken-chain-keeps-cumulative-null",
        ),
        # OQ-10: a same-day round trip leaves Q = 0 but the asset is expected; its 2000 counts.
        pytest.param(
            {ASSET_A, ASSET_B},
            {ASSET_A: complete("1000", "0"), ASSET_B: complete("0", "2000")},
            "0",
            COMPLETE,
            ("1000", "2000", "3000", "3000"),
            id="zero-quantity-expected-asset-counts",
        ),
        # OQ-1: 10 × (0 − 99990) = −999900 on the day after maturity; 5000 − 999900 = −994900.
        pytest.param(
            {ASSET_A},
            {ASSET_A: complete("-999900", "0")},
            "5000",
            COMPLETE,
            ("-999900", "0", "-999900", "-994900"),
            id="post-maturity-position-flows-in",
        ),
    ],
)
def test_the_portfolio_sums_every_expected_asset(
    expected: set[UUID],
    results: Mapping[UUID, AssetPnLResult],
    previous_cumulative: str | None,
    status: CalculationCompleteness,
    figures: Figures,
) -> None:
    result = aggregate_pnl(
        expected_assets=expected,
        asset_results=results,
        previous_cumulative=None if previous_cumulative is None else D(previous_cumulative),
    )

    assert result.status is status
    assert (
        result.position_pnl,
        result.trades_pnl,
        result.daily_pnl,
        result.cumulative_pnl,
    ) == tuple(None if f is None else D(f) for f in figures)


def test_a_result_for_an_asset_that_is_not_expected_is_rejected() -> None:
    # OQ-10: results exist exactly for expected assets; anything else is a caller bug.
    with pytest.raises(ValueError, match="not expected"):
        aggregate_pnl(
            expected_assets={ASSET_A},
            asset_results={ASSET_A: complete("0", "0"), ASSET_B: complete("1", "0")},
            previous_cumulative=D("0"),
        )
