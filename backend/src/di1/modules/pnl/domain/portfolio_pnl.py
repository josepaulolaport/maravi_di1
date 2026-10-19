"""Portfolio P&L aggregation (spec §8.1, §8.3; OQ-4, OQ-10).

Each component is the sum over **every expected asset**: if any expected asset lacks it, the
portfolio component is ``None``, never the sum of the available ones. ``cumulative = previous +
daily`` and stays ``None`` once the chain is broken (``previous_cumulative`` is ``None``); the
caller passes 0 before the first entry (OQ-4). Deposits and withdrawals are not inputs: they are
never P&L (§8.1).

The calculator assumes a valid D-1 state. Processing calls it for D only when the positions chain
of D-1 is ``PROCESSED`` or ``PROCESSED_WITH_ISSUES``, or D-1 is that chain's zero state (no earlier
date with a positions status and no trade on or before D-1, OQ-40 item 5). Otherwise the
positions chain fails on D with ``POSITIONS_PREDECESSOR_MISSING`` ("Dia anterior não processado")
before any P&L is calculated (OQ-31); on an ALL run only that chain stops (OQ-36).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Set
from decimal import Decimal
from uuid import UUID

from di1.modules.pnl.domain.results import (
    AssetPnLResult,
    CalculationCompleteness,
    PortfolioPnLResult,
)
from di1.shared.decimals import financial_context


class PortfolioPnLCalculator:
    def aggregate(
        self,
        expected_assets: Set[UUID],
        asset_results: Mapping[UUID, AssetPnLResult],
        previous_cumulative: Decimal | None,
    ) -> PortfolioPnLResult:
        unexpected = asset_results.keys() - expected_assets
        if unexpected:
            raise ValueError(
                f"P&L results for assets not expected on the day: {sorted(unexpected)}"
            )

        incomplete = frozenset(
            asset
            for asset in expected_assets
            if (result := asset_results.get(asset)) is None
            or result.status is not CalculationCompleteness.COMPLETE
        )

        def total(component: Callable[[AssetPnLResult], Decimal | None]) -> Decimal | None:
            values: list[Decimal] = []
            for asset in sorted(expected_assets):  # a fixed order, should a sum ever round
                result = asset_results.get(asset)
                value = None if result is None else component(result)
                if value is None:
                    return None
                values.append(value)
            return sum(values, Decimal(0))

        with financial_context():
            position_pnl = total(lambda r: r.position_pnl)
            trades_pnl = total(lambda r: r.trades_pnl)
            daily_pnl = total(lambda r: r.daily_pnl)
            cumulative_pnl = (
                None
                if previous_cumulative is None or daily_pnl is None
                else previous_cumulative + daily_pnl
            )

        def status(value: Decimal | None) -> CalculationCompleteness:
            if value is None:
                return CalculationCompleteness.MISSING
            return CalculationCompleteness.COMPLETE

        return PortfolioPnLResult(
            position_pnl=position_pnl,
            trades_pnl=trades_pnl,
            daily_pnl=daily_pnl,
            cumulative_pnl=cumulative_pnl,
            status=CalculationCompleteness.MISSING
            if incomplete
            else CalculationCompleteness.COMPLETE,
            cumulative_status=status(cumulative_pnl),
            incomplete_assets=incomplete,
        )
