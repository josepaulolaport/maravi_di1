"""Market value (spec §8.2, §8.3, §7.4; OQ-1, OQ-2, OQ-10).

    financial_total[a, D]      = Q[a, D] × reference_PU[a, D]
    positions_market_value[D]  = Σ financial_total[a, D]

Pure: it takes the day's closing quantities and the reference PUs the caller resolved once with
`maturity.reference_pu_on` (the exact-date preferred price, ``None`` without one, 0 after
maturity, OQ-1). AUM = cash + market value is not computed here: ``PortfolioService`` computes it
on read from both published chains of the date (OQ-21, OQ-38, OQ-50 item 1).
A missing required price leaves the dependent figures null, never zero: the portfolio total is
not complete if any expected asset is missing. A flat position is worth zero without a price.
The multiplier is not applied (OQ-2). Money is kept exact (OQ-3).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from di1.modules.portfolio.domain.errors import PortfolioError
from di1.shared.decimals import ZERO, financial_context, unsigned


class ValuationStatus(StrEnum):
    """Mirrors ``valuation_status`` in ``position_metrics`` and ``portfolio_metrics``. COMPLETE and
    MISSING are PnL's ``CalculationCompleteness`` values, which a portfolio day stores."""

    COMPLETE = "COMPLETE"
    MISSING = "MISSING"
    NOT_REQUIRED = "NOT_REQUIRED"  # a flat position: worth 0 with or without a price


@dataclass(frozen=True)
class AssetValuationInput:
    """One expected asset on the valuation date: its closing quantity and its reference PU as
    resolved by the caller (``None`` when there is no price)."""

    asset_id: UUID
    quantity: int
    reference_pu: Decimal | None


@dataclass(frozen=True)
class AssetValuation:
    """``reference_pu`` is the PU used: the reference price's, 0 after maturity, or ``None`` when
    there is none (MISSING, or a flat position without a price, NOT_REQUIRED)."""

    asset_id: UUID
    reference_pu: Decimal | None
    financial_total: Decimal | None
    status: ValuationStatus


@dataclass(frozen=True)
class PortfolioValuation:
    """``status`` is COMPLETE or MISSING and describes the market value."""

    date: date
    assets: tuple[AssetValuation, ...]
    positions_market_value: Decimal | None
    status: ValuationStatus


def value_positions(date: date, assets: Sequence[AssetValuationInput]) -> PortfolioValuation:
    """Values every expected asset of one day, then the portfolio's market value."""
    asset_ids = [a.asset_id for a in assets]
    if len(set(asset_ids)) != len(asset_ids):
        raise PortfolioError("each asset is valued at most once per day")
    with financial_context():
        valued = tuple(_value(a) for a in sorted(assets, key=lambda a: a.asset_id))
        totals = [v.financial_total for v in valued]
        market_value = (
            None
            if any(t is None for t in totals)
            else sum((t for t in totals if t is not None), ZERO)
        )
    return PortfolioValuation(
        date=date,
        assets=valued,
        positions_market_value=market_value,
        status=ValuationStatus.MISSING if market_value is None else ValuationStatus.COMPLETE,
    )


def _value(asset: AssetValuationInput) -> AssetValuation:
    if asset.quantity == 0:
        return AssetValuation(
            asset.asset_id, asset.reference_pu, ZERO, ValuationStatus.NOT_REQUIRED
        )
    if asset.reference_pu is None:
        return AssetValuation(asset.asset_id, None, None, ValuationStatus.MISSING)
    # A short position at a zero PU must not yield a negative zero.
    financial_total = unsigned(asset.quantity * asset.reference_pu)
    return AssetValuation(
        asset.asset_id, asset.reference_pu, financial_total, ValuationStatus.COMPLETE
    )
