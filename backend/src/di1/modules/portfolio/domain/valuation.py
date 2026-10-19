"""Market value and AUM (spec §8.2, §8.3, §7.4; OQ-1, OQ-2, OQ-10).

    financial_total[a, D]      = Q[a, D] × reference_PU[a, D]
    positions_market_value[D]  = Σ financial_total[a, D]
    aum[D]                     = cash_balance[D] + positions_market_value[D]

Pure: it takes the day's closing quantities, the exact-date reference PUs chosen by the caller
(with the source each came from, for traceability), the maturities and the cash balance.
A missing required price leaves the dependent figures null, never zero: the portfolio total is
not complete if any expected asset is missing. A flat position is worth zero without a price.
After maturity the reference PU is 0 by definition and no price is accepted (OQ-1). The
multiplier is not applied (OQ-2). Money is kept exact (OQ-3).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum, StrEnum
from uuid import UUID

from di1.modules.portfolio.domain.errors import AccountingError
from di1.shared.decimals import financial_context

ZERO = Decimal("0")


class ValuationStatus(Enum):
    """Mirrors ``valuation_status`` in ``position_metrics`` and ``portfolio_metrics``."""

    COMPLETE = "COMPLETE"
    MISSING = "MISSING"
    NOT_REQUIRED = "NOT_REQUIRED"  # a flat position: worth 0 with or without a price


class ReferenceSource(StrEnum):
    """The source of a reference PU. Same values as Prices' ``PriceSource``; Portfolio's
    application layer maps one onto the other (the domain imports no other module)."""

    MANUAL = "MANUAL"
    B3 = "B3"


@dataclass(frozen=True)
class AssetValuationInput:
    """One expected asset on the valuation date: its closing quantity, its maturity and the
    exact-date reference PU, ``None`` when there is no price, with its source (MANUAL or B3) so
    the price used stays traceable (OQ-9, OQ-25): a PU and its source are given together or not at
    all. Past maturity the caller passes neither; the calculator sets the PU to 0 (OQ-1)."""

    asset_id: UUID
    quantity: int
    maturity_date: date
    reference_pu: Decimal | None
    reference_source: ReferenceSource | None

    def __post_init__(self) -> None:
        if (self.reference_source is None) != (self.reference_pu is None):
            raise AccountingError("a reference PU and its source go together")


@dataclass(frozen=True)
class AssetValuation:
    """``reference_pu`` is the PU used: the reference price's, 0 after maturity, or ``None`` when
    there is none (MISSING, or a flat position without a price, NOT_REQUIRED).
    ``reference_source`` is its source; ``None`` without a price and after maturity."""

    asset_id: UUID
    reference_pu: Decimal | None
    reference_source: ReferenceSource | None
    financial_total: Decimal | None
    status: ValuationStatus


@dataclass(frozen=True)
class PortfolioValuation:
    """``status`` is COMPLETE or MISSING and describes the market value; ``aum`` is also null
    when the cash balance is unknown."""

    date: date
    assets: tuple[AssetValuation, ...]
    positions_market_value: Decimal | None
    aum: Decimal | None
    status: ValuationStatus


class ValuationCalculator:
    """Values every expected asset of one day, then the portfolio total and AUM."""

    def calculate_day(
        self,
        date: date,
        assets: Sequence[AssetValuationInput],
        cash_balance: Decimal | None,
    ) -> PortfolioValuation:
        asset_ids = [a.asset_id for a in assets]
        if len(set(asset_ids)) != len(asset_ids):
            raise AccountingError("each asset is valued at most once per day")
        with financial_context():
            valued = tuple(_value(a, date) for a in sorted(assets, key=lambda a: a.asset_id))
            totals = [v.financial_total for v in valued]
            market_value = (
                None
                if any(t is None for t in totals)
                else sum((t for t in totals if t is not None), ZERO)
            )
            aum = (
                None
                if market_value is None or cash_balance is None
                else cash_balance + market_value
            )
        return PortfolioValuation(
            date=date,
            assets=valued,
            positions_market_value=market_value,
            aum=aum,
            status=ValuationStatus.MISSING if market_value is None else ValuationStatus.COMPLETE,
        )


def _value(asset: AssetValuationInput, on: date) -> AssetValuation:
    reference_pu, source = asset.reference_pu, asset.reference_source
    if on > asset.maturity_date:
        if reference_pu is not None:
            raise AccountingError(
                f"no reference price is accepted after maturity for {asset.asset_id}"
            )
        reference_pu = ZERO
    if asset.quantity == 0:
        return AssetValuation(
            asset.asset_id, reference_pu, source, ZERO, ValuationStatus.NOT_REQUIRED
        )
    if reference_pu is None:
        return AssetValuation(asset.asset_id, None, None, None, ValuationStatus.MISSING)
    # 0 + Q × PU: a short position at a zero PU must not yield a negative zero.
    financial_total = ZERO + asset.quantity * reference_pu
    return AssetValuation(
        asset.asset_id, reference_pu, source, financial_total, ValuationStatus.COMPLETE
    )
