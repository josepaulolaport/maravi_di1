"""Per-asset daily P&L attribution (spec §8.1, §8.3; OQ-1, OQ-2, OQ-4).

    position_pnl = Q[D-1] × (PU_D − PU_{D-1})
    trades_pnl   = Σ q_i × (PU_D − PU_exec_i)
    daily_pnl    = position_pnl + trades_pnl

Prices are exact-date reference PUs chosen by the caller; after maturity the caller passes 0 as
the current reference PU (OQ-1). The multiplier is not applied (OQ-2). Results are exact: money
is never quantized here (OQ-3).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from di1.modules.pnl.domain.results import (
    AssetPnLResult,
    CalculationCompleteness,
    MissingReferencePrice,
)
from di1.shared.decimals import financial_context

_ZERO = Decimal(0)


@dataclass(frozen=True, slots=True)
class PnLTrade:
    """What P&L needs from a trade: buys positive, sells negative (schema ``INTEGER``), at the
    execution PU. The application layer maps Ledger's trade record to it."""

    signed_quantity: int
    execution_pu: Decimal


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

        with financial_context():
            position_pnl: Decimal | None
            if not holds_position:
                position_pnl = _ZERO  # OQ-4: exactly 0, no D-1 price needed
            elif previous_reference_pu is None or current_reference_pu is None:
                position_pnl = None
            else:
                position_pnl = _unsigned_zero(
                    previous_position * (current_reference_pu - previous_reference_pu)
                )

            trades_pnl: Decimal | None
            if not day_trades:
                trades_pnl = _ZERO
            elif current_reference_pu is None:
                trades_pnl = None
            else:
                trades_pnl = sum(
                    (
                        t.signed_quantity * (current_reference_pu - t.execution_pu)
                        for t in day_trades
                    ),
                    _ZERO,
                )

            daily_pnl = (
                None if position_pnl is None or trades_pnl is None else position_pnl + trades_pnl
            )

        return AssetPnLResult(
            position_pnl=position_pnl,
            trades_pnl=trades_pnl,
            daily_pnl=daily_pnl,
            status=CalculationCompleteness.MISSING if missing else CalculationCompleteness.COMPLETE,
            missing_prices=frozenset(missing),
        )


def _unsigned_zero(value: Decimal) -> Decimal:
    """A short times a zero move is ``-0`` in ``Decimal``; P&L never carries that sign."""
    return value.copy_abs() if value.is_zero() else value
