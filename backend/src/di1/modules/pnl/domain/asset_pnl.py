"""Daily P&L of one asset: daily = position_pnl + trades_pnl (spec §8.1, §8.3).

Composes `position_pnl` and `trades_pnl` and records which exact-date reference price was missing.
``daily_pnl`` is set only when both components are. Results are exact: money is never quantized
here (OQ-3).
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from di1.modules.pnl.domain.position_pnl import calculate_position_pnl
from di1.modules.pnl.domain.results import (
    AssetPnLResult,
    CalculationCompleteness,
    MissingReferencePrice,
)
from di1.modules.pnl.domain.trade import PnLTrade
from di1.modules.pnl.domain.trades_pnl import calculate_trades_pnl
from di1.shared.decimals import financial_context


class AssetPnLCalculator:
    def calculate(
        self,
        previous_position: int,
        day_trades: Sequence[PnLTrade],
        previous_reference_pu: Decimal | None,
        current_reference_pu: Decimal | None,
    ) -> AssetPnLResult:
        """``previous_position`` is the signed closing quantity Q[D-1]."""
        holds_position = previous_position != 0
        missing: set[MissingReferencePrice] = set()
        if holds_position and previous_reference_pu is None:
            missing.add(MissingReferencePrice.PREVIOUS)
        if (holds_position or day_trades) and current_reference_pu is None:
            missing.add(MissingReferencePrice.CURRENT)

        position_pnl = calculate_position_pnl(
            previous_position, previous_reference_pu, current_reference_pu
        )
        trades_pnl = calculate_trades_pnl(day_trades, current_reference_pu)
        daily_pnl: Decimal | None = None
        if position_pnl is not None and trades_pnl is not None:
            with financial_context():
                daily_pnl = position_pnl + trades_pnl

        return AssetPnLResult(
            position_pnl=position_pnl,
            trades_pnl=trades_pnl,
            daily_pnl=daily_pnl,
            status=CalculationCompleteness.MISSING if missing else CalculationCompleteness.COMPLETE,
            missing_prices=frozenset(missing),
        )
