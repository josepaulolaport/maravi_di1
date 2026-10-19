"""PnL's frozen public contract (plan §3, W0.3c; interfaces.md "PnL")."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from di1.modules.pnl.public import (
    AssetPnLCalculator,
    CalculationCompleteness,
    PnLTrade,
    PortfolioPnLCalculator,
)


def test_completeness_matches_the_pnl_status_check() -> None:
    assert {status.value for status in CalculationCompleteness} == {"COMPLETE", "MISSING"}


def test_the_calculators_are_usable_through_the_contract() -> None:
    asset = uuid4()
    result = AssetPnLCalculator().calculate(
        previous_position=10,
        day_trades=[PnLTrade(signed_quantity=-4, execution_pu=Decimal("90100"))],
        previous_reference_pu=Decimal("90000"),
        current_reference_pu=Decimal("90050"),
    )
    portfolio = PortfolioPnLCalculator().aggregate(
        expected_assets={asset}, asset_results={asset: result}, previous_cumulative=Decimal("0")
    )

    # position 10 × 50 = 500; trades −4 × (90050 − 90100) = 200 (spec §8.1)
    assert (result.position_pnl, result.trades_pnl, result.daily_pnl) == (
        Decimal("500"),
        Decimal("200"),
        Decimal("700"),
    )
    assert portfolio.cumulative_pnl == Decimal("700")
