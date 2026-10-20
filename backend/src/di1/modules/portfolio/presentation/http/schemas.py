"""HTTP shapes of the Portfolio reads: the frontend contract ``frontend/src/api/contract/
portfolio.ts`` with the OQ-31 status names. Decimals cross as strings in plain notation; absent
values are ``null``, never 0; a chain with no status is ``NOT_PROCESSED``; instants are sent in
UTC. The read models are mapped one to one: the HTTP layer only renames and formats
(portfolio/public.py)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Self
from uuid import UUID

from pydantic import BaseModel

from di1.modules.pnl.public import CalculationCompleteness
from di1.modules.portfolio.public import (
    CashSummaryView,
    PnLPointView,
    PortfolioSummaryView,
    PositionRowView,
    PositionsSummaryView,
    PositionTableView,
    ValuationStatus,
)
from di1.modules.prices.public import PriceSource
from di1.modules.processing.public import ChainStatus
from di1.platform.http import UtcDatetime
from di1.shared.decimals import to_plain


class ShownChainStatus(StrEnum):
    """A chain's status on a date as the API sends it: ``ChainStatus``, or NOT_PROCESSED."""

    NOT_PROCESSED = "NOT_PROCESSED"
    PROCESSED = "PROCESSED"
    PROCESSED_WITH_ISSUES = "PROCESSED_WITH_ISSUES"
    RUNNING = "RUNNING"
    FAILED = "FAILED"

    @classmethod
    def of(cls, status: ChainStatus | None) -> ShownChainStatus:
        return cls.NOT_PROCESSED if status is None else cls(status.value)


def _decimal(value: Decimal | None) -> str | None:
    return None if value is None else to_plain(value)


class CashSummaryResponse(BaseModel):
    status: ShownChainStatus
    balance: str | None
    trades_cash_flow: str | None
    deposits: str | None
    withdrawals: str | None
    published_at: UtcDatetime | None

    @classmethod
    def of(cls, view: CashSummaryView) -> Self:
        return cls(
            status=ShownChainStatus.of(view.status),
            balance=_decimal(view.balance),
            trades_cash_flow=_decimal(view.trades_cash_flow),
            deposits=_decimal(view.deposits),
            withdrawals=_decimal(view.withdrawals),
            published_at=view.published_at,
        )


class PositionsSummaryResponse(BaseModel):
    status: ShownChainStatus
    published_at: UtcDatetime | None
    market_value: str | None
    valuation_status: CalculationCompleteness | None
    position_pnl: str | None
    trades_pnl: str | None
    daily_pnl: str | None
    cumulative_pnl: str | None
    pnl_status: CalculationCompleteness | None

    @classmethod
    def of(cls, view: PositionsSummaryView) -> Self:
        return cls(
            status=ShownChainStatus.of(view.status),
            published_at=view.published_at,
            market_value=_decimal(view.market_value),
            valuation_status=view.valuation_status,
            position_pnl=_decimal(view.position_pnl),
            trades_pnl=_decimal(view.trades_pnl),
            daily_pnl=_decimal(view.daily_pnl),
            cumulative_pnl=_decimal(view.cumulative_pnl),
            pnl_status=view.pnl_status,
        )


class PortfolioSummaryResponse(BaseModel):
    date: date
    cash: CashSummaryResponse
    positions: PositionsSummaryResponse
    aum: str | None

    @classmethod
    def of(cls, view: PortfolioSummaryView) -> Self:
        return cls(
            date=view.date,
            cash=CashSummaryResponse.of(view.cash),
            positions=PositionsSummaryResponse.of(view.positions),
            aum=_decimal(view.aum),
        )


class PositionRowResponse(BaseModel):
    asset_id: UUID
    asset_code: str
    maturity_date: date | None
    quantity: int
    average_entry_pu: str | None
    average_entry_rate: str | None
    reference_source: PriceSource | None
    reference_pu: str | None
    reference_rate: str | None
    reference_price_changed: bool
    financial_total: str | None
    position_pnl: str | None
    trades_pnl: str | None
    daily_pnl: str | None
    valuation_status: ValuationStatus
    pnl_status: CalculationCompleteness

    @classmethod
    def of(cls, row: PositionRowView) -> Self:
        return cls(
            asset_id=row.asset_id,
            asset_code=row.asset_code,
            maturity_date=row.maturity_date,
            quantity=row.quantity,
            average_entry_pu=_decimal(row.average_entry_pu),
            average_entry_rate=_decimal(row.average_entry_rate),
            reference_source=row.reference_source,
            reference_pu=_decimal(row.reference_pu),
            reference_rate=_decimal(row.reference_rate),
            reference_price_changed=row.reference_price_changed,
            financial_total=_decimal(row.financial_total),
            position_pnl=_decimal(row.position_pnl),
            trades_pnl=_decimal(row.trades_pnl),
            daily_pnl=_decimal(row.daily_pnl),
            valuation_status=row.valuation_status,
            pnl_status=row.pnl_status,
        )


class PortfolioPositionsResponse(BaseModel):
    date: date
    status: ShownChainStatus
    published_at: UtcDatetime | None
    items: list[PositionRowResponse]

    @classmethod
    def of(cls, view: PositionTableView) -> Self:
        return cls(
            date=view.date,
            status=ShownChainStatus.of(view.status),
            published_at=view.published_at,
            items=[PositionRowResponse.of(r) for r in view.items],
        )


class PnlPointResponse(BaseModel):
    """One calendar date of the range, processed or not (OQ-41, OQ-49)."""

    date: date
    daily_pnl: str | None
    range_cumulative_pnl: str
    status: ShownChainStatus

    @classmethod
    def of(cls, point: PnLPointView) -> Self:
        return cls(
            date=point.date,
            daily_pnl=_decimal(point.daily_pnl),
            range_cumulative_pnl=to_plain(point.range_cumulative_pnl),
            status=ShownChainStatus.of(point.status),
        )


class PnlSeriesResponse(BaseModel):
    items: list[PnlPointResponse]

    @classmethod
    def of(cls, points: Sequence[PnLPointView]) -> Self:
        return cls(items=[PnlPointResponse.of(p) for p in points])
