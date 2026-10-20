"""Portfolio P&L aggregation (spec §8.1, §8.3; OQ-4, OQ-10).

Each component is the sum over **every expected asset**: if any expected asset lacks it, the
portfolio component is ``None``, never the sum of the available ones. ``cumulative = previous +
daily`` and stays ``None`` once the chain is broken (``previous_cumulative`` is ``None``); the
caller passes 0 before the first entry (OQ-4). Deposits and withdrawals are not inputs: they are
never P&L (§8.1).

The aggregation assumes a valid D-1 state. Processing calls it for D only when the positions chain
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
from di1.shared.decimals import ZERO, financial_context


def aggregate_pnl(
    expected_assets: Set[UUID],
    asset_results: Mapping[UUID, AssetPnLResult],
    previous_cumulative: Decimal | None,
) -> PortfolioPnLResult:
    unexpected = asset_results.keys() - expected_assets
    if unexpected:
        raise ValueError(f"P&L results for assets not expected on the day: {sorted(unexpected)}")

    complete = all(
        (result := asset_results.get(asset)) is not None
        and result.status is CalculationCompleteness.COMPLETE
        for asset in expected_assets
    )

    def total(component: Callable[[AssetPnLResult], Decimal | None]) -> Decimal | None:
        values: list[Decimal] = []
        for asset in sorted(expected_assets):  # a fixed order, should a sum ever round
            result = asset_results.get(asset)
            value = None if result is None else component(result)
            if value is None:
                return None
            values.append(value)
        return sum(values, ZERO)

    with financial_context():
        position_pnl = total(lambda r: r.position_pnl)
        trades_pnl = total(lambda r: r.trades_pnl)
        daily_pnl = total(lambda r: r.daily_pnl)
        cumulative_pnl = (
            None
            if previous_cumulative is None or daily_pnl is None
            else previous_cumulative + daily_pnl
        )

    return PortfolioPnLResult(
        position_pnl=position_pnl,
        trades_pnl=trades_pnl,
        daily_pnl=daily_pnl,
        cumulative_pnl=cumulative_pnl,
        status=CalculationCompleteness.COMPLETE if complete else CalculationCompleteness.MISSING,
    )
